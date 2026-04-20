"""Transport layer wrapping the Hamilton VENUS Web API (REST + SignalR).

Provides both HTTP REST calls and SignalR real-time notifications.
In simulation mode, all responses are simulated without needing VENUS installed.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any, Callable, Dict, List, Optional

import requests
from signalrcore.hub_connection_builder import HubConnectionBuilder

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "http://localhost:51745"
API_PREFIX = "/api/vector/v2"
SIGNALR_HUB = "/signalR"


class VenusClient:
    """HTTP + SignalR client for the Hamilton VENUS Web API."""

    def __init__(self, base_url: str = DEFAULT_BASE_URL) -> None:
        self.base_url = base_url.rstrip("/")
        self._api_url = f"{self.base_url}{API_PREFIX}"
        self._session = requests.Session()
        self._hub: Optional[Any] = None
        self._hub_lock = threading.Lock()

        # SignalR callback registrations
        self._callbacks: Dict[str, List[Callable]] = {
            "NewRuntimeStatus": [],
            "NewRuntimeError": [],
            "NewRuntimeTrace": [],
            "OnProgressChanged": [],
            "OnDeviceCreated": [],
            "OnLoadMethod": [],
        }

    # ── REST Methods ──────────────────────────────────────────────────

    def _raise_with_detail(self, resp: requests.Response) -> None:
        """Raise an HTTPError that includes the response body for diagnostics."""
        try:
            detail = resp.text
        except Exception:
            detail = "(no response body)"
        raise requests.HTTPError(
            f"{resp.status_code} {resp.reason} for url: {resp.url}\nResponse body: {detail}",
            response=resp,
        )

    def _get(self, path: str, params: Optional[Dict] = None) -> Any:
        url = f"{self._api_url}{path}"
        resp = self._session.get(url, params=params, timeout=30)
        if not resp.ok:
            self._raise_with_detail(resp)
        return resp.json() if resp.content else None

    def _post(self, path: str, json_data: Optional[Dict] = None) -> Any:
        url = f"{self._api_url}{path}"
        resp = self._session.post(url, json=json_data, timeout=30)
        if not resp.ok:
            self._raise_with_detail(resp)
        return resp.json() if resp.content else None

    def _put(self, path: str, json_data: Optional[Dict] = None) -> Any:
        url = f"{self._api_url}{path}"
        resp = self._session.put(url, json=json_data, timeout=30)
        if not resp.ok:
            self._raise_with_detail(resp)
        return resp.json() if resp.content else None

    def load_method(self, file_path: str, simulation: bool = False, hwnd: int = 0) -> Any:
        return self._put("/execution/load", {
            "filePath": file_path,
            "simulation": simulation,
            "parentWindowHandle": hwnd,
        })

    def start_method(self) -> Any:
        return self._post("/execution/start")

    def pause_method(self) -> Any:
        return self._post("/execution/pause")

    def resume_method(self) -> Any:
        return self._post("/execution/resume")

    def abort_method(self) -> Any:
        return self._post("/execution/abort")

    def unload_method(self) -> Any:
        return self._post("/execution/unload-method")

    def get_runtime_devices(self) -> Any:
        return self._get("/devices/registered")

    def get_runtime_devices_with_ids(self) -> Any:
        return self._get("/devices/runtime")

    def get_loaded_method(self) -> Any:
        return self._get("/execution/loaded-method")

    def get_run_state(self) -> Any:
        return self._get("/execution/run-state")

    def get_deck_layout(self, device_id: int) -> Any:
        return self._get(f"/devices/deck-layout/{device_id}")

    def get_current_run_data(self) -> Any:
        return self._get("/execution/current-run-data")

    def get_runtime_data(self, start_date: Optional[str] = None, end_date: Optional[str] = None) -> Any:
        params: Dict[str, Any] = {}
        if start_date or end_date:
            params["filter"] = True
            if start_date:
                params["fromDate"] = start_date
            if end_date:
                params["toDate"] = end_date
        return self._get("/files/runtime-data", params=params)

    def get_detailed_run_data(self, run_guid: str) -> Any:
        return self._get(f"/files/detailed-run-data/{run_guid}")

    def get_system_version(self) -> Any:
        return self._get("/system/version")

    # ── SignalR ───────────────────────────────────────────────────────

    def connect_signalr(self) -> None:
        """Connect to the Venus SignalR hub for real-time notifications."""
        with self._hub_lock:
            if self._hub is not None:
                return

            hub_url = f"{self.base_url}{SIGNALR_HUB}"
            self._hub = (
                HubConnectionBuilder()
                .with_url(hub_url)
                .with_automatic_reconnect({
                    "type": "raw",
                    "keep_alive_interval": 10,
                    "reconnect_interval": 5,
                    "max_attempts": 5,
                })
                .build()
            )

            # Register handlers
            for event_name, callback_list in self._callbacks.items():
                self._hub.on(event_name, lambda args, _cbs=callback_list: self._dispatch(args, _cbs))

            self._hub.start()
            logger.info("SignalR hub connected to %s", hub_url)

    def disconnect_signalr(self) -> None:
        with self._hub_lock:
            if self._hub is not None:
                self._hub.stop()
                self._hub = None
                logger.info("SignalR hub disconnected")

    def on(self, event_name: str, callback: Callable) -> None:
        """Register a callback for a SignalR event."""
        if event_name in self._callbacks:
            self._callbacks[event_name].append(callback)
        else:
            logger.warning("Unknown SignalR event: %s", event_name)

    def off(self, event_name: str, callback: Callable) -> None:
        """Remove a callback for a SignalR event."""
        if event_name in self._callbacks:
            try:
                self._callbacks[event_name].remove(callback)
            except ValueError:
                pass

    def _dispatch(self, args: list, callbacks: List[Callable]) -> None:
        for cb in callbacks:
            try:
                cb(args)
            except Exception:
                logger.exception("Error in SignalR callback")

    # ── Health check ──────────────────────────────────────────────────

    def is_reachable(self) -> bool:
        """Check if the Venus Web API is reachable."""
        try:
            self._session.get(f"{self._api_url}/system/version", timeout=5)
            return True
        except Exception:
            return False


class SimulatedVenusClient:
    """Simulates the Venus Web API for testing without VENUS installed.

    Tracks internal state and produces realistic responses.
    """

    def __init__(self) -> None:
        self.base_url = "http://localhost:51745 (simulated)"
        self._status = "Undefined"
        self._method_loaded = False
        self._loaded_file = ""
        self._is_running = False
        self._is_paused = False
        self._lock = threading.Lock()

        # Callbacks for simulated events (same interface as VenusClient)
        self._callbacks: Dict[str, List[Callable]] = {
            "NewRuntimeStatus": [],
            "NewRuntimeError": [],
            "NewRuntimeTrace": [],
            "OnProgressChanged": [],
            "OnDeviceCreated": [],
            "OnLoadMethod": [],
        }

    def _fire(self, event: str, data: Any) -> None:
        for cb in self._callbacks.get(event, []):
            try:
                cb([data])
            except Exception:
                logger.exception("Error in simulated callback")

    def on(self, event_name: str, callback: Callable) -> None:
        if event_name in self._callbacks:
            self._callbacks[event_name].append(callback)

    def off(self, event_name: str, callback: Callable) -> None:
        if event_name in self._callbacks:
            try:
                self._callbacks[event_name].remove(callback)
            except ValueError:
                pass

    def connect_signalr(self) -> None:
        logger.info("Simulated SignalR connected")

    def disconnect_signalr(self) -> None:
        logger.info("Simulated SignalR disconnected")

    def is_reachable(self) -> bool:
        return True

    # ── Simulated REST methods ────────────────────────────────────────

    def load_method(self, file_path: str, simulation: bool = False, hwnd: int = 0) -> Dict:
        with self._lock:
            self._loaded_file = file_path
            self._status = "Loading"
            self._fire("NewRuntimeStatus", {"status": "Loading"})
            self._fire("NewRuntimeTrace", {"message": f"Loading method: {file_path}"})

        # Simulate loading delay
        time.sleep(1.0)

        with self._lock:
            self._method_loaded = True
            self._status = "Initialized"
            self._fire("OnLoadMethod", {"filePath": file_path, "status": "Initialized"})
            self._fire("NewRuntimeStatus", {"status": "Initialized"})
            self._fire("NewRuntimeTrace", {"message": "Method loaded and initialized"})

        return {"status": "Initialized", "filePath": file_path}

    def start_method(self) -> Dict:
        with self._lock:
            self._is_running = True
            self._status = "Running"
            self._fire("NewRuntimeStatus", {"status": "Running"})
            self._fire("NewRuntimeTrace", {"message": "Method execution started"})
        return {"status": "Running"}

    def pause_method(self) -> Dict:
        with self._lock:
            self._is_paused = True
            self._status = "Paused"
            self._fire("NewRuntimeStatus", {"status": "Paused"})
            self._fire("NewRuntimeTrace", {"message": "Method execution paused"})
        return {"status": "Paused"}

    def resume_method(self) -> Dict:
        with self._lock:
            self._is_paused = False
            self._status = "Running"
            self._fire("NewRuntimeStatus", {"status": "Running"})
            self._fire("NewRuntimeTrace", {"message": "Method execution resumed"})
        return {"status": "Running"}

    def abort_method(self) -> Dict:
        with self._lock:
            self._is_running = False
            self._is_paused = False
            self._status = "Aborted"
            self._fire("NewRuntimeStatus", {"status": "Aborted"})
            self._fire("NewRuntimeTrace", {"message": "Method execution aborted"})
        return {"status": "Aborted"}

    def unload_method(self) -> Dict:
        with self._lock:
            self._method_loaded = False
            self._is_running = False
            self._is_paused = False
            self._loaded_file = ""
            self._status = "Undefined"
            self._fire("NewRuntimeStatus", {"status": "Undefined"})
            self._fire("NewRuntimeTrace", {"message": "Method unloaded"})
        return {"status": "Undefined"}

    def get_runtime_devices(self) -> List[Dict]:
        return [
            {"deviceName": "ML_STAR", "deviceDisplayName": "ML STAR", "hasDeckLayout": True},
            {"deviceName": "HHS", "deviceDisplayName": "Heater Shaker", "hasDeckLayout": False},
            {"deviceName": "TCC", "deviceDisplayName": "Temperature Controller", "hasDeckLayout": False},
        ]

    def get_runtime_devices_with_ids(self) -> List[Dict]:
        return [
            {"deviceId": 1, "deviceName": "ML_STAR", "deviceDisplayName": "ML STAR",
             "hasDeckLayout": True, "simulation": True, "controlPanelSupport": 0},
            {"deviceId": 2, "deviceName": "HHS", "deviceDisplayName": "Heater Shaker",
             "hasDeckLayout": False, "simulation": True, "controlPanelSupport": 0},
            {"deviceId": 3, "deviceName": "TCC", "deviceDisplayName": "Temperature Controller",
             "hasDeckLayout": False, "simulation": True, "controlPanelSupport": 0},
        ]

    def get_loaded_method(self) -> str:
        return self._loaded_file or ""

    def get_run_state(self) -> int:
        state_map = {"Undefined": 0, "Initialized": 1, "Running": 2, "Paused": 3, "Aborted": 4, "Terminated": 5}
        return state_map.get(self._status, 0)

    def get_deck_layout(self, device_id: int) -> Dict:
        return {
            "deviceId": device_id,
            "positions": [
                {"name": "Position1", "labwareType": "Plate_96", "x": 0, "y": 0},
                {"name": "Position2", "labwareType": "Trough_300mL", "x": 100, "y": 0},
                {"name": "Position3", "labwareType": "TipRack_300uL", "x": 200, "y": 0},
            ],
        }

    def get_current_run_data(self) -> Dict:
        return {
            "methodName": self._loaded_file or "(none)",
            "status": self._status,
            "startTime": "2025-01-01T00:00:00",
            "steps": [],
        }

    def get_runtime_data(self, start_date: Optional[str] = None, end_date: Optional[str] = None) -> List[Dict]:
        return [
            {
                "runGuid": "sim-run-001",
                "methodName": "SimulatedMethod.med",
                "startTime": "2025-01-01T10:00:00",
                "endTime": "2025-01-01T10:05:00",
                "status": "Completed",
            },
        ]

    def get_detailed_run_data(self, run_guid: str) -> Dict:
        return {
            "runGuid": run_guid,
            "methodName": "SimulatedMethod.med",
            "startTime": "2025-01-01T10:00:00",
            "endTime": "2025-01-01T10:05:00",
            "status": "Completed",
            "steps": [
                {"stepId": 1, "name": "Aspirate", "startTime": "2025-01-01T10:00:01", "status": "Completed"},
                {"stepId": 2, "name": "Dispense", "startTime": "2025-01-01T10:00:05", "status": "Completed"},
            ],
        }

    def get_system_version(self) -> Dict:
        return {"version": "4.8.0.0 (simulated)"}

    # ── Simulation helpers for observable commands ────────────────────

    def simulate_run(
        self,
        progress_callback: Optional[Callable[[float, str], None]] = None,
        trace_callback: Optional[Callable[[str], None]] = None,
        check_abort: Optional[Callable[[], bool]] = None,
        check_pause: Optional[Callable[[], bool]] = None,
        duration: float = 10.0,
    ) -> str:
        """Simulate a method run with progress updates.

        Args:
            progress_callback: Called with (progress_fraction, json_details)
            trace_callback: Called with trace message strings
            check_abort: Returns True if run should be aborted
            check_pause: Returns True if run is paused
            duration: Total simulated run time in seconds

        Returns:
            Final status string ("Terminated" or "Aborted")
        """
        steps = int(duration / 1.0)
        elapsed = 0.0

        for i in range(1, steps + 1):
            # Check abort
            if check_abort and check_abort():
                self._fire("NewRuntimeTrace", {"message": "Run aborted by user"})
                return "Aborted"

            # Handle pause
            while check_pause and check_pause():
                time.sleep(0.2)
                if check_abort and check_abort():
                    return "Aborted"

            time.sleep(1.0)
            elapsed += 1.0
            progress = i / steps
            remaining = duration - elapsed

            progress_json = json.dumps({
                "progress": round(progress * 100, 1),
                "elapsed": round(elapsed, 1),
                "remaining": round(remaining, 1),
            })

            if progress_callback:
                progress_callback(progress, progress_json)

            self._fire("OnProgressChanged", {
                "progress": round(progress * 100, 1),
                "elapsed": round(elapsed, 1),
                "remaining": round(remaining, 1),
            })

            trace_msg = f"Step {i}/{steps} completed ({progress * 100:.0f}%)"
            self._fire("NewRuntimeTrace", {"message": trace_msg})

            if trace_callback:
                trace_callback(trace_msg)

        with self._lock:
            self._is_running = False
            self._status = "Terminated"
            self._fire("NewRuntimeStatus", {"status": "Terminated"})
            self._fire("NewRuntimeTrace", {"message": "Method execution completed successfully"})

        return "Terminated"

    @property
    def status(self) -> str:
        return self._status

    @property
    def method_loaded(self) -> bool:
        return self._method_loaded

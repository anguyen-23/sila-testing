"""REST transport for the Micronic 2D tube-rack barcode scanner.

Communicates with the Micronic scanner software via its HTTP REST API
on port 2500. All endpoints use simple GET, POST, or PUT requests.

Endpoints:
  GET  /layoutlist     - list of supported layouts
  GET  /currentlayout  - current active layout
  PUT  /currentlayout  - change active layout
  POST /scanbox        - initiate rack scan
  POST /scantube       - initiate single tube scan
  GET  /scanresult     - scan results (JSON)
  GET  /scanresultcsv  - scan results (CSV)
  PUT  /retry          - retry decode with new params
  PUT  /rescan         - rescan tube with new params
  GET  /rackid         - rack ID
  GET  /state          - device state (idle/scanning/dataready)
"""
from __future__ import annotations

import logging
import time
from typing import Optional

import requests

logger = logging.getLogger(__name__)

POLL_INTERVAL_S = 0.5
SCAN_TIMEOUT_S = 120.0


class MicronicTransport:
    """Low-level HTTP transport for the Micronic tube scanner."""

    def __init__(self) -> None:
        self._base_url: Optional[str] = None
        self._session: Optional[requests.Session] = None

    @property
    def is_connected(self) -> bool:
        return self._base_url is not None

    def connect(self, base_url: str) -> None:
        """Connect to the Micronic scanner API.

        Verifies connectivity by querying the state endpoint.
        Raises ConnectionError on failure.
        """
        base_url = base_url.rstrip("/")
        session = requests.Session()
        try:
            resp = session.get(f"{base_url}/state", timeout=5)
            resp.raise_for_status()
        except Exception as e:
            raise ConnectionError(f"Failed to connect to Micronic at {base_url}: {e}") from e

        self._base_url = base_url
        self._session = session
        logger.info("Connected to Micronic at %s", base_url)

    def disconnect(self) -> None:
        """Disconnect from the Micronic scanner."""
        if self._session:
            self._session.close()
        self._base_url = None
        self._session = None
        logger.info("Disconnected from Micronic")

    def _require_connected(self) -> None:
        if not self.is_connected:
            raise ConnectionError("Not connected to Micronic scanner")

    def _get(self, endpoint: str) -> requests.Response:
        self._require_connected()
        resp = self._session.get(f"{self._base_url}/{endpoint}", timeout=10)
        resp.raise_for_status()
        return resp

    def _post(self, endpoint: str) -> requests.Response:
        self._require_connected()
        resp = self._session.post(f"{self._base_url}/{endpoint}", timeout=10)
        resp.raise_for_status()
        return resp

    def _put(self, endpoint: str, data: str = "") -> requests.Response:
        self._require_connected()
        headers = {"Content-Length": str(len(data))}
        resp = self._session.put(
            f"{self._base_url}/{endpoint}",
            data=data,
            headers=headers,
            timeout=10,
        )
        resp.raise_for_status()
        return resp

    def get_state(self) -> str:
        """Get device state: 'idle', 'scanning', or 'dataready'."""
        return self._get("state").text.strip()

    def get_layout_list(self) -> list[str]:
        """Get list of supported layout names."""
        resp = self._get("layoutlist")
        data = resp.json()
        if isinstance(data, list):
            return data
        return [str(data)]

    def get_current_layout(self) -> str:
        """Get the current active layout name."""
        return self._get("currentlayout").text.strip()

    def set_current_layout(self, layout_name: str) -> None:
        """Set the active layout."""
        self._put("currentlayout", layout_name)
        logger.info("Layout set to: %s", layout_name)

    def scan_box(self) -> None:
        """Initiate a rack scan. Returns immediately; poll state for completion."""
        self._post("scanbox")
        logger.info("Rack scan initiated")

    def scan_tube(self) -> None:
        """Initiate a single tube scan."""
        self._post("scantube")
        logger.info("Single tube scan initiated")

    def get_scan_result(self) -> str:
        """Get scan results as JSON string."""
        return self._get("scanresult").text

    def get_scan_result_csv(self) -> str:
        """Get scan results as CSV string."""
        return self._get("scanresultcsv").text

    def retry_decode(self, position: str, brightness: int, contrast: int, threshold: int) -> None:
        """Retry decoding a tube with new parameters."""
        data = f"{position},{brightness},{contrast},{threshold}"
        self._put("retry", data)
        logger.info("Retry decode: position=%s", position)

    def rescan_tube(self, position: str, brightness: int, contrast: int, threshold: int) -> None:
        """Rescan and decode a tube with new parameters."""
        data = f"{position},{brightness},{contrast},{threshold}"
        self._put("rescan", data)
        logger.info("Rescan tube: position=%s", position)

    def get_rack_id(self) -> str:
        """Get the rack ID."""
        return self._get("rackid").text.strip()

    def wait_for_scan_complete(self, timeout_s: float = SCAN_TIMEOUT_S) -> str:
        """Poll state until scan completes. Returns final state.

        Raises TimeoutError if scan doesn't complete within timeout.
        """
        start = time.monotonic()
        while True:
            state = self.get_state()
            if state == "dataready":
                return state
            if state != "scanning":
                return state
            elapsed = time.monotonic() - start
            if elapsed > timeout_s:
                raise TimeoutError(f"Scan did not complete within {timeout_s}s")
            time.sleep(POLL_INTERVAL_S)

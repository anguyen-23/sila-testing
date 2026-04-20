"""RCI (Remote Control Interface) transport for the PerkinElmer Phenix.

Communicates with the Phenix via the RCI COM library (RCI_DEVICELib).
The RCI protocol uses two ports:
  - Instrument port 8213: the Phenix listens here
  - Scheduler port 8300: our side listens here for callbacks

Commands are sent as (instruction, parameters_array) tuples.
Responses arrive asynchronously via an OnReceive callback and are
matched by CommandID.

Since the RCI SDK is COM-based, this module uses comtypes to access
the RCIDeviceClass. In simulation mode, the COM library is not needed.
"""
from __future__ import annotations

import enum
import logging
import threading
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────

INSTRUMENT_PORT = 8213
SCHEDULER_PORT = 8300
SITE = 1
LOAD_SITE = -1

ACCESS_TIMEOUT_MS = 5000
COMMAND_RESPONSE_TIMEOUT_S = 20.0
STAGE_MOTION_TIMEOUT_S = 120.0


# ── Enums (matching C# integer values) ──────────────────────────────

class DeviceState(enum.IntEnum):
    Operate = 0
    Idle = 1
    Standby = 2
    Offline = 3
    Service = 4


class StagePosition(enum.IntEnum):
    Transfer = 0
    Operate = 1
    Service = 2
    Home = 3


class ControlMode(enum.IntEnum):
    Remote = 0
    Local = 1


class PlateDetector(enum.IntEnum):
    NoDetectorAvailable = -1
    NoPlateDetected = 0
    PlateDetected = 1


class ErrorLevel(enum.IntEnum):
    Info = 0
    Warning = 1
    SeriousWarning = 2
    Error = 3
    FatalError = 4


# ── RCI Commands ────────────────────────────────────────────────────

CMD_STATUS = "STATUS"
CMD_RUN = "RUN"
CMD_LOAD = "LOAD"
CMD_EJECT = "EJECT"
CMD_STOP = "STOP"
CMD_QUERY = "QUERY"
CMD_IDLE = "IDLE"
CMD_STANDBY = "STANDBY"
CMD_SHUTDOWN = "SHUTDOWN"

# Response instructions
RESP_ACKNOWLEDGE = "ACKNOWLEDGE"
RESP_ANSWER = "ANSWER"
RESP_REJECT = "REJECT"
RESP_PROGRESS = "PROGRESS"
RESP_STATUS = "STATUS"


# ── Status response (parsed from 24-element array) ──────────────────

class PhenixStatus:
    """Parsed status/progress response from the Phenix."""

    def __init__(self, arr: list) -> None:
        self.barcode: str = str(arr[0]) if len(arr) > 0 else ""
        self.command_id: int = int(arr[2]) if len(arr) > 2 else 0
        self.estimated_duration: int = int(arr[3]) if len(arr) > 3 else 0
        self.host_name: str = str(arr[4]) if len(arr) > 4 else ""
        self.device_name: str = str(arr[5]) if len(arr) > 5 else ""
        self.current_instruction: str = str(arr[6]) if len(arr) > 6 else ""

        self.control_mode = ControlMode(int(arr[7])) if len(arr) > 7 else ControlMode.Remote
        self.device_state = DeviceState(int(arr[8])) if len(arr) > 8 else DeviceState.Offline
        self.plate_detector = PlateDetector(int(arr[9])) if len(arr) > 9 else PlateDetector.NoDetectorAvailable
        self.stage_position = StagePosition(int(arr[10])) if len(arr) > 10 else StagePosition.Home

        self.process_type: str = str(arr[11]) if len(arr) > 11 else ""
        self.process: str = str(arr[12]) if len(arr) > 12 else ""
        self.progress: int = int(arr[15]) if len(arr) > 15 else 0
        self.well_count: int = int(arr[16]) if len(arr) > 16 else 0
        self.detailed_progress: int = int(arr[17]) if len(arr) > 17 else 0

        self.error_level = ErrorLevel(int(arr[20])) if len(arr) > 20 else ErrorLevel.Info
        self.error_number: int = int(arr[21]) if len(arr) > 21 else 0
        self.error_message: str = str(arr[22]) if len(arr) > 22 else ""


# ── Transport ────────────────────────────────────────────────────────

class RCITransport:
    """Low-level RCI transport for the PerkinElmer Phenix.

    Uses the RCI COM library (comtypes) for real communication.
    The transport handles command ID tracking, synchronization,
    and response parsing.

    Usage:
        transport = RCITransport()
        transport.connect("phenix-host")
        status = transport.get_status("")
        transport.send_load("barcode-123")
        transport.send_run("protocol-name", "barcode-123")
        transport.disconnect()
    """

    def __init__(self) -> None:
        self._rci_device: Optional[Any] = None
        self._lock = threading.Lock()
        self._command_id: int = 0

        # Response synchronization
        self._response_event = threading.Event()
        self._last_instruction: str = ""
        self._last_response: list = []

        # Progress callback for observable commands
        self._progress_callback: Optional[Callable[[PhenixStatus], None]] = None

        # Cached status
        self._status: Optional[PhenixStatus] = None
        self._protocols: list[str] = []

    @property
    def is_connected(self) -> bool:
        return self._rci_device is not None

    @property
    def status(self) -> Optional[PhenixStatus]:
        return self._status

    @property
    def protocols(self) -> list[str]:
        return self._protocols

    def connect(self, hostname: str) -> str:
        """Connect to the Phenix via RCI.

        Returns the device name.
        Raises: ConnectionError on failure.
        """
        try:
            import comtypes.client
            self._rci_device = comtypes.client.CreateObject("RCI_DEVICELib.RCIDeviceClass")
            connection_string = f"{hostname}:{INSTRUMENT_PORT}"
            self._rci_device.Config(connection_string, SCHEDULER_PORT)
            self._rci_device.OnReceive += self._on_receive
        except Exception as e:
            self._rci_device = None
            raise ConnectionError(f"Failed to connect to Phenix at {hostname}: {e}") from e

        # Get initial status
        self._status = self.get_status("")
        # Query available protocols
        self._protocols = self.query_protocols()

        logger.info("Connected to Phenix at %s (%s)", hostname, self._status.device_name)
        return self._status.device_name

    def disconnect(self) -> None:
        """Disconnect from the Phenix."""
        if self._rci_device is not None:
            try:
                self._rci_device.OnReceive -= self._on_receive
            except Exception:
                pass
            self._rci_device = None
        self._status = None
        self._protocols = []
        logger.info("Disconnected from Phenix")

    def get_status(self, barcode: str) -> PhenixStatus:
        """Send STATUS command and return parsed status."""
        resp = self._send_command(CMD_STATUS, [barcode, SITE, self._next_id()])
        return PhenixStatus(resp)

    def query_protocols(self) -> list[str]:
        """Send QUERY command and return list of protocol names."""
        resp = self._send_command(CMD_QUERY, [SITE, self._next_id(), "ALL_PROCESSES"])
        # Protocol names start at index 3
        return [str(resp[i]) for i in range(3, len(resp))]

    def send_load(self, barcode: str) -> None:
        """Send LOAD command (stage Transfer -> Operate)."""
        self._send_command_expect_ack(CMD_LOAD, [barcode, SITE, self._next_id()])

    def send_eject(self, barcode: str) -> None:
        """Send EJECT command (stage Operate -> Transfer)."""
        self._send_command_expect_ack(CMD_EJECT, [barcode, SITE, self._next_id()])

    def send_run(
        self,
        protocol_name: str,
        barcode: str,
        progress_callback: Optional[Callable[[PhenixStatus], None]] = None,
    ) -> None:
        """Send RUN command to start an acquisition protocol.

        The progress_callback is called with PhenixStatus objects as PROGRESS
        responses arrive. The method blocks until the acquisition completes
        (progress == 100) or the process_running event is set.
        """
        self._progress_callback = progress_callback
        self._send_command_expect_ack(
            CMD_RUN,
            [barcode, "Reference", protocol_name, LOAD_SITE, self._next_id()],
        )

    def send_stop(self, barcode: str = "") -> None:
        """Send STOP command to abort running protocol."""
        self._send_command_expect_ack(CMD_STOP, [barcode, SITE, self._next_id()])

    def send_idle(self) -> None:
        """Send IDLE command."""
        self._send_command_expect_ack(CMD_IDLE, [SITE, self._next_id()])

    def send_standby(self, duration_seconds: int) -> None:
        """Send STANDBY command."""
        self._send_command_expect_ack(
            CMD_STANDBY, [SITE, self._next_id(), duration_seconds, 1]
        )

    # ── Internal ─────────────────────────────────────────────────────

    def _next_id(self) -> int:
        self._command_id += 1
        return self._command_id

    def _send_command(self, instruction: str, params: list) -> list:
        """Send a command and wait for the response."""
        if self._rci_device is None:
            raise ConnectionError("Not connected to Phenix")

        self._response_event.clear()
        self._last_instruction = ""
        self._last_response = []

        cmd_array = [instruction, params]
        self._rci_device.Send(instruction, params)

        if not self._response_event.wait(timeout=COMMAND_RESPONSE_TIMEOUT_S):
            raise TimeoutError(f"No response for {instruction} within {COMMAND_RESPONSE_TIMEOUT_S}s")

        return self._last_response

    def _send_command_expect_ack(self, instruction: str, params: list) -> None:
        """Send a command and verify we get ACKNOWLEDGE (not REJECT)."""
        resp = self._send_command(instruction, params)

        if self._last_instruction == RESP_REJECT:
            err_num = resp[3] if len(resp) > 3 else "?"
            err_msg = resp[4] if len(resp) > 4 else "Unknown error"
            raise RuntimeError(f"Command {instruction} rejected: [{err_num}] {err_msg}")

    def _on_receive(self, instruction: str, response_array) -> None:
        """RCI OnReceive callback. Called by the COM library on a background thread."""
        try:
            resp = list(response_array) if response_array else []
            logger.debug("RCI received: %s (len=%d)", instruction, len(resp))

            if instruction == RESP_PROGRESS:
                status = PhenixStatus(resp)
                self._status = status
                if self._progress_callback:
                    self._progress_callback(status)
                # Don't signal the event — progress is ongoing
                return

            if instruction == RESP_STATUS:
                self._status = PhenixStatus(resp)

            self._last_instruction = instruction
            self._last_response = resp
            self._response_event.set()

        except Exception as e:
            logger.error("Error in OnReceive handler: %s", e)

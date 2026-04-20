"""Serial communication layer for the Thermo Scientific Multidrop Combi.

Handles RS232/USB serial communication using the instrument's remote control
protocol. Each command is sent as a 3-letter code (optionally followed by
space-separated parameters), and the response follows this pattern:

    CMD           <- echo of the command sent
    <data lines>  <- zero or more data lines
    CMD END ss    <- terminator with status code (ss = 0 means success)

The VER command is special: it returns instrument info and enters remote mode.
The QIT command exits remote mode.
The ESC character (0x1B) aborts a running operation.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Iterator, Optional

logger = logging.getLogger(__name__)

# Status codes from the Multidrop Combi protocol
STATUS_OK = 0

# Error descriptions from manual Table 3-1 (EAK command section)
ERROR_DESCRIPTIONS = {
    1: "Internal firmware error",
    2: "Unrecognized command",
    3: "Invalid command arguments",
    4: "Pump position error",
    5: "Plate X position error",
    6: "Plate Y position error",
    7: "Z position error",
    9: "Attempt to reset serial number",
    10: "Nonvolatile parameters lost",
    11: "No more memory for user data",
    12: "Pump or X motor was running",
    13: "X and Z positions conflict",
    14: "Cannot dispense: pump not primed",
    15: "Missing prime vessel",
    16: "Rotor shield not in place",
    17: "Dispense volume for all columns is 0",
    18: "Invalid plate type (bad plate index)",
    19: "Plate has not been defined",
    20: "Invalid rows in plate definition",
    21: "Invalid columns in plate definition",
    22: "Plate height is invalid",
    23: "Plate well volume invalid (too small or too big)",
    24: "Invalid cassette type (bad cassette index)",
    25: "Cassette not defined",
    26: "Invalid volume increment for cassette",
    27: "Invalid maximum volume for cassette",
    28: "Invalid minimum volume for cassette",
    29: "Invalid min/max pump speed for cassette",
    30: "Invalid pump rotor offset in cassette definition",
    32: "Dispensing volume not within cassette limits",
    33: "Invalid selector channel",
    34: "Invalid dispensing speed",
    35: "Dispensing height too low for plate",
    36: "Predispense volume not within cassette limits",
    37: "Invalid dispensing order",
    38: "Invalid X or Y dispensing offset",
    39: "RFID option not present",
    40: "RFID tag not present",
    41: "RFID tag data checksum incorrect",
    43: "Wrong cassette type",
    44: "Protocol/plate in use, cannot modify or delete",
    45: "Protocol/plate/cassette is read-only",
}


class MultidropSerialTransport:
    """Low-level serial transport for the Multidrop Combi instrument.

    Usage:
        transport = MultidropSerialTransport()
        info = transport.connect("COM3")
        transport.send_command("SPL 1")  # Set plate type
        transport.send_command("DIS")     # Dispense
        transport.disconnect()
    """

    def __init__(self) -> None:
        self._serial: Optional[object] = None  # serial.Serial when connected
        self._lock = threading.Semaphore(1)
        self._instrument_name: str = ""
        self._firmware_version: str = ""
        self._serial_number: str = ""

    @property
    def is_connected(self) -> bool:
        return self._serial is not None and self._serial.is_open

    @property
    def instrument_name(self) -> str:
        return self._instrument_name

    @property
    def firmware_version(self) -> str:
        return self._firmware_version

    @property
    def serial_number(self) -> str:
        return self._serial_number

    def connect(self, port: str, baudrate: int = 9600, timeout: float = 5.0) -> dict:
        """Open serial port and send VER to enter remote control mode.

        Returns dict with keys: instrument_name, firmware_version, serial_number
        Raises: ConnectionError on failure
        """
        import serial

        with self._lock:
            if self.is_connected:
                self.disconnect()

            try:
                self._serial = serial.Serial(
                    port=port,
                    baudrate=baudrate,
                    bytesize=serial.EIGHTBITS,
                    parity=serial.PARITY_NONE,
                    stopbits=serial.STOPBITS_ONE,
                    timeout=timeout,
                )
            except serial.SerialException as e:
                raise ConnectionError(f"Failed to open serial port {port}: {e}") from e

            # Drain any stale data from previous sessions.
            # reset_input_buffer only clears host-side buffers; the instrument's
            # USB transmit buffer may still hold unread data from a prior session.
            self._serial.reset_input_buffer()
            self._serial.reset_output_buffer()
            old_timeout = self._serial.timeout
            self._serial.timeout = 0.3
            drained = 0
            while True:
                stale = self._serial.readline()
                if not stale:
                    break
                drained += 1
                logger.debug("Drained stale data: %r", stale)
            self._serial.timeout = old_timeout
            if drained:
                logger.info("Drained %d stale lines from serial buffer", drained)

            # Send VER to enter remote control and get instrument info.
            # If VER fails (e.g. instrument is in error state from a previous
            # session), try EAK to clear the error, then retry VER once.
            try:
                lines = self._send_and_receive("VER", timeout=timeout)
            except Exception as first_err:
                logger.warning("VER failed (%s), sending EAK and retrying...", first_err)
                try:
                    self._send_and_receive("EAK", timeout=timeout)
                except Exception:
                    pass  # EAK may itself return an error status; that's fine
                try:
                    lines = self._send_and_receive("VER", timeout=timeout)
                except Exception as e:
                    self._serial.close()
                    self._serial = None
                    raise ConnectionError(f"VER command failed: {e}") from e

            # Parse VER response: single data line "VER <name> <major.minor.build> [<serial>]"
            # The data line has the VER prefix stripped by _send_and_receive
            if lines:
                # Data line format: "<instrument_name> <version> [<serial_number>]"
                # e.g. "VER MultidropCombi 2.00.29 836-4191"
                # or after echo stripping: "MultidropCombi 2.00.29 836-4191"
                raw = lines[0]
                # Strip leading "VER " if present (in case echo stripping missed it)
                if raw.upper().startswith("VER "):
                    raw = raw[4:]
                parts = raw.split()
                self._instrument_name = parts[0] if len(parts) > 0 else "Unknown"
                self._firmware_version = parts[1] if len(parts) > 1 else "Unknown"
                self._serial_number = parts[2] if len(parts) > 2 else "Unknown"
            else:
                self._instrument_name = "Unknown"
                self._firmware_version = "Unknown"
                self._serial_number = "Unknown"

            # Clear any pending error from previous session
            try:
                self._send_and_receive("EAK")
            except RuntimeError:
                pass  # EAK itself may return status 0 or an error; either way, error is cleared

            logger.info(
                "Connected to %s (FW: %s, SN: %s)",
                self._instrument_name,
                self._firmware_version,
                self._serial_number,
            )

            return {
                "instrument_name": self._instrument_name,
                "firmware_version": self._firmware_version,
                "serial_number": self._serial_number,
            }

    def disconnect(self) -> None:
        """Send QIT to exit remote control and close serial port."""
        with self._lock:
            if self._serial is not None and self._serial.is_open:
                try:
                    self._send_and_receive("QIT", timeout=5.0)
                except Exception:
                    pass  # Best-effort on disconnect
                finally:
                    self._serial.close()
                    self._serial = None
            self._instrument_name = ""
            self._firmware_version = ""
            self._serial_number = ""

    def abort(self) -> None:
        """Send ESC character to abort current operation."""
        with self._lock:
            if self._serial is not None and self._serial.is_open:
                self._serial.write(b"\x1b")
                self._serial.flush()

    def send_command(self, cmd: str, timeout: float | None = None) -> list[str]:
        """Send a command and return the data lines from the response.

        Args:
            cmd: Command string (e.g. "DIS", "SPL 1", "SCV 0 500")
            timeout: Per-command serial read timeout in seconds. If None, uses
                     the port's default timeout.

        Returns:
            List of data lines (between the echo and the END terminator)

        Raises:
            ConnectionError: If not connected or communication fails
            RuntimeError: If instrument returns non-zero status code
        """
        with self._lock:
            if not self.is_connected:
                raise ConnectionError("Not connected to instrument")
            return self._send_and_receive(cmd, timeout=timeout)

    def send_command_streaming(self, cmd: str, timeout: float | None = None) -> Iterator[str]:
        """Send a command and yield each data line as it arrives.

        Holds the lock for the entire duration. Use this for observable commands
        like DIS where you need to stream progress lines.

        Args:
            cmd: Command string
            timeout: Per-command serial read timeout in seconds

        Yields:
            Each data line (excluding the echo and END terminator)

        Raises:
            ConnectionError: If not connected or communication fails
            RuntimeError: If instrument returns non-zero status code
        """
        with self._lock:
            if not self.is_connected:
                raise ConnectionError("Not connected to instrument")

            cmd_code = cmd.split()[0]

            original_timeout = self._serial.timeout
            if timeout is not None:
                self._serial.timeout = timeout
            try:
                self._serial.write(f"{cmd}\r".encode("ascii"))
                self._serial.flush()

                while True:
                    raw = self._serial.readline()
                    if not raw:
                        raise ConnectionError(f"Timeout reading response for {cmd_code}")
                    line = raw.decode("ascii", errors="replace").strip()
                    if not line:
                        continue

                    # Check for END terminator: "CMD END ss"
                    if line.startswith(cmd_code) and " END " in line:
                        parts = line.split()
                        status_code = int(parts[-1]) if parts[-1].isdigit() else -1
                        if status_code != STATUS_OK:
                            desc = ERROR_DESCRIPTIONS.get(status_code, "Unknown error")
                            raise RuntimeError(f"Instrument error (status {status_code}): {desc}")
                        return

                    # Skip echo of the command
                    if line.strip().upper() == cmd.strip().upper():
                        continue

                    yield line
            finally:
                if timeout is not None:
                    self._serial.timeout = original_timeout

    def ping(self) -> bool:
        """Check if the instrument is still responsive. Returns True if alive."""
        with self._lock:
            if not self.is_connected:
                return False
            try:
                self._serial.write(b"\r")
                self._serial.flush()
                old_timeout = self._serial.timeout
                self._serial.timeout = 1.0
                try:
                    self._serial.readline()
                finally:
                    self._serial.timeout = old_timeout
                return True
            except Exception:
                return False

    def _send_and_receive(self, cmd: str, timeout: float | None = None) -> list[str]:
        """Internal: send command and collect response. Must hold _lock."""
        cmd_code = cmd.split()[0]  # e.g. "SCV 0 500" -> "SCV"

        original_timeout = self._serial.timeout
        if timeout is not None:
            self._serial.timeout = timeout
        try:
            # Send the command with CR terminator
            self._serial.write(f"{cmd}\r".encode("ascii"))
            self._serial.flush()

            # Read response lines
            lines: list[str] = []
            while True:
                raw = self._serial.readline()
                if not raw:
                    raise ConnectionError(f"Timeout reading response for {cmd_code}")
                line = raw.decode("ascii", errors="replace").strip()
                if not line:
                    continue
                lines.append(line)

                # Check for END terminator: "CMD END ss"
                if line.startswith(cmd_code) and " END " in line:
                    break

            # Parse the terminator line for status
            end_line = lines[-1]
            # Format: "CMD END ss" where ss is the status code
            parts = end_line.split()
            status_code = int(parts[-1]) if parts[-1].isdigit() else -1

            if status_code != STATUS_OK:
                desc = ERROR_DESCRIPTIONS.get(status_code, "Unknown error")
                raise RuntimeError(f"Instrument error (status {status_code}): {desc}")

            # Return data lines: skip the echo (first line) and END line (last line)
            # Some commands echo back, some don't — be flexible
            data_lines = []
            for line in lines[:-1]:  # Exclude the END line
                # Skip the echo of the command itself
                if line.strip().upper() == cmd.strip().upper():
                    continue
                data_lines.append(line)

            return data_lines
        finally:
            if timeout is not None:
                self._serial.timeout = original_timeout

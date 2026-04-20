"""Serial communication layer for the Datalogic barcode scanner.

Handles RS-232 serial communication using ASCII control characters:
- STX (0x02): Start scanning / trigger
- ETX (0x03): Stop scanning

Barcode responses arrive asynchronously, terminated by CR (0x0D).
A background reader thread receives data and signals the main thread
via threading.Event, matching the C# ManualResetEvent pattern.

If the scanner returns "Invalid Cmd", a ValueError is raised.
"""
from __future__ import annotations

import logging
import threading
from typing import Optional

logger = logging.getLogger(__name__)

STX = b"\x02"
ETX = b"\x03"
SCAN_TIMEOUT = 2.0  # seconds, matching C# ManualResetEvent timeout


class DatalogicSerialTransport:
    """Low-level serial transport for a Datalogic barcode scanner.

    Usage:
        transport = DatalogicSerialTransport()
        transport.connect("COM3", 115200)
        barcode = transport.scan()
        transport.disconnect()
    """

    def __init__(self) -> None:
        self._serial: Optional[object] = None  # serial.Serial when connected
        self._lock = threading.Lock()
        self._reader_thread: Optional[threading.Thread] = None
        self._running = False

        # Scan result signaling (mirrors C# ManualResetEvent pattern)
        self._scan_event = threading.Event()
        self._scan_result: Optional[str] = None
        self._scan_error: Optional[str] = None

    @property
    def is_connected(self) -> bool:
        return self._serial is not None and self._serial.is_open

    def connect(self, port: str, baudrate: int = 115200) -> None:
        """Open serial port and start the background reader thread.

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
                    timeout=0.1,  # Short timeout for reader thread polling
                )
            except serial.SerialException as e:
                raise ConnectionError(f"Failed to open serial port {port}: {e}") from e

            self._running = True
            self._reader_thread = threading.Thread(
                target=self._reader_loop, daemon=True, name="barcode-reader"
            )
            self._reader_thread.start()
            logger.info("Connected to barcode scanner on %s @ %d", port, baudrate)

    def disconnect(self) -> None:
        """Stop the reader thread and close the serial port."""
        self._running = False
        if self._reader_thread is not None:
            self._reader_thread.join(timeout=2.0)
            self._reader_thread = None

        if self._serial is not None:
            try:
                self._serial.close()
            except Exception:
                pass
            self._serial = None
        logger.info("Disconnected from barcode scanner")

    def scan(self, timeout: float = SCAN_TIMEOUT) -> str:
        """Send STX to trigger scan and wait for barcode response.

        Returns: Barcode data string
        Raises:
            ConnectionError: If not connected or communication fails
            TimeoutError: If no barcode scanned within timeout
            ValueError: If scanner returns "Invalid Cmd"
        """
        if not self.is_connected:
            raise ConnectionError("Not connected to scanner")

        # Reset the event and result before triggering
        self._scan_event.clear()
        self._scan_result = None
        self._scan_error = None

        # Send STX to trigger scanning
        try:
            self._serial.write(STX)
            self._serial.flush()
        except Exception as e:
            self._auto_disconnect()
            raise ConnectionError(f"Failed to send scan trigger: {e}") from e

        # Wait for response from the reader thread
        if not self._scan_event.wait(timeout=timeout):
            raise TimeoutError("No barcode scanned within timeout period")

        if self._scan_error:
            raise ValueError(self._scan_error)

        return self._scan_result

    def stop_scanning(self) -> None:
        """Send ETX to cancel an active scan.

        Raises: ConnectionError if not connected
        """
        if not self.is_connected:
            raise ConnectionError("Not connected to scanner")

        try:
            self._serial.write(ETX)
            self._serial.flush()
        except Exception as e:
            self._auto_disconnect()
            raise ConnectionError(f"Failed to send stop command: {e}") from e

    def _reader_loop(self) -> None:
        """Background thread that reads incoming data from the scanner.

        Reads lines terminated by CR. Matches the C# DataReceived event
        handler pattern with async data reception.
        """
        buffer = b""
        while self._running:
            try:
                if self._serial is None or not self._serial.is_open:
                    break
                data = self._serial.read(256)
                if not data:
                    continue

                buffer += data
                # Process complete lines (CR-terminated)
                while b"\r" in buffer:
                    line, buffer = buffer.split(b"\r", 1)
                    decoded = line.decode("ascii", errors="replace").strip()
                    if not decoded:
                        continue

                    logger.debug("Scanner received: %r", decoded)

                    if "Invalid Cmd" in decoded:
                        self._scan_error = "Invalid Cmd"
                        self._scan_event.set()
                    else:
                        self._scan_result = decoded
                        self._scan_event.set()

            except Exception as e:
                if self._running:
                    logger.error("Reader thread error: %s", e)
                    self._scan_error = f"Communication error: {e}"
                    self._scan_event.set()
                    self._auto_disconnect()
                break

    def _auto_disconnect(self) -> None:
        """Auto-disconnect on error, matching C# error behavior."""
        self._running = False
        if self._serial is not None:
            try:
                self._serial.close()
            except Exception:
                pass
            self._serial = None
        logger.warning("Auto-disconnected due to error")

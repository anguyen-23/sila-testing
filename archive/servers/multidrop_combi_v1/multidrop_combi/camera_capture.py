"""Camera capture module for IP cameras (HTTP/RTSP) and USB webcams.

Uses OpenCV (cv2) to capture frames in a background thread.
Frames are JPEG-encoded and cached for retrieval via get_latest_frame().

This module is reusable across all servers -- do not diverge.
"""
from __future__ import annotations

import logging
import threading
import time

log = logging.getLogger(__name__)


class CameraCapture:
    """Background camera capture using OpenCV."""

    def __init__(self) -> None:
        self._cap = None  # cv2.VideoCapture instance
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._frame: bytes | None = None
        self._frame_lock = threading.Lock()
        self._source: str | None = None

    @property
    def is_streaming(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def latest_frame(self) -> bytes | None:
        with self._frame_lock:
            return self._frame

    def start(self, source: str) -> None:
        """Start capturing from the given source.

        Args:
            source: An HTTP/RTSP URL for IP cameras, or a device index
                    string (e.g. "0") for USB webcams.

        Raises:
            RuntimeError: If the camera cannot be opened.
        """
        import cv2

        if self.is_streaming:
            self.stop()

        # Parse source: numeric string -> int device index, else URL
        try:
            device_index = int(source)
            cap = cv2.VideoCapture(device_index)
        except ValueError:
            cap = cv2.VideoCapture(source)

        if not cap.isOpened():
            cap.release()
            raise RuntimeError(f"Cannot open camera source: {source}")

        self._cap = cap
        self._source = source
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._capture_loop, daemon=True, name="camera-capture"
        )
        self._thread.start()
        log.info("Camera capture started: %s", source)

    def stop(self) -> None:
        """Stop the capture thread and release the camera."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None
        if self._cap is not None:
            self._cap.release()
            self._cap = None
        with self._frame_lock:
            self._frame = None
        log.info("Camera capture stopped")

    def _capture_loop(self) -> None:
        """Background thread that continuously grabs and encodes frames."""
        import cv2

        while not self._stop_event.is_set():
            if self._cap is None or not self._cap.isOpened():
                log.warning("Camera disconnected, stopping capture")
                break

            ret, frame = self._cap.read()
            if not ret:
                # Brief retry before giving up
                time.sleep(0.1)
                continue

            # Encode as JPEG
            ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
            if ok:
                with self._frame_lock:
                    self._frame = buf.tobytes()

            # ~15 fps capture rate
            time.sleep(0.066)

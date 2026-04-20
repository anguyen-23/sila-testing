"""Camera capture module for IP cameras (HTTP/RTSP) and USB webcams.

Uses OpenCV (cv2) to capture frames in a background thread.
Frames are JPEG-encoded and cached for retrieval via get_latest_frame().

This module is reusable across all servers -- do not diverge.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path

log = logging.getLogger(__name__)


def _camera_config_path(server_package_or_dir: str | Path) -> Path | None:
    """Resolve the path to camera.json for a server."""
    if isinstance(server_package_or_dir, Path):
        return server_package_or_dir / "camera.json"
    import importlib
    try:
        pkg = importlib.import_module(server_package_or_dir)
        return Path(pkg.__file__).parent.parent / "camera.json"
    except (ImportError, AttributeError):
        return None


def load_camera_config(server_package_or_dir: str | Path) -> dict | None:
    """Load camera.json from a server's root directory.

    Args:
        server_package_or_dir: Either a Python package name (e.g. "multidrop_combi")
            or a Path to the server directory.

    Returns:
        Parsed config dict, or None if no config file exists.
    """
    config_path = _camera_config_path(server_package_or_dir)
    if config_path is None or not config_path.exists():
        return None
    try:
        return json.loads(config_path.read_text(encoding="utf-8"))
    except Exception as e:
        log.warning("Failed to load camera config from %s: %s", config_path, e)
        return None


def save_camera_config(server_package_or_dir: str | Path, config: dict) -> None:
    """Save camera.json to a server's root directory (merges with existing)."""
    config_path = _camera_config_path(server_package_or_dir)
    if config_path is None:
        log.warning("Cannot determine config path for camera")
        return
    try:
        existing = {}
        if config_path.exists():
            existing = json.loads(config_path.read_text(encoding="utf-8"))
        existing.update(config)
        config_path.write_text(json.dumps(existing, indent=4) + "\n", encoding="utf-8")
        log.info("Saved camera config to %s", config_path)
    except Exception as e:
        log.warning("Failed to save camera config to %s: %s", config_path, e)


class CameraCapture:
    """Background camera capture using OpenCV."""

    def __init__(self, jpeg_quality: int = 80, fps: int = 15) -> None:
        self._cap = None  # cv2.VideoCapture instance
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._frame: bytes | None = None
        self._frame_lock = threading.Lock()
        self._source: str | None = None
        self._jpeg_quality = jpeg_quality
        self._fps = fps

    @property
    def is_streaming(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def source(self) -> str | None:
        return self._source

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
        import os
        import cv2

        if self.is_streaming:
            self.stop()

        # Log FFMPEG availability from build info
        build_info = cv2.getBuildInformation()
        ffmpeg_lines = [l.strip() for l in build_info.split('\n') if 'FFMPEG' in l.upper()]
        log.info("OpenCV %s FFMPEG build info: %s", cv2.__version__, ffmpeg_lines)

        # Force RTSP over TCP — UDP requires dynamic ports that Windows
        # services (Session 0) often can't receive responses on.
        os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp"

        # Parse source: numeric string -> int device index, else URL
        try:
            device_index = int(source)
            cap = cv2.VideoCapture(device_index)
        except ValueError:
            log.info("Opening camera source: %s", source)

            # Method 1: FFMPEG with explicit timeout
            cap = cv2.VideoCapture()
            cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 10000)
            cap.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, 10000)
            opened = cap.open(source, cv2.CAP_FFMPEG)
            log.info("FFMPEG with timeout: opened=%s", opened)

            if not opened:
                cap.release()
                # Method 2: MSMF backend (Windows Media Foundation)
                log.info("Trying MSMF backend")
                cap = cv2.VideoCapture(source, cv2.CAP_MSMF)
                log.info("MSMF: opened=%s", cap.isOpened())

            if not cap.isOpened():
                cap.release()
                # Method 3: default backend
                log.info("Trying default backend")
                cap = cv2.VideoCapture(source)
                log.info("Default: opened=%s", cap.isOpened())

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
        self._source = None
        log.info("Camera capture stopped")

    def _capture_loop(self) -> None:
        """Background thread that continuously grabs and encodes frames."""
        import cv2

        interval = 1.0 / self._fps if self._fps > 0 else 0.066

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
            ok, buf = cv2.imencode(
                ".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, self._jpeg_quality]
            )
            if ok:
                with self._frame_lock:
                    self._frame = buf.tobytes()

            time.sleep(interval)

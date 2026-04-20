"""Win32 window capture for screen streaming.

Captures screenshots of a target application window using Win32 API.
When running as a Windows service (Session 0), delegates to the
screen_capture_helper running in the user's interactive session.

Requires: pywin32, Pillow, opencv-python, numpy
These are Windows-only dependencies (direct capture only).
"""
from __future__ import annotations

import json
import logging
import threading
import time
from typing import Optional
from urllib.request import urlopen, Request
from urllib.error import URLError

logger = logging.getLogger(__name__)

HELPER_URL = "http://127.0.0.1:8766"


def _helper_available() -> bool:
    """Check if the screen capture helper is running."""
    try:
        resp = urlopen(f"{HELPER_URL}/health", timeout=1)
        return resp.status == 200
    except Exception:
        return False


def _helper_list_windows() -> list[str]:
    """List windows via the screen capture helper."""
    resp = urlopen(f"{HELPER_URL}/windows", timeout=5)
    data = json.loads(resp.read())
    return data.get("windows", [])


def _helper_capture(title: str) -> Optional[bytes]:
    """Capture a window via the screen capture helper."""
    body = json.dumps({"title": title}).encode()
    req = Request(
        f"{HELPER_URL}/capture",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        resp = urlopen(req, timeout=10)
        if resp.status == 200:
            return resp.read()
    except Exception as e:
        logger.debug("Helper capture failed: %s", e)
    return None


def _init_dpi_awareness() -> None:
    """Set per-monitor DPI awareness for accurate pixel dimensions."""
    try:
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


def list_all_windows() -> list[str]:
    """List all visible window titles. Tries helper first, falls back to direct."""
    if _helper_available():
        logger.debug("Listing windows via helper")
        return _helper_list_windows()
    try:
        import win32gui
        titles = []
        def callback(hwnd, _):
            if win32gui.IsWindowVisible(hwnd) or win32gui.IsIconic(hwnd):
                title = win32gui.GetWindowText(hwnd)
                if title:
                    titles.append(title)
            return True
        win32gui.EnumWindows(callback, None)
        titles.sort()
        return titles
    except ImportError:
        return []


def find_window_by_substring(substring: str) -> Optional[int]:
    """Find a window whose title contains the given substring."""
    import win32gui

    result = []
    def callback(hwnd, _):
        if win32gui.IsWindowVisible(hwnd) or win32gui.IsIconic(hwnd):
            title = win32gui.GetWindowText(hwnd)
            if substring.lower() in title.lower():
                result.append(hwnd)
        return True
    win32gui.EnumWindows(callback, None)
    return result[0] if result else None


def _bitmap_to_jpeg(saveBitMap, width: int, height: int) -> Optional[bytes]:
    """Convert a win32ui bitmap to JPEG bytes."""
    import cv2
    import numpy as np
    from PIL import Image

    bmpinfo = saveBitMap.GetInfo()
    bmpstr = saveBitMap.GetBitmapBits(True)
    im = Image.frombuffer(
        'RGB',
        (bmpinfo['bmWidth'], bmpinfo['bmHeight']),
        bmpstr, 'raw', 'BGRX', 0, 1)
    frame = np.array(im)
    frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
    ret, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
    if ret:
        return buffer.tobytes()
    return None


def _has_content(saveBitMap) -> bool:
    """Check if the bitmap has any non-zero pixels."""
    bmpstr = saveBitMap.GetBitmapBits(True)
    return any(b != 0 for b in bmpstr[:1000])


def capture_window(hwnd: int) -> Optional[bytes]:
    """Capture the client area of a window. Returns JPEG bytes or None."""
    import ctypes
    import win32con
    import win32gui
    import win32ui

    is_minimized = win32gui.IsIconic(hwnd)
    rect = win32gui.GetClientRect(hwnd)
    width, height = max(rect[2], 1), max(rect[3], 1)

    if width <= 1 or height <= 1:
        placement = win32gui.GetWindowPlacement(hwnd)
        rc = placement[4]
        width = max(rc[2] - rc[0], 1)
        height = max(rc[3] - rc[1], 1)

    if width <= 1 or height <= 1:
        logger.warning("Window %s has no size (%dx%d)", hwnd, width, height)
        return None

    hwndDC = win32gui.GetWindowDC(hwnd)
    mfcDC = win32ui.CreateDCFromHandle(hwndDC)
    saveDC = mfcDC.CreateCompatibleDC()

    try:
        saveBitMap = win32ui.CreateBitmap()
        saveBitMap.CreateCompatibleBitmap(mfcDC, width, height)
        saveDC.SelectObject(saveBitMap)

        captured = False

        # Method 1: PrintWindow (works for most windows, but not elevated ones)
        if not is_minimized:
            result = ctypes.windll.user32.PrintWindow(hwnd, saveDC.GetSafeHdc(), 3)
            if result == 1 and _has_content(saveBitMap):
                captured = True
                logger.debug("Captured via PrintWindow")

        # Method 2: WM_PRINT message
        if not captured:
            PRF_CLIENT = 0x00000004
            PRF_CHILDREN = 0x00000010
            PRF_OWNED = 0x00000020
            win32gui.SendMessage(
                hwnd, win32con.WM_PRINT, saveDC.GetSafeHdc(),
                PRF_CLIENT | PRF_CHILDREN | PRF_OWNED
            )
            if _has_content(saveBitMap):
                captured = True
                logger.debug("Captured via WM_PRINT")

        # Method 3: BitBlt from window DC
        if not captured:
            saveDC.BitBlt((0, 0), (width, height), mfcDC, (0, 0), win32con.SRCCOPY)
            if _has_content(saveBitMap):
                captured = True
                logger.debug("Captured via BitBlt (window DC)")

        if captured:
            return _bitmap_to_jpeg(saveBitMap, width, height)

        return None
    finally:
        win32gui.DeleteObject(saveBitMap.GetHandle())
        saveDC.DeleteDC()
        mfcDC.DeleteDC()
        win32gui.ReleaseDC(hwnd, hwndDC)


def capture_window_from_screen(hwnd: int) -> Optional[bytes]:
    """Capture a window by copying its screen region from the desktop DC.

    This works for elevated/admin windows that block PrintWindow/WM_PRINT.
    The window must be visible (not occluded) on screen.
    """
    import win32con
    import win32gui
    import win32ui

    if win32gui.IsIconic(hwnd):
        logger.debug("Window is minimized, cannot capture from screen")
        return None

    rect = win32gui.GetWindowRect(hwnd)
    left, top, right, bottom = rect
    width = right - left
    height = bottom - top

    if width <= 1 or height <= 1:
        return None

    # Use desktop DC (screen) as source
    desktopDC = win32gui.GetDC(0)
    srcDC = win32ui.CreateDCFromHandle(desktopDC)
    saveDC = srcDC.CreateCompatibleDC()

    try:
        saveBitMap = win32ui.CreateBitmap()
        saveBitMap.CreateCompatibleBitmap(srcDC, width, height)
        saveDC.SelectObject(saveBitMap)

        saveDC.BitBlt((0, 0), (width, height), srcDC, (left, top), win32con.SRCCOPY)

        if _has_content(saveBitMap):
            logger.debug("Captured via desktop DC (screen region)")
            return _bitmap_to_jpeg(saveBitMap, width, height)

        return None
    finally:
        win32gui.DeleteObject(saveBitMap.GetHandle())
        saveDC.DeleteDC()
        srcDC.DeleteDC()
        win32gui.ReleaseDC(0, desktopDC)


class ScreenCapture:
    """Background screen capture thread for a target window."""

    def __init__(self) -> None:
        self._target_title: Optional[str] = None
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._last_jpeg: Optional[bytes] = None
        self._frame_lock = threading.Lock()

    @property
    def is_capturing(self) -> bool:
        return self._running and self._thread is not None and self._thread.is_alive()

    @property
    def latest_frame(self) -> Optional[bytes]:
        with self._frame_lock:
            return self._last_jpeg

    def start(self, window_title: str) -> None:
        """Start capturing a window matching the title substring.

        Raises RuntimeError if the window is not found.
        """
        _init_dpi_awareness()

        # Check if the helper can find the window, or try direct
        if _helper_available():
            windows = _helper_list_windows()
            found = any(window_title.lower() in w.lower() for w in windows)
            if not found:
                raise RuntimeError(f"No window found matching '{window_title}'")
        else:
            hwnd = find_window_by_substring(window_title)
            if hwnd is None:
                raise RuntimeError(f"No window found matching '{window_title}'")

        self.stop()
        self._target_title = window_title
        self._running = True
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()
        logger.info("Screen capture started for window: %s", window_title)

    def stop(self) -> None:
        """Stop the capture thread."""
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        self._last_jpeg = None
        logger.info("Screen capture stopped")

    def _capture_loop(self) -> None:
        """Background loop that continuously captures the target window.

        Tries the screen capture helper first (for service/Session 0 usage),
        then falls back to direct Win32 capture (for local dev).
        """
        fail_count = 0
        use_helper = _helper_available()
        if use_helper:
            logger.info("Using screen capture helper at %s", HELPER_URL)
        else:
            logger.info("Screen capture helper not available, using direct Win32 capture")

        while self._running:
            try:
                jpeg = None

                if use_helper:
                    jpeg = _helper_capture(self._target_title)
                else:
                    hwnd = find_window_by_substring(self._target_title)
                    if hwnd:
                        jpeg = capture_window(hwnd)
                        if jpeg is None:
                            jpeg = capture_window_from_screen(hwnd)

                if jpeg is not None:
                    with self._frame_lock:
                        self._last_jpeg = jpeg
                    fail_count = 0
                else:
                    fail_count += 1
                    if fail_count <= 3:
                        logger.warning("Capture failed for '%s'", self._target_title)
                    # Re-check helper availability periodically
                    if fail_count % 50 == 0:
                        use_helper = _helper_available()
            except Exception as e:
                fail_count += 1
                if fail_count <= 3:
                    logger.warning("Capture error: %s", e)
            time.sleep(0.1)

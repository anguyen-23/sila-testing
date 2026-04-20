"""Screen Capture Helper — runs in the user's interactive session.

This lightweight HTTP server exposes window enumeration and screen capture
to SiLA servers running as Windows services (Session 0), which cannot
access the interactive desktop directly.

Listens on 127.0.0.1:8766 (localhost only).

Endpoints:
    GET  /health              → {"status": "ok"}
    GET  /windows             → {"windows": ["Title 1", "Title 2", ...]}
    POST /capture             → JPEG bytes (body: {"title": "window title"})

Deployed as a scheduled task at logon via Ansible.
"""
from __future__ import annotations

import ctypes
import io
import json
import logging
import sys
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Optional

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

PORT = 8766


def _init_dpi_awareness() -> None:
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def list_windows() -> list[str]:
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


def find_window_by_substring(substring: str) -> Optional[int]:
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
    import cv2
    import numpy as np
    from PIL import Image

    bmpinfo = saveBitMap.GetInfo()
    bmpstr = saveBitMap.GetBitmapBits(True)
    im = Image.frombuffer(
        "RGB",
        (bmpinfo["bmWidth"], bmpinfo["bmHeight"]),
        bmpstr, "raw", "BGRX", 0, 1,
    )
    frame = np.array(im)
    frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
    ret, buffer = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
    if ret:
        return buffer.tobytes()
    return None


def _has_content(saveBitMap) -> bool:
    bmpstr = saveBitMap.GetBitmapBits(True)
    return any(b != 0 for b in bmpstr[:1000])


def capture_window(hwnd: int) -> Optional[bytes]:
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
        return None

    hwndDC = win32gui.GetWindowDC(hwnd)
    mfcDC = win32ui.CreateDCFromHandle(hwndDC)
    saveDC = mfcDC.CreateCompatibleDC()

    try:
        saveBitMap = win32ui.CreateBitmap()
        saveBitMap.CreateCompatibleBitmap(mfcDC, width, height)
        saveDC.SelectObject(saveBitMap)

        captured = False

        if not is_minimized:
            result = ctypes.windll.user32.PrintWindow(hwnd, saveDC.GetSafeHdc(), 3)
            if result == 1 and _has_content(saveBitMap):
                captured = True

        if not captured:
            PRF_CLIENT = 0x00000004
            PRF_CHILDREN = 0x00000010
            PRF_OWNED = 0x00000020
            win32gui.SendMessage(
                hwnd, win32con.WM_PRINT, saveDC.GetSafeHdc(),
                PRF_CLIENT | PRF_CHILDREN | PRF_OWNED,
            )
            if _has_content(saveBitMap):
                captured = True

        if not captured:
            saveDC.BitBlt((0, 0), (width, height), mfcDC, (0, 0), win32con.SRCCOPY)
            if _has_content(saveBitMap):
                captured = True

        if captured:
            return _bitmap_to_jpeg(saveBitMap, width, height)
        return None
    finally:
        win32gui.DeleteObject(saveBitMap.GetHandle())
        saveDC.DeleteDC()
        mfcDC.DeleteDC()
        win32gui.ReleaseDC(hwnd, hwndDC)


def capture_window_from_screen(hwnd: int) -> Optional[bytes]:
    import win32con
    import win32gui
    import win32ui

    if win32gui.IsIconic(hwnd):
        return None

    rect = win32gui.GetWindowRect(hwnd)
    left, top, right, bottom = rect
    width = right - left
    height = bottom - top

    if width <= 1 or height <= 1:
        return None

    desktopDC = win32gui.GetDC(0)
    srcDC = win32ui.CreateDCFromHandle(desktopDC)
    saveDC = srcDC.CreateCompatibleDC()

    try:
        saveBitMap = win32ui.CreateBitmap()
        saveBitMap.CreateCompatibleBitmap(srcDC, width, height)
        saveDC.SelectObject(saveBitMap)
        saveDC.BitBlt((0, 0), (width, height), srcDC, (left, top), win32con.SRCCOPY)

        if _has_content(saveBitMap):
            return _bitmap_to_jpeg(saveBitMap, width, height)
        return None
    finally:
        win32gui.DeleteObject(saveBitMap.GetHandle())
        saveDC.DeleteDC()
        srcDC.DeleteDC()
        win32gui.ReleaseDC(0, desktopDC)


def capture(title: str) -> Optional[bytes]:
    hwnd = find_window_by_substring(title)
    if hwnd is None:
        return None
    jpeg = capture_window(hwnd)
    if jpeg is None:
        jpeg = capture_window_from_screen(hwnd)
    return jpeg


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/health":
            self._json_response({"status": "ok"})
        elif self.path == "/windows":
            self._json_response({"windows": list_windows()})
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path == "/capture":
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length)) if length else {}
            title = body.get("title", "")
            if not title:
                self._json_response({"error": "missing 'title'"}, status=400)
                return
            jpeg = capture(title)
            if jpeg is None:
                self._json_response(
                    {"error": f"Could not capture window matching '{title}'"},
                    status=404,
                )
                return
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", str(len(jpeg)))
            self.end_headers()
            self.wfile.write(jpeg)
        else:
            self.send_error(404)

    def _json_response(self, data: dict, status: int = 200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        log.info(format, *args)


def main():
    _init_dpi_awareness()
    server = HTTPServer(("127.0.0.1", PORT), Handler)
    log.info("Screen capture helper listening on 127.0.0.1:%d", PORT)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("Shutting down")
        server.shutdown()


if __name__ == "__main__":
    main()

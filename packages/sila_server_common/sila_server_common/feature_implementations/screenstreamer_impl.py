"""ScreenStreamer implementation factory — canonical, shared across all servers.

Usage in server.py:
    from sila_server_common.feature_implementations.screenstreamer_impl import create_screenstreamer_impl
    from .generated import screenstreamer as ss_gen

    ScreenStreamerImpl = create_screenstreamer_impl(ss_gen)
    self.screenstreamer = ScreenStreamerImpl(self)
    self.set_feature_implementation(ss_gen.ScreenStreamerFeature, self.screenstreamer)
"""
from __future__ import annotations

import io
import logging
from types import ModuleType

logger = logging.getLogger(__name__)


def _make_placeholder_jpeg() -> bytes:
    """Generate a 320x240 placeholder JPEG with text for simulation mode."""
    from PIL import Image, ImageDraw

    img = Image.new('RGB', (320, 240), color=(40, 40, 40))
    draw = ImageDraw.Draw(img)
    draw.text((60, 100), "SIMULATION MODE", fill=(200, 200, 200))
    draw.text((80, 130), "Screen Streamer", fill=(140, 140, 140))
    buf = io.BytesIO()
    img.save(buf, format='JPEG', quality=70)
    return buf.getvalue()


def create_screenstreamer_impl(generated_module: ModuleType) -> type:
    """Create a ScreenStreamerImpl class bound to the server's generated module."""

    Base = generated_module.ScreenStreamerBase
    CaptureError = generated_module.CaptureError
    WindowNotFound = generated_module.WindowNotFound
    GetLatestFrame_Responses = generated_module.GetLatestFrame_Responses
    ListWindows_Responses = generated_module.ListWindows_Responses
    StartCapture_Responses = generated_module.StartCapture_Responses
    StopCapture_Responses = generated_module.StopCapture_Responses

    class ScreenStreamerImpl(Base):
        """Screen streaming feature using Win32 window capture.

        In simulation mode, returns a placeholder JPEG.
        In real mode, captures windows using PrintWindow/BitBlt.
        """

        def __init__(self, parent_server) -> None:
            super().__init__(parent_server=parent_server)
            self._simulation_mode: bool = True
            self._sim_capturing: bool = False
            self._capture = None
            self._server_package: str = getattr(parent_server, '_server_package', '')

        def _get_capture(self):
            if self._capture is None:
                from sila_server_common.transports.win32_capture import ScreenCapture
                self._capture = ScreenCapture()
            return self._capture

        def _save_window_title(self, window_title: str) -> None:
            """Persist the window title to screen_capture.json."""
            if not self._server_package:
                return
            from sila_server_common.transports.win32_capture import save_screen_config
            save_screen_config(self._server_package, {"window_title": window_title})

        def _clear_window_title(self) -> None:
            """Remove persisted window title."""
            if not self._server_package:
                return
            from sila_server_common.transports.win32_capture import save_screen_config
            save_screen_config(self._server_package, {})

        def auto_start(self, config: dict) -> None:
            """Auto-start screen capture from a config dict (from screen_capture.json).

            Called by BaseInstrumentServer after start() when window_title is set.
            """
            window_title = config.get("window_title", "")
            if not window_title:
                return

            if self._simulation_mode:
                logger.info("Screen capture auto_start in simulation mode (window='%s')", window_title)
                self._sim_capturing = True
                return

            try:
                self._get_capture().start(window_title)
                logger.info("Screen capture auto-started: %s", window_title)
            except Exception as e:
                logger.warning("Screen capture auto_start failed: %s", e)

        def get_IsCapturing(self, *, metadata) -> bool:
            if self._simulation_mode:
                return self._sim_capturing
            return self._get_capture().is_capturing

        def ListWindows(self, *, metadata) -> ListWindows_Responses:
            logger.info("ListWindows: simulation=%s", self._simulation_mode,
                        extra={"category": "command", "command_name": "ListWindows"})

            if self._simulation_mode:
                return ListWindows_Responses(WindowTitles=[
                    "Simulated Window 1",
                    "Simulated Window 2",
                    "Device Application (simulated)",
                ])

            try:
                from sila_server_common.transports.win32_capture import list_all_windows
                titles = list_all_windows()
                return ListWindows_Responses(WindowTitles=titles)
            except ImportError:
                raise CaptureError("pywin32 not installed on server")
            except Exception as e:
                raise CaptureError(str(e))

        def StartCapture(self, WindowTitle: str, *, metadata) -> StartCapture_Responses:
            logger.info("StartCapture: window='%s', simulation=%s", WindowTitle, self._simulation_mode,
                        extra={"category": "command", "command_name": "StartCapture"})

            if self._simulation_mode:
                self._sim_capturing = True
                self._save_window_title(WindowTitle)
                return StartCapture_Responses()

            try:
                self._get_capture().start(WindowTitle)
                self._save_window_title(WindowTitle)
            except RuntimeError as e:
                if "No window found" in str(e):
                    raise WindowNotFound(str(e))
                raise CaptureError(str(e))
            except Exception as e:
                raise CaptureError(str(e))
            return StartCapture_Responses()

        def StopCapture(self, *, metadata) -> StopCapture_Responses:
            logger.info("StopCapture")

            if self._simulation_mode:
                self._sim_capturing = False
                return StopCapture_Responses()

            self._get_capture().stop()
            return StopCapture_Responses()

        def GetLatestFrame(self, *, metadata) -> GetLatestFrame_Responses:
            if self._simulation_mode:
                if not self._sim_capturing:
                    raise CaptureError("Not capturing. Call StartCapture first.")
                return GetLatestFrame_Responses(Frame=_make_placeholder_jpeg())

            capture = self._get_capture()
            frame = capture.latest_frame
            if frame is None:
                raise CaptureError("No frame available. Ensure capture is running and the window is visible.")
            return GetLatestFrame_Responses(Frame=frame)

    return ScreenStreamerImpl

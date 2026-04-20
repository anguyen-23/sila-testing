"""CameraStreamProvider implementation factory — optional, per-server feature.

Unlike ScreenStreamer (registered on all servers via BaseInstrumentServer),
CameraStreamProvider is opt-in. Servers register it manually in server.py.

Usage in server.py:
    import importlib
    from sila_server_common.feature_implementations.camerastreamprovider_impl import create_camerastreamprovider_impl

    csp_gen = importlib.import_module(f"{server_package}.generated.camerastreamprovider")
    CameraStreamProviderImpl = create_camerastreamprovider_impl(csp_gen)
    self.camerastreamprovider = CameraStreamProviderImpl(self)
    self.set_feature_implementation(csp_gen.CameraStreamProviderFeature, self.camerastreamprovider)
"""
from __future__ import annotations

import io
import logging
from types import ModuleType

logger = logging.getLogger(__name__)


def _make_placeholder_jpeg() -> bytes:
    """Generate a 320x240 placeholder JPEG with text for simulation mode."""
    try:
        from PIL import Image, ImageDraw

        img = Image.new('RGB', (320, 240), color=(40, 40, 40))
        draw = ImageDraw.Draw(img)
        draw.text((60, 100), "SIMULATION MODE", fill=(200, 200, 200))
        draw.text((70, 130), "Camera Stream", fill=(140, 140, 140))
        buf = io.BytesIO()
        img.save(buf, format='JPEG', quality=70)
        return buf.getvalue()
    except ImportError:
        # Minimal valid 1x1 gray JPEG fallback
        return bytes([
            0xFF, 0xD8, 0xFF, 0xE0, 0x00, 0x10, 0x4A, 0x46,
            0x49, 0x46, 0x00, 0x01, 0x01, 0x00, 0x00, 0x01,
            0x00, 0x01, 0x00, 0x00, 0xFF, 0xDB, 0x00, 0x43,
            0x00, 0x08, 0x06, 0x06, 0x07, 0x06, 0x05, 0x08,
            0x07, 0x07, 0x07, 0x09, 0x09, 0x08, 0x0A, 0x0C,
            0x14, 0x0D, 0x0C, 0x0B, 0x0B, 0x0C, 0x19, 0x12,
            0x13, 0x0F, 0x14, 0x1D, 0x1A, 0x1F, 0x1E, 0x1D,
            0x1A, 0x1C, 0x1C, 0x20, 0x24, 0x2E, 0x27, 0x20,
            0x22, 0x2C, 0x23, 0x1C, 0x1C, 0x28, 0x37, 0x29,
            0x2C, 0x30, 0x31, 0x34, 0x34, 0x34, 0x1F, 0x27,
            0x39, 0x3D, 0x38, 0x32, 0x3C, 0x2E, 0x33, 0x34,
            0x32, 0xFF, 0xC0, 0x00, 0x0B, 0x08, 0x00, 0x01,
            0x00, 0x01, 0x01, 0x01, 0x11, 0x00, 0xFF, 0xC4,
            0x00, 0x1F, 0x00, 0x00, 0x01, 0x05, 0x01, 0x01,
            0x01, 0x01, 0x01, 0x01, 0x00, 0x00, 0x00, 0x00,
            0x00, 0x00, 0x00, 0x00, 0x01, 0x02, 0x03, 0x04,
            0x05, 0x06, 0x07, 0x08, 0x09, 0x0A, 0x0B, 0xFF,
            0xC4, 0x00, 0xB5, 0x10, 0x00, 0x02, 0x01, 0x03,
            0x03, 0x02, 0x04, 0x03, 0x05, 0x05, 0x04, 0x04,
            0x00, 0x00, 0x01, 0x7D, 0x01, 0x02, 0x03, 0x00,
            0x04, 0x11, 0x05, 0x12, 0x21, 0x31, 0x41, 0x06,
            0x13, 0x51, 0x61, 0x07, 0x22, 0x71, 0x14, 0x32,
            0x81, 0x91, 0xA1, 0x08, 0x23, 0x42, 0xB1, 0xC1,
            0x15, 0x52, 0xD1, 0xF0, 0x24, 0x33, 0x62, 0x72,
            0x82, 0x09, 0x0A, 0x16, 0x17, 0x18, 0x19, 0x1A,
            0x25, 0x26, 0x27, 0x28, 0x29, 0x2A, 0x34, 0x35,
            0x36, 0x37, 0x38, 0x39, 0x3A, 0x43, 0x44, 0x45,
            0x46, 0x47, 0x48, 0x49, 0x4A, 0x53, 0x54, 0x55,
            0x56, 0x57, 0x58, 0x59, 0x5A, 0x63, 0x64, 0x65,
            0x66, 0x67, 0x68, 0x69, 0x6A, 0x73, 0x74, 0x75,
            0x76, 0x77, 0x78, 0x79, 0x7A, 0x83, 0x84, 0x85,
            0x86, 0x87, 0x88, 0x89, 0x8A, 0x92, 0x93, 0x94,
            0x95, 0x96, 0x97, 0x98, 0x99, 0x9A, 0xA2, 0xA3,
            0xA4, 0xA5, 0xA6, 0xA7, 0xA8, 0xA9, 0xAA, 0xB2,
            0xB3, 0xB4, 0xB5, 0xB6, 0xB7, 0xB8, 0xB9, 0xBA,
            0xC2, 0xC3, 0xC4, 0xC5, 0xC6, 0xC7, 0xC8, 0xC9,
            0xCA, 0xD2, 0xD3, 0xD4, 0xD5, 0xD6, 0xD7, 0xD8,
            0xD9, 0xDA, 0xE1, 0xE2, 0xE3, 0xE4, 0xE5, 0xE6,
            0xE7, 0xE8, 0xE9, 0xEA, 0xF1, 0xF2, 0xF3, 0xF4,
            0xF5, 0xF6, 0xF7, 0xF8, 0xF9, 0xFA, 0xFF, 0xDA,
            0x00, 0x08, 0x01, 0x01, 0x00, 0x00, 0x3F, 0x00,
            0x7B, 0x94, 0x11, 0x00, 0x00, 0x00, 0x00, 0x00,
            0xFF, 0xD9,
        ])


def create_camerastreamprovider_impl(generated_module: ModuleType) -> type:
    """Create a CameraStreamProviderImpl class bound to the server's generated module."""

    Base = generated_module.CameraStreamProviderBase
    CameraNotFound = generated_module.CameraNotFound
    StreamError = generated_module.StreamError
    GetLatestFrame_Responses = generated_module.GetLatestFrame_Responses
    StartStream_Responses = generated_module.StartStream_Responses
    StopStream_Responses = generated_module.StopStream_Responses

    class CameraStreamProviderImpl(Base):
        """Camera streaming feature using OpenCV.

        In simulation mode, returns a placeholder JPEG.
        In real mode, captures from IP cameras (HTTP/RTSP) or USB webcams.
        """

        def __init__(self, parent_server) -> None:
            super().__init__(parent_server=parent_server)
            self._simulation_mode: bool = True
            self._sim_streaming: bool = False
            self._capture = None
            self._server_package: str = getattr(parent_server, '_server_package', '')

        def _get_capture(self, jpeg_quality: int = 80, fps: int = 15):
            """Lazy-load CameraCapture to avoid OpenCV import errors when not installed."""
            if self._capture is None:
                from sila_server_common.transports.camera_capture import CameraCapture
                self._capture = CameraCapture(jpeg_quality=jpeg_quality, fps=fps)
            return self._capture

        def _save_source(self, source: str) -> None:
            """Persist the camera source to camera.json (merges with existing config)."""
            if not self._server_package:
                return
            from sila_server_common.transports.camera_capture import save_camera_config
            save_camera_config(self._server_package, {"source": source})

        def auto_start(self, config: dict) -> None:
            """Auto-start camera streaming from a config dict (from camera.json).

            Called by the server after start() when auto_start is true in config.
            """
            source = config.get("source", "")
            if not source:
                logger.warning("Camera auto_start: no source configured")
                return

            jpeg_quality = config.get("jpeg_quality", 80)
            fps = config.get("fps", 15)

            if self._simulation_mode:
                logger.info("Camera auto_start in simulation mode (source=%s)", source)
                self._sim_streaming = True
                return

            try:
                self._get_capture(jpeg_quality=jpeg_quality, fps=fps).start(source)
                logger.info("Camera auto-started: %s", source)
            except Exception as e:
                logger.error("Camera auto_start failed: %s", e)

        def get_IsStreaming(self, *, metadata) -> bool:
            if self._simulation_mode:
                return self._sim_streaming
            return self._get_capture().is_streaming

        def StartStream(self, Source: str, *, metadata) -> StartStream_Responses:
            logger.info("StartStream: source='%s', simulation=%s", Source, self._simulation_mode)

            if self._simulation_mode:
                self._sim_streaming = True
                self._save_source(Source)
                return StartStream_Responses()

            try:
                self._get_capture().start(Source)
                self._save_source(Source)
            except RuntimeError as e:
                if "Cannot open" in str(e):
                    raise CameraNotFound(str(e))
                raise StreamError(str(e))
            except Exception as e:
                raise StreamError(str(e))
            return StartStream_Responses()

        def StopStream(self, *, metadata) -> StopStream_Responses:
            logger.info("StopStream")

            if self._simulation_mode:
                self._sim_streaming = False
                return StopStream_Responses()

            self._get_capture().stop()
            return StopStream_Responses()

        def GetLatestFrame(self, *, metadata) -> GetLatestFrame_Responses:
            if self._simulation_mode:
                if not self._sim_streaming:
                    raise StreamError("Not streaming. Call StartStream first.")
                return GetLatestFrame_Responses(Frame=_make_placeholder_jpeg())

            capture = self._get_capture()
            frame = capture.latest_frame
            if frame is None:
                raise StreamError("No frame available. Ensure stream is running and camera is accessible.")
            return GetLatestFrame_Responses(Frame=frame)

    return CameraStreamProviderImpl

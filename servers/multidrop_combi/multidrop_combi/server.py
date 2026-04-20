import importlib
import logging
from typing import Optional
from uuid import UUID

from sila_server_common.base_server import BaseInstrumentServer
from sila_server_common.feature_implementations.camerastreamprovider_impl import create_camerastreamprovider_impl
from sila_server_common.transports.camera_capture import load_camera_config

from .feature_implementations.multidropcombi_impl import MultidropCombiImpl
from .generated.multidropcombi import MultidropCombiFeature

logger = logging.getLogger(__name__)


class Server(BaseInstrumentServer):
    def __init__(
        self,
        server_uuid: Optional[UUID] = None,
        name: Optional[str] = None,
        description: Optional[str] = None,
    ):
        if name is None:
            name = "Multidrop Combi"
        if description is None:
            description = "Thermo Scientific Multidrop Combi reagent dispenser (SiLA 2)"
        super().__init__(
            server_name=name,
            server_description=description,
            server_type="MultidropCombi",
            server_version="1.0.0",
            server_vendor_url="https://github.com/keyser",
            server_package="multidrop_combi",
            server_uuid=server_uuid,
        )

        # Device-specific feature
        self.multidropcombi = MultidropCombiImpl(self)
        self.set_feature_implementation(MultidropCombiFeature, self.multidropcombi)

        # CameraStreamProvider (optional)
        csp_gen = importlib.import_module(f"{self._server_package}.generated.camerastreamprovider")
        CameraStreamProviderImpl = create_camerastreamprovider_impl(csp_gen)
        self.camerastreamprovider = CameraStreamProviderImpl(self)
        self.set_feature_implementation(csp_gen.CameraStreamProviderFeature, self.camerastreamprovider)

    def on_simulation_mode_changed(self, simulation_mode: bool) -> None:
        super().on_simulation_mode_changed(simulation_mode)

        self.camerastreamprovider._simulation_mode = simulation_mode

        combi = self.multidropcombi

        # Disconnect real transport if connected
        if combi._transport.is_connected:
            try:
                combi._transport.disconnect()
            except Exception:
                pass

        # Reset simulation connection state
        combi._sim_connected = False
        combi._sim_primed = False
        combi._simulation_mode = simulation_mode

        # Push observable updates
        combi.update_IsConnected(False)
        combi.update_IsPrimed(False)
        combi.update_InstrumentName("")
        combi.update_FirmwareVersion("")

        mode_str = "simulation" if simulation_mode else "real"
        combi._push_device_status(f"Entered {mode_str} mode")
        logger.info("Disconnected Multidrop Combi due to simulation mode change")

    def start_insecure(self, *args, **kwargs):
        super().start_insecure(*args, **kwargs)
        self._auto_start_camera()

    def start(self, *args, **kwargs):
        super().start(*args, **kwargs)
        self._auto_start_camera()

    def _auto_start_camera(self) -> None:
        """Auto-start camera if configured in camera.json."""
        config = load_camera_config(self._server_package)
        if config and config.get("auto_start"):
            self.camerastreamprovider.auto_start(config)

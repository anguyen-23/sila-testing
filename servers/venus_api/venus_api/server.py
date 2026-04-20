import logging
from typing import Optional
from uuid import UUID

from sila_server_common.base_server import BaseInstrumentServer

from .feature_implementations.venusmethodexecutor_impl import VenusMethodExecutorImpl
from .generated.venusmethodexecutor import VenusMethodExecutorFeature

logger = logging.getLogger(__name__)


class Server(BaseInstrumentServer):
    def __init__(
        self,
        server_uuid: Optional[UUID] = None,
        name: Optional[str] = None,
        description: Optional[str] = None,
        venus_url: str = "http://localhost:51745",
    ):
        if name is None:
            name = "Venus API"
        if description is None:
            description = "Hamilton VENUS Web API wrapper (SiLA 2)"
        super().__init__(
            server_name=name,
            server_description=description,
            server_type="VenusAPI",
            server_version="1.0.0",
            server_vendor_url="https://github.com/keyser",
            server_package="venus_api",
            server_uuid=server_uuid,
        )

        # Device-specific feature
        self.venusmethodexecutor = VenusMethodExecutorImpl(self, venus_url=venus_url)
        self.set_feature_implementation(VenusMethodExecutorFeature, self.venusmethodexecutor)

    def on_simulation_mode_changed(self, simulation_mode: bool) -> None:
        super().on_simulation_mode_changed(simulation_mode)

        executor = self.venusmethodexecutor

        # Reset executor state
        executor._method_loaded = False
        executor._loaded_file_path = ""
        executor._is_running = False
        executor._is_paused = False
        executor._abort_requested = False
        executor._status = "Undefined"
        executor._current_progress = 0.0
        executor._elapsed_str = ""
        executor._remaining_str = ""
        executor._latest_trace = ""

        # Push observable updates
        executor.update_IsMethodLoaded(False)
        executor.update_RuntimeStatus("Undefined")
        executor.update_RuntimeTrace("")

        # Switch simulation mode on the device impl
        executor.set_simulation_mode(simulation_mode)

        mode_str = "simulation" if simulation_mode else "real"
        executor._push_device_status(f"Entered {mode_str} mode")
        logger.info("Reset Venus executor state due to simulation mode change")

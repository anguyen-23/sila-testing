"""Base server class that auto-registers all standard SiLA 2 features.

A device server only needs to:
1. Subclass BaseInstrumentServer
2. Create and register its device-specific feature implementation
3. Implement a `_on_simulation_mode_changed(simulation_mode: bool)` method

Example:
    from sila_server_common.base_server import BaseInstrumentServer

    class Server(BaseInstrumentServer):
        def __init__(self, ...):
            super().__init__(
                server_name="My Device",
                server_description="Description",
                server_type="MyDevice",
                server_version="2.0",
                server_package="my_device",
            )

            # Register device-specific feature
            from .generated.mydevice import MyDeviceFeature
            from .feature_implementations.mydevice_impl import MyDeviceImpl
            self.mydevice = MyDeviceImpl(self)
            self.set_feature_implementation(MyDeviceFeature, self.mydevice)
"""
from __future__ import annotations

import importlib
import logging
from pathlib import Path
from typing import Optional
from uuid import UUID, uuid4

from sila2.server import SilaServer

from .feature_implementations.lockcontroller_impl import LockControllerImpl

logger = logging.getLogger(__name__)


class BaseInstrumentServer(SilaServer):
    """Base class for SiLA 2 instrument servers with all standard features.

    Subclasses must:
    - Call super().__init__() with server metadata
    - Register their device-specific feature(s)
    - The SimulationController calls `on_simulation_mode_changed()` — override
      this to propagate simulation mode to your device feature implementation.
    """

    def __init__(
        self,
        server_name: str,
        server_description: str,
        server_type: str,
        server_version: str = "1.0.0",
        server_vendor_url: str = "",
        server_package: str = "",
        server_uuid: Optional[UUID] = None,
    ):
        super().__init__(
            server_name=server_name,
            server_description=server_description,
            server_type=server_type,
            server_version=server_version,
            server_vendor_url=server_vendor_url,
            server_uuid=server_uuid if server_uuid is not None else uuid4(),
        )

        self._server_package = server_package

        # Import the server's generated modules
        gen = importlib.import_module(f"{server_package}.generated")

        # ── Standard features (order matters for some dependencies) ──

        # LockController — uses sila2 built-in, no generated module needed
        from sila2.features.lockcontroller import LockControllerFeature
        self._lock_controller_impl = LockControllerImpl(self)
        self.set_feature_implementation(LockControllerFeature, self._lock_controller_impl)

        # ScreenStreamer
        ss_gen = importlib.import_module(f"{server_package}.generated.screenstreamer")
        from .feature_implementations.screenstreamer_impl import create_screenstreamer_impl
        ScreenStreamerImpl = create_screenstreamer_impl(ss_gen)
        self.screenstreamer = ScreenStreamerImpl(self)
        self.set_feature_implementation(ss_gen.ScreenStreamerFeature, self.screenstreamer)

        # MessagingClient
        mc_gen = importlib.import_module(f"{server_package}.generated.messagingclient")
        from .feature_implementations.messagingclient_impl import create_messagingclient_impl
        MessagingClientImpl = create_messagingclient_impl(mc_gen)
        self.messagingclient = MessagingClientImpl(self)
        self.set_feature_implementation(mc_gen.MessagingClientFeature, self.messagingclient)

        # SimulationController
        sc_gen = importlib.import_module(f"{server_package}.generated.simulationcontroller")
        SimulationControllerImpl = _create_simulationcontroller_impl(sc_gen, self)
        self.simulationcontroller = SimulationControllerImpl(self)
        self.set_feature_implementation(sc_gen.SimulationControllerFeature, self.simulationcontroller)

        # WebUIProvider
        wui_gen = importlib.import_module(f"{server_package}.generated.webuiprovider")
        from .feature_implementations.webuiprovider_impl import create_webuiprovider_impl
        pkg_dir = Path(importlib.import_module(server_package).__file__).parent
        WebUIProviderImpl = create_webuiprovider_impl(wui_gen, html_path=pkg_dir / "custom_ui.html")
        self.webuiprovider = WebUIProviderImpl(self)
        self.set_feature_implementation(wui_gen.WebUIProviderFeature, self.webuiprovider)

        # UserManualProvider
        ump_gen = importlib.import_module(f"{server_package}.generated.usermanualprovider")
        from .feature_implementations.usermanualprovider_impl import create_usermanualprovider_impl
        UserManualProviderImpl = create_usermanualprovider_impl(ump_gen, pdf_path=pkg_dir / "user_manual.pdf")
        self.usermanualprovider = UserManualProviderImpl(self)
        self.set_feature_implementation(ump_gen.UserManualProviderFeature, self.usermanualprovider)

        # ServerLogProvider
        slp_gen = importlib.import_module(f"{server_package}.generated.serverlogprovider")
        from .feature_implementations.serverlogprovider_impl import create_serverlogprovider_impl
        ServerLogProviderImpl = create_serverlogprovider_impl(slp_gen, db_path=pkg_dir / "logs" / "structured.db")
        self.serverlogprovider = ServerLogProviderImpl(self)
        self.set_feature_implementation(slp_gen.ServerLogProviderFeature, self.serverlogprovider)

        # ScriptRunner
        sr_gen = importlib.import_module(f"{server_package}.generated.scriptrunner")
        from .feature_implementations.scriptrunner_impl import create_scriptrunner_impl
        ScriptRunnerImpl = create_scriptrunner_impl(sr_gen, server_package=server_package)
        self.scriptrunner = ScriptRunnerImpl(self)
        self.set_feature_implementation(sr_gen.ScriptRunnerFeature, self.scriptrunner)

    def start_insecure(self, *args, **kwargs):
        super().start_insecure(*args, **kwargs)
        self._auto_start_screen_capture()

    def start(self, *args, **kwargs):
        super().start(*args, **kwargs)
        self._auto_start_screen_capture()

    def _auto_start_screen_capture(self) -> None:
        """Auto-start screen capture if a window title is persisted in screen_capture.json."""
        from .transports.win32_capture import load_screen_config
        config = load_screen_config(self._server_package)
        if config and config.get("window_title"):
            self.screenstreamer.auto_start(config)

    def on_simulation_mode_changed(self, simulation_mode: bool) -> None:
        """Called when simulation mode changes. Override to propagate to device features.

        The base implementation updates ScreenStreamer and MessagingClient.
        Subclasses should call super() and also update their device-specific feature.
        """
        self.screenstreamer._simulation_mode = simulation_mode
        self.messagingclient._simulation_mode = simulation_mode


def _create_simulationcontroller_impl(generated_module, server: BaseInstrumentServer) -> type:
    """Create a SimulationControllerImpl that delegates to the server's callback."""

    Base = generated_module.SimulationControllerBase
    StartSimulationMode_Responses = generated_module.StartSimulationMode_Responses
    StopSimulationMode_Responses = generated_module.StopSimulationMode_Responses

    class SimulationControllerImpl(Base):
        def __init__(self, parent_server) -> None:
            super().__init__(parent_server=parent_server)
            self._simulation_mode: bool = True

        def start(self) -> None:
            super().start()
            self.update_SimulationMode(self._simulation_mode)
            logger.info("SimulationController started (simulation_mode=%s)", self._simulation_mode)

        @property
        def simulation_mode(self) -> bool:
            return self._simulation_mode

        def StartSimulationMode(self, *, metadata) -> StartSimulationMode_Responses:
            logger.info("Entering simulation mode", extra={"category": "state_change"})
            self._simulation_mode = True
            self.update_SimulationMode(True)
            self.parent_server.on_simulation_mode_changed(True)
            return StartSimulationMode_Responses()

        def StopSimulationMode(self, *, metadata) -> StopSimulationMode_Responses:
            logger.info("Exiting simulation mode", extra={"category": "state_change"})
            self._simulation_mode = False
            self.update_SimulationMode(False)
            self.parent_server.on_simulation_mode_changed(False)
            return StopSimulationMode_Responses()

    return SimulationControllerImpl

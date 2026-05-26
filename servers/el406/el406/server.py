import logging
from typing import Optional
from uuid import UUID

from sila_server_common.base_server import BaseInstrumentServer

from .feature_implementations.el406_impl import EL406Impl
from .generated.el406 import EL406Feature

logger = logging.getLogger(__name__)


class Server(BaseInstrumentServer):
    def __init__(
        self,
        server_uuid: Optional[UUID] = None,
        name: Optional[str] = None,
        description: Optional[str] = None,
    ):
        if name is None:
            name = "BioTek EL406"
        if description is None:
            description = (
                "BioTek EL406 plate washer + dispenser SiLA 2 server "
                "(wraps pylabrobot v1b1)"
            )
        super().__init__(
            server_name=name,
            server_description=description,
            server_type="EL406",
            server_version="1.0.0",
            server_vendor_url="https://github.com/anguyen-23/sila-testing",
            server_package="el406",
            server_uuid=server_uuid,
        )

        self.el406 = EL406Impl(self)
        self.set_feature_implementation(EL406Feature, self.el406)

    def on_simulation_mode_changed(self, simulation_mode: bool) -> None:
        super().on_simulation_mode_changed(simulation_mode)

        el = self.el406

        # If switching modes while connected to real hardware, disconnect first.
        if el._connected and not el._simulation_mode and el._device is not None:
            try:
                el._bridge.run(el._device.stop(), timeout=30)
            except Exception:
                logger.exception("Error stopping EL406 during simulation mode change")

        # Always drop any real-mode plate reference on mode flip — otherwise a
        # later real->sim->real flip would reuse a stale plate while _device is None.
        el._device = None
        el._plate = None

        el._simulation_mode = simulation_mode
        el._connected = False
        el._serial_number = ""
        el._instrument_name = ""
        el._sim_assigned_plate_name = ""
        el._sim_assigned_num_wells = 0
        el.update_IsConnected(False)
        el.update_SerialNumber("")
        el.update_AssignedPlate("")
        el._push_device_status(
            "Entered simulation mode" if simulation_mode else "Entered real mode"
        )

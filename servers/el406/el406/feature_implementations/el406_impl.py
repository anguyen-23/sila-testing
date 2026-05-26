"""BioTek EL406 SiLA 2 feature implementation.

Wraps pylabrobot v1b1's `EL406` device — bridges the asyncio driver to
sila2's synchronous feature interface via a background event loop thread.

Simulation mode: when `_simulation_mode` is True, hardware is never touched;
internal state is kept and DeviceStatus is pushed exactly as in real mode.
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import json
import logging
import threading
import time
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Optional

from sila2.server import MetadataDict, ObservableCommandInstanceWithIntermediateResponses

from ..generated.el406 import (
    Abort_Responses,
    AssignPlate_Responses,
    CommunicationError,
    Connect_Responses,
    ConnectionFailed,
    DeviceError,
    Disconnect_Responses,
    EL406Base,
    HomeMotors_Responses,
    InvalidParameter,
    ManifoldAspirate_IntermediateResponses,
    ManifoldAspirate_Responses,
    ManifoldAutoClean_IntermediateResponses,
    ManifoldAutoClean_Responses,
    ManifoldDispense_IntermediateResponses,
    ManifoldDispense_Responses,
    ManifoldPrime_IntermediateResponses,
    ManifoldPrime_Responses,
    ManifoldWash_IntermediateResponses,
    ManifoldWash_Responses,
    NoPlateAssigned,
    NotConnected,
    Pause_Responses,
    PeristalticDispense_IntermediateResponses,
    PeristalticDispense_Responses,
    PeristalticPrime_IntermediateResponses,
    PeristalticPrime_Responses,
    PeristalticPurge_IntermediateResponses,
    PeristalticPurge_Responses,
    RequestInstrumentSettings_Responses,
    RequestSerialNumber_Responses,
    Reset_Responses,
    Resume_Responses,
    RunSelfCheck_Responses,
    SetWasherManifold_Responses,
    Shake_IntermediateResponses,
    Shake_Responses,
    SyringeDispense_IntermediateResponses,
    SyringeDispense_Responses,
    SyringePrime_IntermediateResponses,
    SyringePrime_Responses,
    UnassignPlate_Responses,
)

if TYPE_CHECKING:
    from ..server import Server

logger = logging.getLogger(__name__)


_STEP_TYPE_MAP = {
    "Current": None,
    "PDispense": "P_DISPENSE",
    "PPrime": "P_PRIME",
    "PPurge": "P_PURGE",
    "SDispense": "S_DISPENSE",
    "SPrime": "S_PRIME",
    "MWash": "M_WASH",
    "MAspirate": "M_ASPIRATE",
    "MDispense": "M_DISPENSE",
    "MPrime": "M_PRIME",
    "MAutoClean": "M_AUTO_CLEAN",
    "ShakeSoak": "SHAKE_SOAK",
}

_HOME_TYPE_MAP = {
    "InitAllMotors": "INIT_ALL_MOTORS",
    "InitPeriPump": "INIT_PERI_PUMP",
    "HomeMotor": "HOME_MOTOR",
    "HomeXyzMotors": "HOME_XYZ_MOTORS",
    "VerifyMotor": "VERIFY_MOTOR",
    "VerifyXyzMotors": "VERIFY_XYZ_MOTORS",
}

_MOTOR_MAP = {
    "CarrierX": "CARRIER_X",
    "CarrierY": "CARRIER_Y",
    "DispHeadZ": "DISP_HEAD_Z",
    "WashHeadZ": "WASH_HEAD_Z",
    "SyringeA": "SYRINGE_A",
    "SyringeB": "SYRINGE_B",
    "PeriPumpPrimary": "PERI_PUMP_PRIMARY",
    "PeriPumpSecondary": "PERI_PUMP_SECONDARY",
    "LevelSenseY": "LEVEL_SENSE_Y",
    "WashSyringe": "WASH_SYRINGE",
    "WashAspHeadZ": "WASH_ASP_HEAD_Z",
    "SingleWellY": "SINGLE_WELL_Y",
}

_WASHER_MANIFOLD_MAP = {
    "Tube96Dual": "TUBE_96_DUAL",
    "Tube192": "TUBE_192",
    "Tube128": "TUBE_128",
    "Tube96Single": "TUBE_96_SINGLE",
    "DeepPin96": "DEEP_PIN_96",
    "NotInstalled": "NOT_INSTALLED",
}


class _AsyncBridge:
    """Run an asyncio event loop in a background thread; call coroutines synchronously."""

    def __init__(self) -> None:
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._started = threading.Event()

    def start(self) -> None:
        if self._thread is not None:
            return

        def _runner() -> None:
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            self._started.set()
            try:
                self._loop.run_forever()
            finally:
                self._loop.close()

        self._thread = threading.Thread(target=_runner, name="el406-asyncio", daemon=True)
        self._thread.start()
        self._started.wait(timeout=5)

    def stop(self) -> None:
        loop = self._loop
        if loop is not None and loop.is_running():
            # Cancel any in-flight tasks so the loop can shut down cleanly.
            async def _cancel_all() -> None:
                tasks = [t for t in asyncio.all_tasks(loop) if t is not asyncio.current_task()]
                for t in tasks:
                    t.cancel()
                if tasks:
                    await asyncio.gather(*tasks, return_exceptions=True)

            try:
                asyncio.run_coroutine_threadsafe(_cancel_all(), loop).result(timeout=5)
            except Exception:
                logger.exception("Error cancelling pending tasks during async bridge stop")
            loop.call_soon_threadsafe(loop.stop)
        if self._thread is not None:
            self._thread.join(timeout=5)
        self._loop = None
        self._thread = None
        self._started.clear()

    def run(self, coro: Awaitable[Any], *, timeout: float | None = None) -> Any:
        if self._loop is None or not self._loop.is_running():
            raise RuntimeError("Async bridge is not running")
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result(timeout=timeout)


class EL406Impl(EL406Base):
    """BioTek EL406 SiLA 2 feature implementation."""

    def __init__(self, parent_server: Server) -> None:
        super().__init__(parent_server=parent_server)

        self.ManifoldAspirate_default_lifetime_of_execution = timedelta(minutes=2)
        self.ManifoldDispense_default_lifetime_of_execution = timedelta(minutes=2)
        self.ManifoldWash_default_lifetime_of_execution = timedelta(minutes=30)
        self.ManifoldPrime_default_lifetime_of_execution = timedelta(hours=2)
        self.ManifoldAutoClean_default_lifetime_of_execution = timedelta(hours=4)
        self.SyringeDispense_default_lifetime_of_execution = timedelta(minutes=5)
        self.SyringePrime_default_lifetime_of_execution = timedelta(hours=1)
        self.PeristalticDispense_default_lifetime_of_execution = timedelta(minutes=5)
        self.PeristalticPrime_default_lifetime_of_execution = timedelta(minutes=10)
        self.PeristalticPurge_default_lifetime_of_execution = timedelta(minutes=10)
        self.Shake_default_lifetime_of_execution = timedelta(minutes=60)

        self._simulation_mode: bool = True
        self._connected: bool = False
        self._serial_number: str = ""
        self._instrument_name: str = ""
        self._activity_log: list[str] = []
        self._lock = threading.Lock()

        self._device: Any = None
        self._plate: Any = None

        self._sim_assigned_plate_name: str = ""
        self._sim_assigned_num_wells: int = 0
        self._sim_washer_manifold: str = "Tube96Dual"

        self._bridge = _AsyncBridge()

    def start(self) -> None:
        super().start()
        self._bridge.start()
        self.update_IsConnected(False)
        self.update_SerialNumber("")
        self.update_AssignedPlate("")
        self._push_device_status()

    def stop(self) -> None:
        try:
            if self._device is not None and not self._simulation_mode:
                try:
                    self._bridge.run(self._device.stop(), timeout=30)
                except Exception:
                    logger.exception("Error stopping EL406 device")
        finally:
            self._device = None
            self._connected = False
            self._bridge.stop()
        super().stop()

    def _push_device_status(self, activity: str | None = None) -> None:
        if activity:
            ts = time.strftime("%H:%M:%S")
            self._activity_log.append(f"[{ts}] {activity}")
            if len(self._activity_log) > 100:
                self._activity_log = self._activity_log[-100:]

        if self._simulation_mode:
            plate_name = self._sim_assigned_plate_name
            num_wells = self._sim_assigned_num_wells
        else:
            plate_name = self._plate.name if self._plate is not None else ""
            num_wells = getattr(self._plate, "num_items", 0) if self._plate is not None else 0

        status = {
            "simulationMode": self._simulation_mode,
            "isConnected": self._connected,
            "instrumentName": self._instrument_name,
            "serialNumber": self._serial_number,
            "assignedPlate": plate_name,
            "numWells": num_wells,
            "washerManifold": self._sim_washer_manifold,
            "activityLog": self._activity_log[-50:],
        }
        self.update_DeviceStatus(json.dumps(status))

    def get_DisplayIcon(self, *, metadata: MetadataDict) -> bytes:
        return (Path(__file__).parent.parent / "icon.png").read_bytes()

    def get_DeviceDescription(self, *, metadata: MetadataDict) -> str:
        return (
            "BioTek EL406 SiLA 2 Server\n\n"
            "Combination plate washer + reagent dispenser. Wraps the pylabrobot v1b1\n"
            "EL406 driver and exposes four subsystems plus low-level driver commands:\n\n"
            "  * Manifold (wash head) — ManifoldAspirate, ManifoldDispense, ManifoldWash,\n"
            "    ManifoldPrime, ManifoldAutoClean. Multi-cycle wash supports shake/soak.\n"
            "    Buffer valves A/B/C/D, flow rates 1-11.\n"
            "  * Syringe pumps — SyringeDispense, SyringePrime. Two syringes A/B.\n"
            "  * Peristaltic pumps — PeristalticDispense, PeristalticPrime,\n"
            "    PeristalticPurge. Cassettes Any/1uL/5uL/10uL.\n"
            "  * Shaker — Shake with optional soak. Intensity Variable/Slow/Medium/Fast.\n\n"
            "Workflow: Connect -> AssignPlate (96 or 384) -> run subsystem commands\n"
            "-> optional Reset/Abort/Pause/Resume -> Disconnect.\n\n"
            "AssignPlate MUST be called before any aspirate/dispense/wash/prime/shake step\n"
            "because the plate type is encoded on every wire frame.\n"
        )

    # ── Helpers ──────────────────────────────────────────────────────

    def _require_connected(self) -> None:
        if not self._connected:
            raise NotConnected("EL406 is not connected. Call Connect first.")

    def _require_plate(self) -> None:
        if self._simulation_mode:
            if not self._sim_assigned_plate_name:
                raise NoPlateAssigned("No plate assigned. Call AssignPlate first.")
        else:
            if self._plate is None:
                raise NoPlateAssigned("No plate assigned. Call AssignPlate first.")

    def _send_progress(
        self,
        instance: ObservableCommandInstanceWithIntermediateResponses[Any],
        message: str,
        cls: type,
    ) -> None:
        instance.send_intermediate_response(cls(StatusMessage=message))

    def _wrap_exec(
        self,
        coro_factory: Callable[[], Awaitable[Any]],
        *,
        timeout: float | None = None,
    ) -> Any:
        try:
            return self._bridge.run(coro_factory(), timeout=timeout)
        except ValueError as e:
            raise InvalidParameter(str(e)) from e
        # concurrent.futures.TimeoutError (from future.result(timeout=...)) and
        # asyncio.TimeoutError / builtin TimeoutError are unified on Python 3.11+
        # but distinct on 3.10. Catch both so bridge-level timeouts always map.
        except (TimeoutError, concurrent.futures.TimeoutError) as e:
            raise CommunicationError(f"Timeout: {e}") from e
        except RuntimeError as e:
            raise CommunicationError(str(e)) from e
        except Exception as e:
            try:
                from pylabrobot.agilent.biotek.el406.errors import (  # type: ignore
                    EL406CommunicationError,
                    EL406DeviceError,
                )
                if isinstance(e, EL406CommunicationError):
                    raise CommunicationError(str(e)) from e
                if isinstance(e, EL406DeviceError):
                    raise DeviceError(str(e)) from e
            except ImportError:
                pass
            raise

    def _sim_step(
        self,
        instance: ObservableCommandInstanceWithIntermediateResponses[Any],
        intermediate_cls: type,
        label: str,
        seconds: float = 0.4,
    ) -> None:
        instance.estimated_remaining_time = timedelta(seconds=seconds)
        ticks = max(2, int(seconds / 0.2))
        for i in range(ticks):
            elapsed = (i + 1) * seconds / ticks
            instance.progress = elapsed / seconds
            instance.estimated_remaining_time = timedelta(seconds=max(0.0, seconds - elapsed))
            self._send_progress(
                instance, f"{label} ({elapsed:.1f}/{seconds:.1f}s sim)", intermediate_cls
            )
            time.sleep(seconds / ticks)
        instance.progress = 1.0

    # ─────────────────────────────────────────────────────────────────
    # CONNECTION
    # ─────────────────────────────────────────────────────────────────

    def Connect(
        self, DeviceId: str, SkipReset: bool, *, metadata: MetadataDict
    ) -> Connect_Responses:
        with self._lock:
            if self._connected:
                logger.info("Connect called while already connected")
                return Connect_Responses(
                    InstrumentName=self._instrument_name,
                    SerialNumber=self._serial_number,
                )

            if self._simulation_mode:
                self._connected = True
                self._instrument_name = "Simulated EL406"
                self._serial_number = ""
                self.update_IsConnected(True)
                self.update_SerialNumber("")
                self._push_device_status(f"Connected (simulated, device_id={DeviceId!r})")
                return Connect_Responses(
                    InstrumentName=self._instrument_name,
                    SerialNumber=self._serial_number,
                )

            try:
                from pylabrobot.agilent.biotek.el406 import EL406  # type: ignore
                from pylabrobot.agilent.biotek.el406.driver import EL406Driver  # type: ignore
            except ImportError as e:
                raise ConnectionFailed(
                    f"pylabrobot import failed: {e}. Install the v1b1 branch:\n"
                    "  pip install git+https://github.com/PyLabRobot/pylabrobot.git@v1b1"
                ) from e

            device_id = DeviceId.strip() or None
            try:
                device = EL406(name="el406", device_id=device_id)
                setup_params = EL406Driver.SetupParams(skip_reset=SkipReset)
                self._bridge.run(device.setup(backend_params=setup_params), timeout=180)
                serial = self._bridge.run(
                    device.driver.request_serial_number(), timeout=15
                )
            except Exception as e:
                raise ConnectionFailed(f"Failed to connect to EL406: {e}") from e

            self._device = device
            self._connected = True
            self._instrument_name = "BioTek EL406"
            self._serial_number = serial
            self.update_IsConnected(True)
            self.update_SerialNumber(serial)
            self._push_device_status(f"Connected (serial={serial})")
            return Connect_Responses(
                InstrumentName=self._instrument_name,
                SerialNumber=self._serial_number,
            )

    def Disconnect(self, *, metadata: MetadataDict) -> Disconnect_Responses:
        with self._lock:
            if not self._connected:
                return Disconnect_Responses(Acknowledged="OK")
            if not self._simulation_mode and self._device is not None:
                try:
                    self._bridge.run(self._device.stop(), timeout=30)
                except Exception:
                    logger.exception("Error during EL406 disconnect")
            self._device = None
            self._plate = None
            self._connected = False
            self.update_IsConnected(False)
            self.update_AssignedPlate("")
            self._push_device_status("Disconnected")
            return Disconnect_Responses(Acknowledged="OK")

    # ─────────────────────────────────────────────────────────────────
    # PLATE ASSIGNMENT
    # ─────────────────────────────────────────────────────────────────

    def AssignPlate(self, NumWells: int, *, metadata: MetadataDict) -> AssignPlate_Responses:
        if NumWells not in (96, 384):
            raise InvalidParameter(f"NumWells must be 96 or 384, got {NumWells}")
        self._require_connected()

        plate_name = f"el406_plate_{NumWells}_{int(time.time())}"

        if self._simulation_mode:
            self._sim_assigned_plate_name = plate_name
            self._sim_assigned_num_wells = NumWells
            self.update_AssignedPlate(plate_name)
            self._push_device_status(
                f"Assigned plate {plate_name} ({NumWells} wells, simulated)"
            )
            return AssignPlate_Responses(PlateName=plate_name)

        try:
            if NumWells == 96:
                from pylabrobot.resources.corning.plates import (  # type: ignore
                    Cor_96_wellplate_360ul_Fb as _factory,
                )
            else:
                from pylabrobot.resources.greiner.plates import (  # type: ignore
                    Greiner_384_wellplate_28ul_Fb as _factory,
                )
            plate = _factory(name=plate_name)
        except ImportError as e:
            raise InvalidParameter(f"Failed to import plate definition: {e}") from e

        if self._plate is not None:
            try:
                self._device.plate_holder.unassign_child_resource(self._plate)
            except Exception:
                logger.exception("Failed to unassign previous plate")
        self._device.plate_holder.assign_child_resource(plate)
        self._plate = plate
        self.update_AssignedPlate(plate_name)
        self._push_device_status(f"Assigned plate {plate_name} ({NumWells} wells)")
        return AssignPlate_Responses(PlateName=plate_name)

    def UnassignPlate(self, *, metadata: MetadataDict) -> UnassignPlate_Responses:
        if self._simulation_mode:
            self._sim_assigned_plate_name = ""
            self._sim_assigned_num_wells = 0
        else:
            if self._device is not None and self._plate is not None:
                try:
                    self._device.plate_holder.unassign_child_resource(self._plate)
                except Exception:
                    logger.exception("Failed to unassign plate")
            self._plate = None
        self.update_AssignedPlate("")
        self._push_device_status("Unassigned plate")
        return UnassignPlate_Responses(Acknowledged="OK")

    # ─────────────────────────────────────────────────────────────────
    # LOW-LEVEL DRIVER COMMANDS
    # ─────────────────────────────────────────────────────────────────

    def Reset(self, *, metadata: MetadataDict) -> Reset_Responses:
        self._require_connected()
        if self._simulation_mode:
            time.sleep(0.3)
            self._push_device_status("Reset (simulated)")
            return Reset_Responses(Acknowledged="OK")
        self._wrap_exec(lambda: self._device.driver.reset(), timeout=180)
        self._push_device_status("Reset complete")
        return Reset_Responses(Acknowledged="OK")

    def Abort(self, StepType: str, *, metadata: MetadataDict) -> Abort_Responses:
        self._require_connected()
        if StepType not in _STEP_TYPE_MAP:
            raise InvalidParameter(f"Unknown StepType: {StepType!r}")
        if self._simulation_mode:
            self._push_device_status(f"Abort {StepType} (simulated)")
            return Abort_Responses(Acknowledged="OK")

        from pylabrobot.agilent.biotek.el406.enums import EL406StepType  # type: ignore

        step_enum = None
        if _STEP_TYPE_MAP[StepType] is not None:
            step_enum = EL406StepType[_STEP_TYPE_MAP[StepType]]
        self._wrap_exec(lambda: self._device.driver.abort(step_type=step_enum), timeout=30)
        self._push_device_status(f"Aborted {StepType}")
        return Abort_Responses(Acknowledged="OK")

    def Pause(self, *, metadata: MetadataDict) -> Pause_Responses:
        self._require_connected()
        if self._simulation_mode:
            self._push_device_status("Pause (simulated)")
            return Pause_Responses(Acknowledged="OK")
        self._wrap_exec(lambda: self._device.driver.pause(), timeout=30)
        self._push_device_status("Paused")
        return Pause_Responses(Acknowledged="OK")

    def Resume(self, *, metadata: MetadataDict) -> Resume_Responses:
        self._require_connected()
        if self._simulation_mode:
            self._push_device_status("Resume (simulated)")
            return Resume_Responses(Acknowledged="OK")
        self._wrap_exec(lambda: self._device.driver.resume(), timeout=30)
        self._push_device_status("Resumed")
        return Resume_Responses(Acknowledged="OK")

    def HomeMotors(
        self, HomeType: str, Motor: str, *, metadata: MetadataDict
    ) -> HomeMotors_Responses:
        self._require_connected()
        if HomeType not in _HOME_TYPE_MAP:
            raise InvalidParameter(f"Unknown HomeType: {HomeType!r}")
        if Motor and Motor not in _MOTOR_MAP:
            raise InvalidParameter(f"Unknown Motor: {Motor!r}")
        if self._simulation_mode:
            time.sleep(0.2)
            self._push_device_status(
                f"HomeMotors {HomeType}/{Motor or 'default'} (simulated)"
            )
            return HomeMotors_Responses(Acknowledged="OK")

        from pylabrobot.agilent.biotek.el406.enums import (  # type: ignore
            EL406Motor,
            EL406MotorHomeType,
        )

        home_enum = EL406MotorHomeType[_HOME_TYPE_MAP[HomeType]]
        motor_enum = EL406Motor[_MOTOR_MAP[Motor]] if Motor else None
        self._wrap_exec(
            lambda: self._device.driver.home_motors(home_type=home_enum, motor=motor_enum),
            timeout=180,
        )
        self._push_device_status(f"HomeMotors {HomeType}/{Motor or 'default'}")
        return HomeMotors_Responses(Acknowledged="OK")

    def SetWasherManifold(
        self, Manifold: str, *, metadata: MetadataDict
    ) -> SetWasherManifold_Responses:
        self._require_connected()
        if Manifold not in _WASHER_MANIFOLD_MAP:
            raise InvalidParameter(f"Unknown Manifold: {Manifold!r}")
        if self._simulation_mode:
            self._sim_washer_manifold = Manifold
            self._push_device_status(f"SetWasherManifold {Manifold} (simulated)")
            return SetWasherManifold_Responses(Acknowledged="OK")

        from pylabrobot.agilent.biotek.el406.enums import (  # type: ignore
            EL406WasherManifold,
        )

        manifold_enum = EL406WasherManifold[_WASHER_MANIFOLD_MAP[Manifold]]
        self._wrap_exec(
            lambda: self._device.driver.set_washer_manifold(manifold_enum), timeout=30
        )
        self._sim_washer_manifold = Manifold  # only after success
        self._push_device_status(f"SetWasherManifold {Manifold}")
        return SetWasherManifold_Responses(Acknowledged="OK")

    def RunSelfCheck(self, *, metadata: MetadataDict) -> RunSelfCheck_Responses:
        self._require_connected()
        if self._simulation_mode:
            time.sleep(0.2)
            self._push_device_status("RunSelfCheck (simulated)")
            return RunSelfCheck_Responses(
                Success=True, ErrorCode=0, Message="Self-check passed (simulated)"
            )
        result = self._wrap_exec(lambda: self._device.driver.run_self_check(), timeout=180)
        self._push_device_status(f"RunSelfCheck -> {result['message']}")
        return RunSelfCheck_Responses(
            Success=bool(result["success"]),
            ErrorCode=int(result["error_code"]),
            Message=str(result["message"]),
        )

    def RequestSerialNumber(
        self, *, metadata: MetadataDict
    ) -> RequestSerialNumber_Responses:
        self._require_connected()
        if self._simulation_mode:
            self._push_device_status("RequestSerialNumber (simulated)")
            return RequestSerialNumber_Responses(SerialNumber=self._serial_number)
        serial = self._wrap_exec(
            lambda: self._device.driver.request_serial_number(), timeout=15
        )
        self._serial_number = serial
        self.update_SerialNumber(serial)
        self._push_device_status(f"Queried serial number: {serial}")
        return RequestSerialNumber_Responses(SerialNumber=serial)

    def RequestInstrumentSettings(
        self, *, metadata: MetadataDict
    ) -> RequestInstrumentSettings_Responses:
        self._require_connected()
        if self._simulation_mode:
            payload = {
                "washer_manifold": self._sim_washer_manifold,
                "syringe_manifold": "NOT_INSTALLED",
                "syringe_box": {"box_type": 0, "box_size": 0, "installed": False},
                "peristaltic_pump_1": True,
                "peristaltic_pump_2": False,
                "simulated": True,
            }
            return RequestInstrumentSettings_Responses(SettingsJson=json.dumps(payload))
        settings = self._wrap_exec(
            lambda: self._device.driver.request_instrument_settings(), timeout=60
        )
        payload = {
            "washer_manifold": settings["washer_manifold"].name,
            "syringe_manifold": settings["syringe_manifold"].name,
            "syringe_box": dict(settings["syringe_box"]),
            "peristaltic_pump_1": settings["peristaltic_pump_1"],
            "peristaltic_pump_2": settings["peristaltic_pump_2"],
        }
        self._push_device_status("Queried instrument settings")
        return RequestInstrumentSettings_Responses(SettingsJson=json.dumps(payload))

    # ─────────────────────────────────────────────────────────────────
    # MANIFOLD STEPS
    # ─────────────────────────────────────────────────────────────────

    def ManifoldAspirate(
        self,
        VacuumFiltration: bool,
        TravelRate: str,
        Delay: float,
        VacuumTime: float,
        OffsetX: int,
        OffsetY: int,
        OffsetZ: int,
        *,
        metadata: MetadataDict,
        instance: ObservableCommandInstanceWithIntermediateResponses[
            ManifoldAspirate_IntermediateResponses
        ],
    ) -> ManifoldAspirate_Responses:
        self._require_connected()
        self._require_plate()
        instance.begin_execution()

        if self._simulation_mode:
            self._sim_step(
                instance,
                ManifoldAspirate_IntermediateResponses,
                f"ManifoldAspirate vacuum={VacuumFiltration}",
                seconds=0.6,
            )
            self._push_device_status(
                f"ManifoldAspirate (simulated): vacuum={VacuumFiltration}"
            )
            return ManifoldAspirate_Responses(Acknowledged="OK")

        from pylabrobot.agilent.biotek.el406.plate_washing_backend import (  # type: ignore
            EL406PlateWasher96Backend,
        )

        params = EL406PlateWasher96Backend.AspirateParams(
            vacuum_filtration=VacuumFiltration,
            travel_rate=TravelRate,
            delay=Delay,
            vacuum_time=VacuumTime,
            offset_x=OffsetX,
            offset_y=OffsetY,
            offset_z=OffsetZ if OffsetZ > 0 else None,
        )
        self._send_progress(
            instance, "Sending aspirate", ManifoldAspirate_IntermediateResponses
        )
        self._wrap_exec(
            lambda: self._device.washer.aspirate(self._plate, backend_params=params),
            timeout=120,
        )
        self._push_device_status(
            f"ManifoldAspirate complete (vacuum={VacuumFiltration})"
        )
        return ManifoldAspirate_Responses(Acknowledged="OK")

    def ManifoldDispense(
        self,
        Volume: float,
        Buffer: str,
        FlowRate: int,
        OffsetX: int,
        OffsetY: int,
        OffsetZ: int,
        PreDispenseVolume: float,
        PreDispenseFlowRate: int,
        VacuumDelayVolume: float,
        *,
        metadata: MetadataDict,
        instance: ObservableCommandInstanceWithIntermediateResponses[
            ManifoldDispense_IntermediateResponses
        ],
    ) -> ManifoldDispense_Responses:
        self._require_connected()
        self._require_plate()
        instance.begin_execution()

        if self._simulation_mode:
            self._sim_step(
                instance,
                ManifoldDispense_IntermediateResponses,
                f"ManifoldDispense {Volume}uL buffer={Buffer}",
                seconds=0.6,
            )
            self._push_device_status(
                f"ManifoldDispense (simulated): {Volume}uL, buffer {Buffer}"
            )
            return ManifoldDispense_Responses(Acknowledged="OK")

        from pylabrobot.agilent.biotek.el406.plate_washing_backend import (  # type: ignore
            EL406PlateWasher96Backend,
        )

        params = EL406PlateWasher96Backend.DispenseParams(
            buffer=Buffer,
            flow_rate=FlowRate,
            offset_x=OffsetX,
            offset_y=OffsetY,
            offset_z=OffsetZ if OffsetZ > 0 else None,
            pre_dispense_volume=PreDispenseVolume,
            pre_dispense_flow_rate=PreDispenseFlowRate,
            vacuum_delay_volume=VacuumDelayVolume,
        )
        self._send_progress(
            instance, "Sending dispense", ManifoldDispense_IntermediateResponses
        )
        self._wrap_exec(
            lambda: self._device.washer.dispense(
                self._plate, volume=Volume, backend_params=params
            ),
            timeout=120,
        )
        self._push_device_status(
            f"ManifoldDispense complete: {Volume}uL, buffer {Buffer}"
        )
        return ManifoldDispense_Responses(Acknowledged="OK")

    def ManifoldWash(
        self,
        Cycles: int,
        DispenseVolume: float,
        Buffer: str,
        DispenseFlowRate: int,
        AspirateTravelRate: int,
        SoakDuration: int,
        ShakeDuration: int,
        ShakeIntensity: str,
        FinalAspirate: bool,
        *,
        metadata: MetadataDict,
        instance: ObservableCommandInstanceWithIntermediateResponses[
            ManifoldWash_IntermediateResponses
        ],
    ) -> ManifoldWash_Responses:
        self._require_connected()
        self._require_plate()
        instance.begin_execution()
        instance.estimated_remaining_time = timedelta(
            seconds=Cycles * 30 + ShakeDuration + SoakDuration
        )

        if self._simulation_mode:
            self._sim_step(
                instance,
                ManifoldWash_IntermediateResponses,
                f"ManifoldWash {Cycles} cycles buffer={Buffer}",
                seconds=min(3.0, 0.4 * Cycles + 0.2),
            )
            self._push_device_status(
                f"ManifoldWash (simulated): {Cycles} cycles, buffer {Buffer}"
            )
            return ManifoldWash_Responses(Acknowledged="OK")

        from pylabrobot.agilent.biotek.el406.plate_washing_backend import (  # type: ignore
            EL406PlateWasher96Backend,
        )

        params = EL406PlateWasher96Backend.WashParams(
            buffer=Buffer,
            dispense_flow_rate=DispenseFlowRate,
            aspirate_travel_rate=AspirateTravelRate,
            soak_duration=SoakDuration,
            shake_duration=ShakeDuration,
            shake_intensity=ShakeIntensity,
            final_aspirate=FinalAspirate,
        )
        self._send_progress(
            instance,
            f"Starting wash: {Cycles} cycles",
            ManifoldWash_IntermediateResponses,
        )
        dispense_vol = DispenseVolume if DispenseVolume > 0 else None
        timeout = (Cycles * 60) + ShakeDuration + SoakDuration + 180
        self._wrap_exec(
            lambda: self._device.washer.wash(
                self._plate,
                cycles=Cycles,
                dispense_volume=dispense_vol,
                backend_params=params,
            ),
            timeout=timeout,
        )
        self._push_device_status(
            f"ManifoldWash complete: {Cycles} cycles, buffer {Buffer}"
        )
        return ManifoldWash_Responses(Acknowledged="OK")

    def ManifoldPrime(
        self,
        Volume: float,
        Buffer: str,
        FlowRate: int,
        LowFlowVolume: float,
        SubmergeDuration: float,
        *,
        metadata: MetadataDict,
        instance: ObservableCommandInstanceWithIntermediateResponses[
            ManifoldPrime_IntermediateResponses
        ],
    ) -> ManifoldPrime_Responses:
        self._require_connected()
        self._require_plate()
        instance.begin_execution()

        if self._simulation_mode:
            self._sim_step(
                instance,
                ManifoldPrime_IntermediateResponses,
                f"ManifoldPrime {Volume}uL buffer={Buffer}",
                seconds=1.0,
            )
            self._push_device_status(
                f"ManifoldPrime (simulated): {Volume}uL, buffer {Buffer}"
            )
            return ManifoldPrime_Responses(Acknowledged="OK")

        from pylabrobot.agilent.biotek.el406.plate_washing_backend import (  # type: ignore
            EL406PlateWasher96Backend,
        )

        params = EL406PlateWasher96Backend.PrimeParams(
            volume=Volume,
            buffer=Buffer,
            flow_rate=FlowRate,
            low_flow_volume=LowFlowVolume,
            submerge_duration=SubmergeDuration,
        )
        timeout = 60 + SubmergeDuration + 60
        self._wrap_exec(
            lambda: self._device.washer.prime(self._plate, backend_params=params),
            timeout=timeout,
        )
        self._push_device_status(
            f"ManifoldPrime complete: {Volume}uL, buffer {Buffer}"
        )
        return ManifoldPrime_Responses(Acknowledged="OK")

    def ManifoldAutoClean(
        self,
        Buffer: str,
        Duration: float,
        *,
        metadata: MetadataDict,
        instance: ObservableCommandInstanceWithIntermediateResponses[
            ManifoldAutoClean_IntermediateResponses
        ],
    ) -> ManifoldAutoClean_Responses:
        self._require_connected()
        self._require_plate()
        instance.begin_execution()
        instance.estimated_remaining_time = timedelta(seconds=Duration)

        if self._simulation_mode:
            self._sim_step(
                instance,
                ManifoldAutoClean_IntermediateResponses,
                f"ManifoldAutoClean buffer={Buffer} for {Duration}s",
                seconds=1.0,
            )
            self._push_device_status(
                f"ManifoldAutoClean (simulated): buffer {Buffer}, {Duration}s"
            )
            return ManifoldAutoClean_Responses(Acknowledged="OK")

        timeout = max(120.0, Duration + 60.0)
        self._wrap_exec(
            lambda: self._device.washer.backend.auto_clean(
                self._plate, buffer=Buffer, duration=Duration
            ),
            timeout=timeout,
        )
        self._push_device_status(
            f"ManifoldAutoClean complete: buffer {Buffer}, {Duration}s"
        )
        return ManifoldAutoClean_Responses(Acknowledged="OK")

    # ─────────────────────────────────────────────────────────────────
    # SYRINGE STEPS
    # ─────────────────────────────────────────────────────────────────

    def SyringeDispense(
        self,
        Volume: float,
        Syringe: str,
        FlowRate: int,
        OffsetX: float,
        OffsetY: float,
        OffsetZ: float,
        PumpDelay: float,
        PreDispense: bool,
        PreDispenseVolume: float,
        NumPreDispenses: int,
        *,
        metadata: MetadataDict,
        instance: ObservableCommandInstanceWithIntermediateResponses[
            SyringeDispense_IntermediateResponses
        ],
    ) -> SyringeDispense_Responses:
        self._require_connected()
        self._require_plate()
        instance.begin_execution()

        if self._simulation_mode:
            self._sim_step(
                instance,
                SyringeDispense_IntermediateResponses,
                f"SyringeDispense {Volume}uL from {Syringe}",
                seconds=0.6,
            )
            self._push_device_status(
                f"SyringeDispense (simulated): {Volume}uL from {Syringe}"
            )
            return SyringeDispense_Responses(Acknowledged="OK")

        from pylabrobot.agilent.biotek.el406.syringe_dispensing_backend8 import (  # type: ignore
            EL406SyringeDispensingBackend8,
        )
        from pylabrobot.agilent.biotek.el406.helpers import plate_max_columns  # type: ignore

        params = EL406SyringeDispensingBackend8.DispenseParams(
            syringe=Syringe,
            flow_rate=FlowRate,
            offset_x=OffsetX,
            offset_y=OffsetY,
            offset_z=OffsetZ,
            pump_delay=PumpDelay,
            pre_dispense=PreDispense,
            pre_dispense_volume=PreDispenseVolume,
            num_pre_dispenses=NumPreDispenses,
        )
        num_cols = plate_max_columns(self._plate)
        volumes = {col: Volume for col in range(1, num_cols + 1)}
        self._wrap_exec(
            lambda: self._device.syringe_dispenser.backend.dispense(
                self._plate, volumes=volumes, backend_params=params
            ),
            timeout=300,
        )
        self._push_device_status(
            f"SyringeDispense complete: {Volume}uL from {Syringe}"
        )
        return SyringeDispense_Responses(Acknowledged="OK")

    def SyringePrime(
        self,
        Volume: float,
        Syringe: str,
        FlowRate: int,
        Refills: int,
        PumpDelay: float,
        SubmergeTips: bool,
        SubmergeDuration: float,
        *,
        metadata: MetadataDict,
        instance: ObservableCommandInstanceWithIntermediateResponses[
            SyringePrime_IntermediateResponses
        ],
    ) -> SyringePrime_Responses:
        self._require_connected()
        self._require_plate()
        instance.begin_execution()

        if self._simulation_mode:
            self._sim_step(
                instance,
                SyringePrime_IntermediateResponses,
                f"SyringePrime {Syringe} {Refills} refills",
                seconds=0.8,
            )
            self._push_device_status(
                f"SyringePrime (simulated): {Syringe} x {Refills}"
            )
            return SyringePrime_Responses(Acknowledged="OK")

        from pylabrobot.agilent.biotek.el406.syringe_dispensing_backend8 import (  # type: ignore
            EL406SyringeDispensingBackend8,
        )

        params = EL406SyringeDispensingBackend8.PrimeParams(
            syringe=Syringe,
            flow_rate=FlowRate,
            refills=Refills,
            pump_delay=PumpDelay,
            submerge_tips=SubmergeTips,
            submerge_duration=SubmergeDuration,
        )
        timeout = 60 + SubmergeDuration + 60
        self._wrap_exec(
            lambda: self._device.syringe_dispenser.backend.prime(
                self._plate, volume=Volume, backend_params=params
            ),
            timeout=timeout,
        )
        self._push_device_status(f"SyringePrime complete: {Syringe} x {Refills}")
        return SyringePrime_Responses(Acknowledged="OK")

    # ─────────────────────────────────────────────────────────────────
    # PERISTALTIC STEPS
    # ─────────────────────────────────────────────────────────────────

    def PeristalticDispense(
        self,
        Volume: float,
        FlowRate: str,
        Cassette: str,
        OffsetX: float,
        OffsetY: float,
        OffsetZ: float,
        PreDispenseVolume: float,
        NumPreDispenses: int,
        *,
        metadata: MetadataDict,
        instance: ObservableCommandInstanceWithIntermediateResponses[
            PeristalticDispense_IntermediateResponses
        ],
    ) -> PeristalticDispense_Responses:
        self._require_connected()
        self._require_plate()
        instance.begin_execution()

        if self._simulation_mode:
            self._sim_step(
                instance,
                PeristalticDispense_IntermediateResponses,
                f"PeristalticDispense {Volume}uL flow={FlowRate}",
                seconds=0.5,
            )
            self._push_device_status(
                f"PeristalticDispense (simulated): {Volume}uL, flow {FlowRate}"
            )
            return PeristalticDispense_Responses(Acknowledged="OK")

        from pylabrobot.agilent.biotek.el406.peristaltic_dispensing_backend8 import (  # type: ignore
            EL406PeristalticDispensingBackend8,
        )
        from pylabrobot.agilent.biotek.el406.helpers import plate_max_columns  # type: ignore

        params = EL406PeristalticDispensingBackend8.DispenseParams(
            flow_rate=FlowRate,
            offset_x=OffsetX,
            offset_y=OffsetY,
            offset_z=OffsetZ if OffsetZ > 0 else None,
            pre_dispense_volume=PreDispenseVolume,
            num_pre_dispenses=NumPreDispenses,
            cassette=Cassette,
        )
        num_cols = plate_max_columns(self._plate)
        volumes = {col: Volume for col in range(1, num_cols + 1)}
        self._wrap_exec(
            lambda: self._device.peristaltic_dispenser.backend.dispense(
                self._plate, volumes=volumes, backend_params=params
            ),
            timeout=300,
        )
        self._push_device_status(
            f"PeristalticDispense complete: {Volume}uL, flow {FlowRate}"
        )
        return PeristalticDispense_Responses(Acknowledged="OK")

    def _peristaltic_prime_or_purge(
        self,
        *,
        Volume: float,
        Duration: int,
        FlowRate: str,
        Cassette: str,
        is_purge: bool,
        instance: ObservableCommandInstanceWithIntermediateResponses[Any],
        intermediate_cls: type,
    ) -> None:
        self._require_connected()
        self._require_plate()

        if Volume > 0 and Duration > 0:
            raise InvalidParameter(
                "Specify Volume OR Duration (set the unused one to 0)."
            )
        if Volume <= 0 and Duration <= 0:
            raise InvalidParameter("At least one of Volume or Duration must be > 0.")

        instance.begin_execution()
        action = "purge" if is_purge else "prime"

        if self._simulation_mode:
            self._sim_step(
                instance,
                intermediate_cls,
                f"Peristaltic{action.capitalize()} flow={FlowRate}",
                seconds=0.8,
            )
            label = f"Vol={Volume}uL" if Volume > 0 else f"Dur={Duration}s"
            self._push_device_status(
                f"Peristaltic{action.capitalize()} (simulated): {label}, flow {FlowRate}"
            )
            return

        from pylabrobot.agilent.biotek.el406.peristaltic_dispensing_backend8 import (  # type: ignore
            EL406PeristalticDispensingBackend8,
        )

        params = EL406PeristalticDispensingBackend8.PrimeParams(
            flow_rate=FlowRate, cassette=Cassette
        )
        vol_arg = Volume if Volume > 0 else None
        dur_arg = Duration if Duration > 0 else None
        timeout = 60 + (Duration if Duration > 0 else 60)
        method = (
            self._device.peristaltic_dispenser.backend.purge
            if is_purge
            else self._device.peristaltic_dispenser.backend.prime
        )
        self._wrap_exec(
            lambda: method(
                self._plate, volume=vol_arg, duration=dur_arg, backend_params=params
            ),
            timeout=timeout,
        )
        label = f"Vol={Volume}uL" if Volume > 0 else f"Dur={Duration}s"
        self._push_device_status(
            f"Peristaltic{action.capitalize()} complete: {label}, flow {FlowRate}"
        )

    def PeristalticPrime(
        self,
        Volume: float,
        Duration: int,
        FlowRate: str,
        Cassette: str,
        *,
        metadata: MetadataDict,
        instance: ObservableCommandInstanceWithIntermediateResponses[
            PeristalticPrime_IntermediateResponses
        ],
    ) -> PeristalticPrime_Responses:
        self._peristaltic_prime_or_purge(
            Volume=Volume,
            Duration=Duration,
            FlowRate=FlowRate,
            Cassette=Cassette,
            is_purge=False,
            instance=instance,
            intermediate_cls=PeristalticPrime_IntermediateResponses,
        )
        return PeristalticPrime_Responses(Acknowledged="OK")

    def PeristalticPurge(
        self,
        Volume: float,
        Duration: int,
        FlowRate: str,
        Cassette: str,
        *,
        metadata: MetadataDict,
        instance: ObservableCommandInstanceWithIntermediateResponses[
            PeristalticPurge_IntermediateResponses
        ],
    ) -> PeristalticPurge_Responses:
        self._peristaltic_prime_or_purge(
            Volume=Volume,
            Duration=Duration,
            FlowRate=FlowRate,
            Cassette=Cassette,
            is_purge=True,
            instance=instance,
            intermediate_cls=PeristalticPurge_IntermediateResponses,
        )
        return PeristalticPurge_Responses(Acknowledged="OK")

    # ─────────────────────────────────────────────────────────────────
    # SHAKER
    # ─────────────────────────────────────────────────────────────────

    def Shake(
        self,
        Duration: int,
        Intensity: str,
        SoakDuration: int,
        MoveHomeFirst: bool,
        *,
        metadata: MetadataDict,
        instance: ObservableCommandInstanceWithIntermediateResponses[
            Shake_IntermediateResponses
        ],
    ) -> Shake_Responses:
        self._require_connected()
        self._require_plate()
        if Duration <= 0 and SoakDuration <= 0:
            raise InvalidParameter(
                "At least one of Duration or SoakDuration must be > 0."
            )
        instance.begin_execution()
        instance.estimated_remaining_time = timedelta(seconds=Duration + SoakDuration)

        if self._simulation_mode:
            self._sim_step(
                instance,
                Shake_IntermediateResponses,
                f"Shake {Duration}s {Intensity} soak={SoakDuration}s",
                seconds=min(2.0, 0.05 * (Duration + SoakDuration) + 0.2),
            )
            self._push_device_status(
                f"Shake (simulated): {Duration}s {Intensity}, soak {SoakDuration}s"
            )
            return Shake_Responses(Acknowledged="OK")

        from pylabrobot.agilent.biotek.el406.shaking_backend import (  # type: ignore
            EL406ShakingBackend,
        )

        params = EL406ShakingBackend.ShakeParams(
            intensity=Intensity,
            soak_duration=SoakDuration,
            move_home_first=MoveHomeFirst,
        )
        timeout = Duration + SoakDuration + 60
        self._wrap_exec(
            lambda: self._device.shaker.shake(
                speed=0.0, duration=Duration, backend_params=params
            ),
            timeout=timeout,
        )
        self._push_device_status(
            f"Shake complete: {Duration}s {Intensity}, soak {SoakDuration}s"
        )
        return Shake_Responses(Acknowledged="OK")

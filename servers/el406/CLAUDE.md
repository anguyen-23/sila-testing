# BioTek EL406 SiLA 2 Server

## What This Is
A SiLA 2 server for the BioTek EL406 combination plate washer + dispenser. Wraps
pylabrobot v1b1's `EL406` device — the SiLA layer is a thin async-to-sync bridge
around the existing pylabrobot driver. Part of the sila-testing platform.

## Architecture
This server uses the `sila_server_common` shared library. The only files you
need to edit are:

1. **`EL406.sila.xml`** — Device FDL (22 commands, 5 errors, observable + standard properties)
2. **`el406/feature_implementations/el406_impl.py`** — Device implementation
3. **`el406/custom_ui.html`** — React + Babel WebUI
4. **`el406/server.py`** — `BaseInstrumentServer` subclass + simulation-mode handler

Everything else (LockController, SimulationController, ScreenStreamer,
MessagingClient, ServerLogProvider, ScriptRunner, WebUIProvider,
UserManualProvider) is auto-registered by `BaseInstrumentServer`.

## Subsystems Exposed via SiLA Commands

| Group | Commands |
|---|---|
| Connection | Connect, Disconnect |
| Plate | AssignPlate (96 \| 384), UnassignPlate |
| Driver | Reset, Abort, Pause, Resume, HomeMotors, SetWasherManifold, RunSelfCheck, RequestSerialNumber, RequestInstrumentSettings |
| Manifold | ManifoldAspirate, ManifoldDispense, ManifoldWash, ManifoldPrime, ManifoldAutoClean |
| Syringe | SyringeDispense, SyringePrime |
| Peristaltic | PeristalticDispense, PeristalticPrime, PeristalticPurge |
| Shaker | Shake |

Long-running commands (Wash, Prime, AutoClean, Shake, etc.) are **observable**
with progress + status updates.

## Async-to-sync Bridge

The pylabrobot driver is `asyncio`-based; sila2 features are synchronous.
`EL406Impl._bridge` runs an event loop in a background thread; every command
that touches hardware calls `self._bridge.run(coro, timeout=...)`.

## Simulation Mode

When `_simulation_mode` is True (the default), no hardware is touched — pylabrobot
isn't even imported. Internal state (assigned plate, manifold, serial number) is
maintained so the WebUI/SSE flow behaves identically. The `SimulationController`
feature toggles this via `on_simulation_mode_changed` in `server.py`.

## Key Files
```
el406/
├── EL406.sila.xml                       # Device feature definition
├── SimulationController.sila.xml        # Standard features (do not edit)
├── ScreenStreamer.sila.xml
├── MessagingClient.sila.xml
├── WebUIProvider.sila.xml
├── UserManualProvider.sila.xml
├── ServerLogProvider.sila.xml
├── ScriptRunner.sila.xml
├── pyproject.toml                       # Pins pylabrobot @ v1b1
├── deploy.bat
├── start_server.bat
└── el406/
    ├── __init__.py
    ├── __main__.py                      # Entry point (uses create_main)
    ├── server.py                        # BaseInstrumentServer subclass
    ├── custom_ui.html                   # React WebUI (connection + 4 subsystem tabs)
    ├── icon.png                         # Placeholder icon
    └── feature_implementations/
        └── el406_impl.py                # ~900 lines; wraps pylabrobot.agilent.biotek.el406
```

## Commands

```bash
# Install
pip install -e servers/el406

# Run in simulation
python -m el406 --insecure --port 50061 --verbose --simulation

# Run on real hardware
python -m el406 --insecure --port 50061 --verbose

# Validate compliance
python -m sila_server_common.validate servers/el406

# Test suite (in web UI, after starting the server)
# Open http://localhost:5000/tests/el406
```

## Workflow

```
Connect (DeviceId="", SkipReset=true)
  ↓
AssignPlate (NumWells=96 or 384)   ← required before any step command
  ↓
SetWasherManifold (e.g. Tube96Dual)  ← optional, one-time
  ↓
Manifold/Syringe/Peristaltic/Shake commands as needed
  ↓
UnassignPlate
  ↓
Disconnect
```

## Reference
- Full SiLA framework guide: `CREATING_SERVERS.md` in the project root
- Reference server (similar serial-wrapper): `servers/multidrop_combi/`
- Shared library: `packages/sila_server_common/`
- Wrapped driver: `pylabrobot/agilent/biotek/el406/` on v1b1

# CLAUDE.md - SiLA 2 Server Development & Testing Platform

## Project Overview
This is a **development and testing platform** for building SiLA 2 (Standardization in Lab Automation) instrument servers.
Developers use this project to create, test, and validate instrument servers that will be deployed in production environments.
All servers MUST follow the same standardized architecture to ensure consistency across the fleet.
The `client_web_ui` in this project is a **testing tool** — the production client is a separate application.

## Tech Stack
- **Python 3.13+** with `sila2[full]` package (from PyPI)
- **Flask** for the Client Web UI
- **gRPC** (via sila2 library) for SiLA communication
- Virtual environment in `.venv/`

## Project Structure
```
servers/              # SiLA 2 Server implementations (one per device)
  temperature_controller/   # Simulated heating/cooling device
  pump_controller/          # Simulated liquid pump
  plate_reader/             # Simulated plate reader
  multidrop_combi/          # Thermo Multidrop Combi serial wrapper (pyserial)
  venus_api/                # Hamilton VENUS Web API wrapper (REST+SignalR)
  barcode_scanner/          # Datalogic barcode scanner serial wrapper (pyserial)
  phenix_imager/            # PerkinElmer Opera Phenix RCI wrapper (comtypes)
  micronic_tube_scanner/    # Micronic 2D tube scanner REST wrapper
  xarm6/                    # UFACTORY xArm 6 robotic arm (xArm Python SDK)
packages/
  sila_server_common/       # Shared library: base server, feature factories, scaffold, validator
client_web_ui/        # Flask web app for discovering and interacting with servers + message server (port 8765) + test runner
deployment/           # Ansible deployment system (playbooks, inventory, roles, admin console, screen capture helper)
documentation/        # SiLA 2 specification PDFs and reference material
```

## Key Conventions
- Each server is a standalone Python package generated via `sila2-codegen`
- FDL files (`.sila.xml`) define the SiLA Features for each device
- Servers support both real and simulation modes via a `--simulation` flag
- All servers run insecure (`--insecure`) for local development
- Each server includes a `deploy.bat` for one-click deployment on target machines (see `DEPLOY.md`)
- Default ports: Temperature=50052, Pump=50053, PlateReader=50054, MultidropCombi=50055, VenusAPI=50056, BarcodeScanner=50057, PhenixImager=50058, MicronicTubeScanner=50059, XArm6=50060, WebUI=5000, AdminConsole=5001, MessageServer(WS)=8765, ScreenCaptureHelper=8766
- Every server includes ScreenStreamer (Win32 window capture), MessagingClient (WebSocket messaging), ServerLogProvider (structured SQLite logging), and ScriptRunner (Python automation scripts) as reusable cross-server features
- Optional per-server features: CameraStreamProvider (IP/USB camera via OpenCV) — servers opt in with `--camera` scaffold flag or manual registration
- Transport modules `win32_capture.py`, `messaging_transport.py`, `structured_logging.py`, `camera_capture.py`, and `device_helpers.py` are identical across all servers — do not diverge
- When running as a Windows service (Session 0), ScreenStreamer delegates to the screen capture helper (port 8766) running in the user session

## Test Runner Framework
- Test suites are JSON files in `client_web_ui/test_suites/`
- Tests can be `scripted` (automated via command/check_response/wait/loop DSL) or `manual` (checklist)
- Tests are tagged with `modes: ["simulation"]`, `["real"]`, or `["simulation", "real"]`
- The runner is a React + Babel CDN app at `/tests/<suite_name>`
- Test DSL actions: `command`, `check_response`, `wait`, `loop`, `loop_values`, `ensure_connected`
- `ensure_connected` infers simulation vs real mode from test's `modes` tag
- Command parameter ordering uses FDL definition order (not alphabetical JSON key order)
- See `CREATING_SERVERS.md` for full documentation

## Server Architecture
All servers MUST implement the standard architecture pattern. See `CREATING_SERVERS.md` for full documentation.

### Required Features (every server)
- **Device-specific feature** — Commands and properties for the instrument (custom per device)
- **DeviceStatus** observable property — JSON blob carrying full device state, drives the WebUI
- **WebUIProvider** — React + Babel CDN single-file WebUI served via SiLA property
- **SimulationController** — Simulation mode support (`--simulation` flag)
- **LockController** — Device locking (generated via `--lock-controller` codegen flag)
- **ScreenStreamer** — Win32 window capture (Session 0 helper proxy for services)
- **MessagingClient** — WebSocket messaging with auto-reconnect
- **ServerLogProvider** — Structured SQLite logging with SiLA query interface
- **ScriptRunner** — Per-server Python automation scripts with output streaming
- **UserManualProvider** — PDF manual served as binary property
- **DisplayIcon** — PNG icon served as binary property
- **DeviceDescription** — Rich text description for LLM/MCP system prompts

### Architecture Pattern
```
Browser (React WebUI)  <-- SSE -->  Flask client_web_ui  <-- gRPC streaming -->  SiLA 2 Server
                                                                                      |
                                                                              Observable Properties
                                                                              (DeviceStatus JSON push)
```

### Key Principles
- Observable Properties for real-time state push (not polling)
- Every command pushes a DeviceStatus update after execution
- React + Babel CDN single-file WebUI (no build step)
- SSE bridging from gRPC observable properties to browser
- Shared transport modules are identical across all servers — never diverge
- Device-specific logic lives only in the device feature implementation and WebUI

## Development Commands
```bash
# Activate venv
source .venv/Scripts/activate    # Windows Git Bash
.venv\Scripts\activate.bat       # Windows CMD

# Install dependencies
pip install -r requirements.txt

# Scaffold a new server
python -m sila_server_common.scaffold --name my_device --port 50062

# Run a server (example)
python -m temperature_controller --insecure --port 50052

# Run the web UI
python -m client_web_ui

# Validate a server
python -m sila_server_common.validate servers/my_device

# Deploy servers to target PCs via Ansible (run from WSL2)
cd deployment
ansible-playbook playbooks/deploy.yml -l venus_api     # full deploy
ansible-playbook playbooks/update.yml -l venus_api     # code update only
ansible-playbook playbooks/status.yml                  # fleet status
ansible-playbook playbooks/tailscale.yml               # install Tailscale VPN

# Run the deployment admin console
cd deployment && python -m admin_console               # http://localhost:5001
```

## AI Script Generation
- The global scripting engine (`/scripts`) has AI-assisted script generation via Gemini
- `lab` and `time` are pre-injected by the runtime preamble — scripts must NOT `import lab` or `import time`
- The AI system prompt receives full introspection from connected servers: command signatures with parameter names, types, descriptions, and response identifiers
- **FDL descriptions matter for AI quality** — the `<Description>` fields on commands, parameters, and responses are passed directly to the AI. Write clear, specific descriptions with expected formats, units, and valid ranges.

## Debugging Workflow
When debugging issues that affect multiple servers or shared infrastructure:
1. Fix the immediate issue in the code
2. Update `CREATING_SERVERS.md` if the fix reveals a convention or requirement that should be documented
3. Log the change in `CHANGELOG_DEBUGGING.md` (create if needed) so we can track what needs to be propagated to other servers
4. After a debugging session, review the changelog and apply fixes to all affected servers

## Important Notes
- The `sila2` package requires Python >= 3.10
- The `generated/` directories inside each server contain auto-generated code from FDL files -- do not edit directly
- The `feature_implementations/` directories contain the hand-written implementation code
- TLS is mandatory in SiLA 2 spec but we use `--insecure` for local dev convenience

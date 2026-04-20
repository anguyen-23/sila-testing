# SiLA 2 Server Development & Testing Platform

A development and testing platform for building [SiLA 2](https://sila-standard.com/) (Standardization in Lab Automation) instrument servers. Developers use this project to create, test, and validate instrument servers that connect to a production client application.

## Quick Start

```bash
# Activate the virtual environment
source .venv/Scripts/activate    # Git Bash
.venv\Scripts\activate.bat       # CMD

# Scaffold a new server
python -m sila_server_common.scaffold --name my_device --port 50062

# Run a server
python -m temperature_controller --insecure --port 50052 --verbose

# Run the test client web UI
python -m client_web_ui

# Validate a server for compliance
python -m sila_server_common.validate servers/my_device
```

## Creating a New Server

The scaffold tool generates a complete server package. You write four files:

1. **Device FDL** (`<Feature>.sila.xml`) — commands, properties, errors
2. **Device implementation** (`feature_implementations/<feature>_impl.py`) — business logic
3. **Custom WebUI** (`custom_ui.html`) — React + Babel CDN single-file UI
4. **Test suite** (`client_web_ui/test_suites/<name>.json`) — scripted and guided tests

Everything else (LockController, SimulationController, ScreenStreamer, MessagingClient, ServerLogProvider, ScriptRunner, WebUIProvider, UserManualProvider) is auto-registered by `BaseInstrumentServer` from the shared library.

See [`CREATING_SERVERS.md`](CREATING_SERVERS.md) for the full guide.

## Servers

| Server | Port | Description |
|--------|------|-------------|
| temperature_controller | 50052 | Simulated heating/cooling device |
| pump_controller | 50053 | Simulated liquid pump |
| plate_reader | 50054 | Simulated plate reader |
| multidrop_combi | 50055 | Thermo Multidrop Combi serial wrapper (pyserial) |
| venus_api | 50056 | Hamilton VENUS Web API wrapper (REST+SignalR) |
| barcode_scanner | 50057 | Datalogic barcode scanner serial wrapper (pyserial) |
| phenix_imager | 50058 | PerkinElmer Opera Phenix RCI wrapper (comtypes) |
| micronic_tube_scanner | 50059 | Micronic 2D tube scanner REST wrapper |
| xarm6 | 50060 | UFACTORY xArm 6 robotic arm (xArm Python SDK) |

## Running Servers

```bash
# Simulated servers (no hardware needed)
python -m temperature_controller --insecure --port 50052 --verbose
python -m pump_controller --insecure --port 50053 --verbose
python -m plate_reader --insecure --port 50054 --verbose

# Real instrument servers
python -m multidrop_combi --insecure --port 50055 --verbose
python -m venus_api --insecure --port 50056 --verbose --venus-url http://localhost:51745
python -m barcode_scanner --insecure --port 50057 --verbose
python -m phenix_imager --insecure --port 50058 --verbose
python -m micronic_tube_scanner --insecure --port 50059 --verbose
python -m xarm6 --insecure --port 50060 --verbose

# Test client web UI (connects to running servers)
python -m client_web_ui
```

All servers start in simulation mode by default. Use the SimulationController feature to switch to real mode.

## Architecture

```
Browser (React WebUI)  <-- SSE -->  Flask client_web_ui  <-- gRPC streaming -->  SiLA 2 Server
                                                                                      |
                                                                              Observable Properties
                                                                              (DeviceStatus JSON push)
```

Every server exposes a `DeviceStatus` observable property — a JSON blob carrying the full device state. The Flask test client bridges this to the browser via Server-Sent Events (SSE). The React WebUI renders state reactively with no polling.

## Project Structure

```
servers/                    # SiLA 2 server implementations (one per device)
packages/
  sila_server_common/       # Shared library: base server, feature factories, transport modules, scaffold, validator
client_web_ui/              # Flask test client: server discovery, command execution, SSE, test runner
deployment/                 # Ansible fleet deployment (playbooks, inventory, roles, admin console)
documentation/              # SiLA 2 specification PDFs and reference material
```

## Test Runner

The test runner (`/tests/<suite_name>` in the web UI) executes test suites defined as JSON files in `client_web_ui/test_suites/`. Three test types:

| Type | Description |
|------|-------------|
| **Scripted** | Fully automated — runs SiLA commands, checks responses, no user interaction |
| **Guided** | Semi-automated — runs SiLA commands with user interaction points (prompts for physical actions, confirmations for visual checks) |

Tests are tagged with `modes: ["simulation"]`, `["real"]`, or both. The runner filters by mode and tracks pass/fail/skip results.

## Key Tools

| Tool | Command |
|------|---------|
| Scaffold | `python -m sila_server_common.scaffold --name <name> --port <port>` |
| Validator | `python -m sila_server_common.validate servers/<name>` |
| Test Runner | Navigate to `/tests/<suite_name>` in the web UI |
| Deployment | `ansible-playbook playbooks/deploy.yml -l <server>` (from WSL2) |

## Tech Stack

- **Python 3.13+** with [`sila2[full]`](https://pypi.org/project/sila2/) (gRPC-based SiLA 2 framework)
- **Flask** for the test client web UI
- **React 18 + Babel CDN** for server WebUIs (no build step)
- **Ansible** for fleet deployment to Windows targets

## Documentation

- [`CREATING_SERVERS.md`](CREATING_SERVERS.md) — Full server creation guide (FDL reference, implementation patterns, WebUI patterns, testing)
- [`DEVELOPMENT_PLAN.md`](DEVELOPMENT_PLAN.md) — Standardization roadmap and status
- [`DEPLOY.md`](DEPLOY.md) — Server deployment guide
- [`CLAUDE.md`](CLAUDE.md) — AI assistant context for this codebase
- [`deployment/DEPLOYMENT.md`](deployment/DEPLOYMENT.md) — Ansible fleet management

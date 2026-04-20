# SiLA 2 Learning Project

A hands-on learning project for understanding [SiLA 2](https://sila-standard.com/) (Standardization in Lab Automation) through building simulated lab instrument servers and a universal web client.

**This is a personal learning project, not intended for production use.**

## What is SiLA 2?

SiLA 2 is a communication standard for lab automation devices. It defines how instruments (servers) expose their capabilities and how software (clients) interact with them, using gRPC over HTTP/2 with XML-based API contracts called Feature Definition Language (FDL).

## Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│                            Local Network                             │
│                                                                      │
│  ┌───────────────┐ ┌───────────────┐ ┌───────────────┐               │
│  │  Temperature   │ │  Pump         │ │  Plate Reader │               │
│  │  Controller    │ │  Controller   │ │               │               │
│  │  :50052        │ │  :50053       │ │  :50054       │               │
│  └───────┬───────┘ └───────┬───────┘ └───────┬───────┘               │
│          │                 │                 │                        │
│  ┌───────┴───────┐ ┌──────┴────────┐ ┌──────┴────────┐              │
│  │  Multidrop    │ │  Venus API    │ │  Barcode      │              │
│  │  Combi        │ │  Server       │ │  Scanner      │              │
│  │  :50055       │ │  :50056       │ │  :50057       │              │
│  └───────┬───────┘ └──────┬────────┘ └──────┬────────┘              │
│          │                │                 │                        │
│  ┌───────┴───────┐ ┌──────┴────────┐        │                       │
│  │  Phenix       │ │  Micronic     │        │                       │
│  │  Imager       │ │  Tube Scanner │        │                       │
│  │  :50058       │ │  :50059       │        │                       │
│  └───────┬───────┘ └──────┬────────┘        │                       │
│          │    gRPC         │    gRPC         │  gRPC                 │
│          └────────┬────────┴────────┬───────┘                       │
│                   │    Tailscale    │                                │
│            ┌──────┴─────────────────┴──────┐                        │
│            │       Client Web UI           │                        │
│            │       Flask App :5000         │                        │
│            │       Message Server :8765    │                        │
│            │  - Browse features/commands   │                        │
│            │  - Execute commands           │                        │
│            │  - View properties            │                        │
│            │  - Lock/unlock devices        │                        │
│            │  - Toggle simulation mode     │                        │
│            │  - Gemini AI chat assistant   │                        │
│            │  - MCP tool descriptions      │                        │
│            │  - Screen streaming viewer    │                        │
│            │  - Operator messaging (WS)    │                        │
│            │  - Test runner (JSON suites)  │                        │
│            └──────────────┬───────────────┘                        │
│                           │ Can also run on                         │
│                           │ Google Cloud Run                        │
└───────────────────────────┼──────────────────────────────────────────┘
                            │
                 ┌──────────┴──────────┐
                 │  Admin Console      │
                 │  Flask App :5001    │
                 │  - Fleet dashboard  │
                 │  - Deploy/update    │
                 │  - Live job output  │
                 │  - Setup wizards    │
                 └─────────────────────┘
```

## SiLA 2 Concepts Covered

| Concept | Where Demonstrated |
|---------|-------------------|
| Unobservable Commands | All servers (simple request/response) |
| Observable Commands | Temperature (SetTemperature), Plate Reader (ReadPlate), Multidrop (Dispense), Venus (LoadMethod, StartMethod) |
| Unobservable Properties | All servers (poll for current value) |
| Observable Properties | Temperature (CurrentTemperature live updates), Venus (RuntimeTrace), Multidrop v2 (DeviceStatus JSON, IsConnected, IsPrimed) |
| Defined Execution Errors | All servers (typed, named errors) |
| Intermediate Responses | Plate Reader (per-well data), Multidrop (column/row progress), Venus (progress %, status updates) |
| SimulationController | All servers (test without hardware) |
| LockController | Temperature, Barcode Scanner, Phenix, Venus, Micronic (exclusive device access) |
| Server Discovery | mDNS/DNS-SD zero-config networking |
| Binary Transfer | All servers (DisplayIcon property) |
| Feature Definition Language | `.sila.xml` files define every server's API contract |
| DeviceDescription (MCP) | Multidrop Combi, Venus API (rich text for LLM system prompts) |
| Wrapping Real APIs | Multidrop (RS232 serial), Venus (REST + SignalR), Barcode (serial STX/ETX), Phenix (COM/RCI), Micronic (REST) |
| Reusable Features | ScreenStreamer + MessagingClient on all servers |
| Win32 Screen Capture | ScreenStreamer (PrintWindow/BitBlt/desktop DC, JPEG streaming, Session 0 helper proxy) |
| WebSocket Messaging | MessagingClient (auto-reconnect, operator instructions, confirmations) |
| Tailscale VPN | Mesh VPN for Cloud Run to on-prem server connectivity |
| Cloud Run Deployment | Containerized web UI with Tailscale userspace networking |

## Servers

### Temperature Controller (`servers/temperature_controller/`)
Simulated heating/cooling device. Demonstrates observable commands with progress tracking, observable properties with live temperature updates, and device locking.

### Pump Controller (`servers/pump_controller/`)
Simulated syringe pump. Demonstrates prerequisite command patterns (must Prime before Dispense), volume tracking, and validation errors.

### Plate Reader (`servers/plate_reader/`)
Simulated microplate reader. Demonstrates long-running observable commands with per-well intermediate responses, CSV data export, and complex data types.

### Multidrop Combi (`servers/multidrop_combi/`)
Thermo Scientific Multidrop Combi reagent dispenser wrapper. Wraps the instrument's RS232 serial remote control protocol via `pyserial`. Includes a `DisplayIcon` binary property for client UI display.

### Multidrop Combi v2 (`servers/multidrop_combi_v2/`)
v2 reference implementation with observable properties for real-time state push, React + Babel CDN WebUI with SSE streaming, and serial robustness patterns (buffer drain, EAK error recovery). See [`CREATING_SERVERSv2.0.md`](CREATING_SERVERSv2.0.md) for the v2 architecture guide.

### Venus API (`servers/venus_api/`)
Hamilton VENUS Web API wrapper. Bridges the VENUS REST + SignalR v2 API to SiLA 2 with method loading (with async run-state polling), execution with progress tracking, pause/resume/abort, device and deck layout queries, and run data retrieval. Includes a `DeviceDescription` property for MCP/LLM integration. See [`servers/venus_api/DEPLOY.md`](servers/venus_api/DEPLOY.md) for deployment on an instrument PC.

### Barcode Scanner (`servers/barcode_scanner/`)
Datalogic barcode scanner wrapper. Wraps the instrument's RS232 serial protocol (STX/ETX framing) via `pyserial`. Includes trigger control, continuous scanning mode, and barcode type detection.

### Phenix Imager (`servers/phenix_imager/`)
PerkinElmer Opera Phenix high-content imager wrapper. Wraps the instrument's RCI (Remote Control Interface) COM automation via `comtypes`. Supports plate loading, imaging protocol execution, and status monitoring.

### Micronic Tube Scanner (`servers/micronic_tube_scanner/`)
Micronic 2D tube barcode scanner wrapper. Wraps the instrument's REST API via `requests`. Supports rack scanning, tube identification, and scan result retrieval.

### Cross-Server Reusable Features

Every server includes two reusable features that are identical across all servers:

- **ScreenStreamer** — Captures screenshots of any window on the server machine using Win32 API (PrintWindow/BitBlt with desktop DC fallback for elevated windows). Includes `ListWindows` to discover available windows, `StartCapture`/`StopCapture` for background frame capture, and `GetLatestFrame` to retrieve JPEG frames. When running as a Windows service (Session 0), delegates to the **Screen Capture Helper** — a lightweight HTTP server that runs in the user's interactive session (see [Deployment](deployment/DEPLOYMENT.md)).

- **MessagingClient** — Connects to the web UI's built-in message server via WebSocket to receive operator instructions. Supports `ConnectToMessageServer`, `DisconnectFromMessageServer`, and `ConfirmMessage` for message acknowledgment.

### Client Web UI (`client_web_ui/`)
A Flask web application that acts as a universal SiLA 2 client. Connects to any SiLA 2 server, introspects its features, and provides a UI for browsing properties, executing commands, managing locks, toggling simulation mode, viewing MCP tool descriptions, and chatting with a Gemini AI assistant that can interact with connected instruments. Includes a built-in message server (port 8765) for operator messaging via WebSocket. Also includes a **test runner** framework for automated and manual testing of SiLA servers using JSON test suite definitions.

## Quick Start

### Prerequisites
- Python 3.10+ (project uses 3.13)
- Git

### Setup

```bash
git clone <repo-url>
cd keyser-sila-testing

python -m venv .venv
source .venv/Scripts/activate    # Windows Git Bash
# or: .venv\Scripts\activate.bat  # Windows CMD

pip install -r requirements.txt
```

### Run Servers

Each server is a standalone Python package. Start them in separate terminals:

```bash
python -m temperature_controller --insecure --port 50052
python -m pump_controller --insecure --port 50053
python -m plate_reader --insecure --port 50054
python -m multidrop_combi --insecure --port 50055
python -m venus_api --insecure --simulation --port 50056
python -m barcode_scanner --insecure --port 50057
python -m phenix_imager --insecure --port 50058
python -m micronic_tube_scanner --insecure --port 50059
python -m multidrop_combi_v2 --insecure --port 50055
```

All servers start in simulation mode by default (except Venus API, which requires `--simulation` explicitly). Add `--verbose` for info-level logging.

### Run the Web UI

```bash
python -m client_web_ui
```

Open http://localhost:5000 to browse connected servers, view properties, and execute commands.

## Project Structure

```
├── servers/
│   ├── temperature_controller/     # Simulated heating/cooling device
│   │   ├── TemperatureController.sila.xml   # FDL (API contract)
│   │   ├── ScreenStreamer.sila.xml          # Reusable: Win32 screen capture
│   │   ├── MessagingClient.sila.xml        # Reusable: WebSocket messaging
│   │   └── temperature_controller/
│   │       ├── feature_implementations/     # Hand-written logic
│   │       ├── generated/                   # Auto-generated from FDL
│   │       ├── win32_capture.py             # Win32 screen capture module
│   │       └── messaging_transport.py       # WebSocket messaging module
│   ├── pump_controller/            # Simulated liquid pump
│   ├── plate_reader/               # Simulated microplate reader
│   ├── multidrop_combi/            # Serial protocol wrapper (pyserial)
│   ├── venus_api/                  # REST+SignalR wrapper (requests, signalrcore)
│   ├── barcode_scanner/            # Serial protocol wrapper (pyserial, STX/ETX)
│   ├── phenix_imager/              # COM/RCI protocol wrapper (comtypes)
│   ├── micronic_tube_scanner/      # REST API wrapper (requests)
│   └── multidrop_combi_v2/        # v2 reference: observable props, React WebUI, SSE
├── client_web_ui/                  # Flask web app
│   ├── app.py                      # Routes, introspection, command execution
│   ├── message_server.py           # Built-in messaging server (HTTP + WS)
│   ├── test_suites/                # JSON test suite definitions
│   └── templates/                  # Jinja2 templates (Bootstrap 5, test runner)
├── deployment/                     # Ansible deployment system
│   ├── DEPLOYMENT.md               # Setup guide and usage
│   ├── inventory/                  # Target PCs and credentials
│   ├── playbooks/                  # deploy, update, status, tailscale
│   ├── roles/
│   │   ├── sila_server/            # Reusable deploy role (Windows + Linux)
│   │   └── tailscale/              # Tailscale VPN install + auth role
│   ├── admin_console/              # Flask fleet management web app (port 5001)
│   └── screen_capture_helper/      # User-session helper for service-mode capture
├── Dockerfile                      # Cloud Run container (web UI + Tailscale)
├── entrypoint.sh                   # Container entrypoint (tailscaled + gunicorn)
├── documentation/                  # SiLA 2 spec PDFs, instrument manuals
├── requirements.txt                # Python dependencies
├── CLAUDE.md                       # Development conventions
├── CREATING_SERVERS.md             # Guide for generating new servers
└── Project Plan.md                 # Phase-by-phase development roadmap
```

### Server Package Anatomy

Each server follows the same pattern:

```
servers/<name>/
├── <Feature>.sila.xml              # FDL defining the SiLA feature
├── ScreenStreamer.sila.xml         # Reusable feature FDL
├── MessagingClient.sila.xml       # Reusable feature FDL
├── <name>/
│   ├── __main__.py                 # CLI entry point (typer)
│   ├── server.py                   # SilaServer subclass, registers features
│   ├── feature_implementations/    # YOUR code - implement the abstract methods
│   ├── generated/                  # DO NOT EDIT - auto-generated by sila2-codegen
│   ├── win32_capture.py            # Screen capture transport (shared across servers)
│   └── messaging_transport.py      # WebSocket messaging transport (shared across servers)
└── pyproject.toml
```

## Creating a New Server

See [`CREATING_SERVERS.md`](CREATING_SERVERS.md) for a step-by-step guide (v1 patterns), or [`CREATING_SERVERSv2.0.md`](CREATING_SERVERSv2.0.md) for v2 patterns (observable properties, React WebUI, SSE, test runner). The short version:

```bash
# 1. Write your FDL file (MyFeature.sila.xml)
# 2. Generate the package
sila2-codegen new-package -n my_server -o servers/my_server MyFeature.sila.xml

# 3. Implement the abstract methods in feature_implementations/
# 4. Run it
python -m my_server --insecure --port 50057
```

## Deployment

Servers are deployed to instrument PCs using [Ansible](https://www.ansible.com/) from a WSL2 control node. See [`deployment/DEPLOYMENT.md`](deployment/DEPLOYMENT.md) for full setup instructions.

```bash
# From WSL2, in the deployment/ directory:
ansible-playbook playbooks/deploy.yml -l venus_api        # deploy one server type
ansible-playbook playbooks/update.yml -l venus_api        # push code update
ansible-playbook playbooks/status.yml                      # fleet status report
ansible-playbook playbooks/tailscale.yml                   # install Tailscale VPN
```

Key components:
- **Ansible playbooks**: deploy (full install), update (code sync + restart), status (fleet report), tailscale (VPN setup)
- **Tailscale role**: Installs and authenticates Tailscale on Windows (winget) and Linux (official script) targets
- **Admin Console**: Flask web app (port 5001) for fleet management with dashboard, live job output, and setup wizards
- **Cloud Run**: Dockerfile + Tailscale for deploying the Client Web UI to Google Cloud Run
- **nssm**: Registers servers as Windows services (auto-start on boot)
- **Screen Capture Helper**: Runs in user session via scheduled task, proxies window capture to services in Session 0
- **Ansible Vault**: Encrypted credential storage for target PC authentication

### Admin Console

The deployment admin console provides a browser-based interface for managing the fleet:

```bash
cd deployment
pip install flask pyyaml
python -m admin_console
# Open http://localhost:5001
```

Features: fleet dashboard with host cards, one-click deploy/update/status per host, live ansible-playbook output streaming, and step-by-step wizards for Tailscale setup, Cloud Run deployment, and adding new hosts.

### Cloud Run

The Client Web UI can be deployed to Google Cloud Run with Tailscale for secure access to on-prem servers:

```bash
gcloud builds submit --tag gcr.io/YOUR_PROJECT/sila-web-ui
gcloud run deploy sila-web-ui \
  --image gcr.io/YOUR_PROJECT/sila-web-ui \
  --platform managed --region us-central1 \
  --allow-unauthenticated \
  --set-env-vars "TS_AUTHKEY=tskey-auth-...,GEMINI_API_KEY=..."
```

## Dependencies

| Package | Purpose |
|---------|---------|
| `sila2[full]` | SiLA 2 framework (server, client, codegen, gRPC) |
| `flask` | Client web UI |
| `typer` | CLI argument parsing for servers |
| `pyserial` | Serial communication (Multidrop Combi, Barcode Scanner) |
| `requests` | HTTP REST client (Venus API, Micronic Tube Scanner) |
| `signalrcore` | SignalR real-time client (Venus API) |
| `aiohttp` | Async HTTP + WebSocket server (message server) |
| `google-genai` | Gemini AI chat integration (Web UI) |
| `python-dotenv` | Environment variable loading (.env for API keys) |
| `pywin32` | Win32 API for screen capture (ScreenStreamer) |
| `opencv-python` | Image encoding for screen capture |
| `numpy` | Array operations for screen capture |
| `Pillow` | Image generation for simulation mode placeholders |

## Phase Status

- **Phase 1** - Foundation (Temperature Controller) - Complete
- **Phase 2** - Core Concepts (SimulationController, LockController, errors) - Complete
- **Phase 3** - More Devices (Pump Controller, Plate Reader) - Complete
- **Phase 4** - Web UI (Flask client with feature browsing, Gemini chat, MCP tools) - Complete
- **Phase 4.5** - Real Hardware (Multidrop Combi, Venus API, Barcode Scanner, Phenix Imager, Micronic Tube Scanner, DeviceDescription) - Complete
- **Phase 4.75** - Reusable Features (ScreenStreamer + MessagingClient on all 8 servers) - Complete
- **Phase 5** - Deployment (Ansible fleet management, Tailscale VPN, Cloud Run, admin console) - In progress
- **Phase 6** - Network & Advanced (Raspberry Pi deployment, TLS) - Not started

## Reference

- [SiLA 2 Standard](https://sila-standard.com/)
- [Python SiLA 2 SDK](https://gitlab.com/SiLA2/sila_python) ([docs](https://sila2.gitlab.io/sila_python/))
- [PyPI: sila2](https://pypi.org/project/sila2/)
- [SiLA Standard Features](https://gitlab.com/SiLA2/sila_base)

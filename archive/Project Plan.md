# SiLA 2 Learning Project - Project Plan

> **Purpose**: This is a personal learning project to understand how SiLA 2 (Standardization
> in Lab Automation) works. It is NOT intended for production use or end-user utility. The
> emphasis is on exploring and understanding SiLA 2 concepts through hands-on implementation.

## Goals

Learn and demonstrate understanding of:
1. **SiLA 2 communication model** - gRPC-based client-server architecture over HTTP/2
2. **Feature Definition Language (FDL)** - XML-based API contracts (`.sila.xml` files)
3. **Commands** - Both Unobservable (simple request/response) and Observable (long-running with progress)
4. **Properties** - Both Unobservable (poll) and Observable (subscribe to changes)
5. **Error handling** - Defined Execution Errors, Undefined Execution Errors, Validation Errors, Framework Errors
6. **Device locking** - LockController for multi-user/multi-client access control
7. **Simulation mode** - SimulationController for testing without hardware
8. **Server discovery** - mDNS/DNS-SD zero-config networking
9. **Metadata** - Cross-cutting concerns via SiLA Client Metadata
10. **Threading model** - How gRPC threading, observable commands, and subscriptions work
11. **Network deployment** - Running servers on Raspberry Pis on a local network

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                       Local Network                           │
│                                                               │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐        │
│  │  Temp Server  │  │  Pump Server │  │ Plate Reader │        │
│  │  (Pi or PC)   │  │  (Pi or PC)  │  │  (Pi or PC)  │        │
│  │  :50052       │  │  :50053      │  │  :50054      │        │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘        │
│         │                 │                 │                  │
│  ┌──────┴───────┐  ┌─────┴────────┐        │                  │
│  │  Multidrop   │  │  Venus API   │        │                  │
│  │  Combi       │  │  Server      │        │                  │
│  │  :50055      │  │  :50056      │        │                  │
│  └──────┬───────┘  └─────┬────────┘        │                  │
│         │    gRPC        │    gRPC         │  gRPC            │
│         └────────┬───────┴────────┬───────┘                   │
│                  │                │                            │
│           ┌──────┴────────────────┴──────┐                    │
│           │      Client Web UI           │                    │
│           │      Flask App :5000         │                    │
│           │  - Discover servers (mDNS)   │                    │
│           │  - Browse features/commands  │                    │
│           │  - Execute commands          │                    │
│           │  - Subscribe to properties   │                    │
│           │  - Lock/unlock devices       │                    │
│           │  - Toggle simulation mode    │                    │
│           │  - Gemini AI chat assistant  │                    │
│           │  - MCP tool descriptions     │                    │
│           └──────────────────────────────┘                    │
└──────────────────────────────────────────────────────────────┘
```

## Servers

### 1. Temperature Controller (`servers/temperature_controller/`)
Simulates a heating/cooling device (e.g., a hot plate or incubator).

**Features to implement:**
| Feature | Type | Concepts Demonstrated |
|---------|------|----------------------|
| `TemperatureController` | Custom | Observable Command (SetTemperature with progress), Observable Property (CurrentTemperature), Defined Errors (OverTemperature, HeaterFault) |
| `SiLAService` | Standard | Mandatory - server identity and feature discovery |
| `SimulationController` | Standard | Toggle simulation mode |
| `LockController` | Standard | Device locking for exclusive access |

**Learning focus**: Observable commands with progress tracking, observable properties with live updates, simulation vs. real behavior branching.

### 2. Pump Controller (`servers/pump_controller/`)
Simulates a syringe or peristaltic pump for liquid handling.

**Features to implement:**
| Feature | Type | Concepts Demonstrated |
|---------|------|----------------------|
| `PumpController` | Custom | Unobservable Command (Aspirate, Dispense), Observable Command (PrimePump), Properties (CurrentVolume, MaxVolume), Defined Errors (InsufficientVolume, PumpStall) |
| `SiLAService` | Standard | Mandatory |
| `SimulationController` | Standard | Simulation mode |
| `LockController` | Standard | Device locking |

**Learning focus**: Multiple commands on one feature, validation errors (negative volumes), state management (tracking current volume).

### 3. Plate Reader (`servers/plate_reader/`)
Simulates a microplate reader that measures absorbance/fluorescence.

**Features to implement:**
| Feature | Type | Concepts Demonstrated |
|---------|------|----------------------|
| `PlateReader` | Custom | Observable Command (ReadPlate - long-running with intermediate per-well results), Unobservable Command (SetWavelength), Properties |
| `MeasurementProvider` | Custom | Unobservable Property (LastMeasurement), custom data types (Structure for plate data) |
| `SiLAService` | Standard | Mandatory |
| `SimulationController` | Standard | Simulation mode |
| `LockController` | Standard | Device locking |

**Learning focus**: Intermediate responses (per-well data during plate read), custom/complex data types (structures, lists), binary transfer (exporting raw data).

### 4. Multidrop Combi (`servers/multidrop_combi/`)
Thermo Scientific Multidrop Combi reagent dispenser wrapper. Wraps the instrument's RS232 serial remote control protocol via `pyserial`.

**Features:** MultidropCombi (Dispense, Prime, GetStatus, etc.), SimulationController
**Learning focus**: Wrapping real hardware serial protocols as SiLA 2 features, Binary Transfer (DisplayIcon property), DeviceDescription for MCP/LLM integration.

### 5. Venus API (`servers/venus_api/`)
Hamilton VENUS Web API wrapper. Bridges the VENUS REST + SignalR API (v2) to SiLA 2 with method loading, execution with progress tracking, pause/resume/abort, device queries, and run data retrieval.

**Features:** VenusMethodExecutor (LoadMethod, StartMethod, PauseMethod, ResumeMethod, AbortMethod, UnloadMethod, GetDevices, GetRuntimeDevices, GetDeckLayout, GetLoadedMethod, GetRunState, GetCurrentRunData, GetRuntimeData, GetDetailedRunData), SimulationController
**Learning focus**: Wrapping REST+SignalR APIs as SiLA 2 features, async method loading with run-state polling, DeviceDescription for MCP/LLM integration. See [`servers/venus_api/DEPLOY.md`](servers/venus_api/DEPLOY.md) for deployment.

## Client Web UI (`client_web_ui/`)

A Flask web application that acts as a universal SiLA 2 client.

**Pages/Features:**
| Page | Description |
|------|-------------|
| **Dashboard** | Discover and list all SiLA servers on the network via mDNS |
| **Server Detail** | Show server info, list all features, properties, commands |
| **Command Executor** | Form to fill parameters and execute any command; show progress for observable commands |
| **Property Viewer** | Live-updating view of observable properties via WebSocket/SSE |
| **Lock Manager** | Lock/unlock servers, show lock status |
| **Simulation Toggle** | Enable/disable simulation mode per server |
| **Error Explorer** | Deliberately trigger various error types to see how they propagate |

**Tech stack**: Flask + Jinja2 templates, minimal JavaScript for live updates (SSE or polling), Bootstrap for styling.

## Implementation Phases

### Phase 1: Foundation
- [x] Project setup (venv, git, project structure)
- [x] Install `sila2[full]` and verify codegen works
- [x] Create FDL files for TemperatureController feature
- [x] Generate and implement the Temperature Controller server
- [x] Write a minimal script client to test communication

### Phase 2: Core Concepts
- [x] Add Observable Properties (CurrentTemperature with live updates)
- [x] Add Observable Commands (SetTemperature with progress)
- [x] Implement Defined Execution Errors
- [x] Add SimulationController support
- [x] Add LockController support
- [x] Test error handling (validation, defined, undefined errors)

### Phase 3: More Devices
- [x] Create and implement Pump Controller server
- [x] Create and implement Plate Reader server (with intermediate responses)
- [x] Test multi-server discovery

### Phase 4: Web UI
- [x] Flask app skeleton with server discovery
- [x] Server detail page with feature browsing
- [x] Command execution UI
- [x] Live property subscriptions (auto-read on page load)
- [x] Lock management UI
- [x] Simulation toggle UI
- [x] MCP tools display (DeviceDescription-based)
- [x] Gemini AI chat assistant for instrument interaction
- [x] Client reconnect button for refreshing cached feature lists

### Phase 4.5: Real Hardware Integration
- [x] Multidrop Combi server (serial protocol wrapper)
- [x] Venus API server (REST+SignalR wrapper, v2 endpoints)
- [x] DeviceDescription property for MCP/LLM system prompts
- [x] Deployment guide for instrument PCs (DEPLOY.md)

### Phase 4.8: v2 Architecture & Test Runner
- [x] Observable properties for real-time state push (DeviceStatus JSON, IsConnected, IsPrimed)
- [x] React + Babel CDN WebUI with SSE streaming (single HTML file, no build step)
- [x] Multidrop Combi v2 reference implementation (`servers/multidrop_combi_v2/`)
- [x] Serial communication robustness patterns (buffer drain, EAK error recovery, per-command timeouts)
- [x] Test runner framework (JSON test suites, scripted + manual tests, mode filtering)
- [x] Test suite for Multidrop Combi v2 (75 tests: 21 sim-only, 36 real-only, 18 both)
- [x] Command parameter ordering fix (definition order, not alphabetical)
- [x] WebUI improvements (error recovery modal, unit conversion, settings persistence, plate map)

### Phase 5: Deployment & Networking
- [x] Ansible fleet deployment (Windows via WinRM + nssm, Linux via SSH + systemd)
- [x] Screen capture helper for service-mode ScreenStreamer (Session 0 proxy)
- [x] Tailscale VPN role for secure mesh networking across fleet
- [x] Cloud Run deployment (Dockerfile + Tailscale userspace networking)
- [x] Deployment admin console (Flask web app with dashboard, live output, wizards)
- [ ] Deploy servers to Raspberry Pis
- [ ] Test cross-machine discovery and communication
- [ ] Explore TLS certificate setup
- [ ] Stress test with multiple concurrent clients
- [ ] Document learnings and gotchas

## Reference Material
- `documentation/` folder contains SiLA 2 specification PDFs (Part A: Core, Part B: Mapping)
- Python SDK: https://gitlab.com/SiLA2/sila_python
- SDK docs: https://sila2.gitlab.io/sila_python/
- PyPI: `pip install sila2[full]`
- SiLA standard features repo: https://gitlab.com/SiLA2/sila_base

## Notes
- The `sila2` PyPI package is in maintenance mode. The maintainers point to
  https://gitlab.com/unitelabs/sila2/sila-python as a more actively developed fork,
  but we use the original for learning since it has better documentation.
- Python 3.10+ is required by the sila2 package; this project uses 3.13.
- All servers run with `--insecure` (no TLS) for local development convenience.
  TLS is mandatory per the SiLA 2 spec but adds complexity we defer to Phase 5.

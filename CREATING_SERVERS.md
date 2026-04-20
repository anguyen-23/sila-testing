# How to Create a New SiLA 2 Instrument Server

This document is for Claude (or a developer using Claude) to generate a new SiLA 2 instrument server. The process is scaffold-driven — most boilerplate is handled automatically. You write four files: the device FDL, the device feature implementation, the custom WebUI, and the test suite.

## Prerequisites

- Python 3.10+ with `sila2[full]` installed
- `sila_server_common` installed (`pip install -e packages/sila_server_common`)
- Virtual environment activated (`source .venv/Scripts/activate`)

## Input Required from User

1. **Device name** (e.g., "Centrifuge", "Vortex Mixer", "Liquid Handler")
2. **Port number** (next available in sequence: 50052, 50053, ...)
3. **Commands** with parameters, responses, and whether they are observable
4. **Properties** with types and whether they are observable
5. **Errors** that commands can raise
6. **Communication protocol** (serial, REST API, SDK, etc.)

## Quick Start (6 Steps)

### Step 1: Scaffold the Server

```bash
source .venv/Scripts/activate
python -m sila_server_common.scaffold --name <snake_case_name> --port <PORT>
```

This generates a complete server package at `servers/<name>/` with all standard features, placeholder FDL, placeholder implementation, and placeholder WebUI.

### Step 2: Define the Device FDL

Edit `servers/<name>/<FeatureName>.sila.xml` — replace the TODO placeholders with your device's commands, properties, and errors.

The scaffold pre-includes three required properties:
- `DeviceStatus` (Observable String) — JSON blob that drives the WebUI via SSE
- `DisplayIcon` (Binary) — PNG icon for client UIs
- `DeviceDescription` (String) — Rich text for LLM/MCP system prompts

See [FDL Reference](#fdl-reference) below for data types, command patterns, and error declarations.

### Step 3: Run Code Generation

The scaffold prints the exact command. Run it:

```bash
sila2-codegen new-package \
  -n <snake_case_name> \
  -o servers/<snake_case_name> \
  --lock-controller \
  servers/<snake_case_name>/<FeatureName>.sila.xml \
  servers/<snake_case_name>/SimulationController.sila.xml \
  servers/<snake_case_name>/ScreenStreamer.sila.xml \
  servers/<snake_case_name>/MessagingClient.sila.xml \
  servers/<snake_case_name>/WebUIProvider.sila.xml \
  servers/<snake_case_name>/UserManualProvider.sila.xml \
  servers/<snake_case_name>/ServerLogProvider.sila.xml \
  servers/<snake_case_name>/ScriptRunner.sila.xml
```

**Important:** The codegen overwrites `server.py`, `__init__.py`, and `__main__.py`. After running codegen, restore the scaffold versions:

```bash
git checkout servers/<snake_case_name>/<snake_case_name>/server.py
git checkout servers/<snake_case_name>/<snake_case_name>/__init__.py
git checkout servers/<snake_case_name>/<snake_case_name>/__main__.py
```

Or, if not using git, save copies before running codegen and restore them after.

### Step 4: Implement the Device Feature

Edit `servers/<name>/<name>/feature_implementations/<featurename>_impl.py` — the scaffold has TODO markers showing exactly where to add your code.

Key patterns:
- Every command should call `self._push_device_status("Activity description")` after execution
- Support both simulation and real modes via `self._simulation_mode`
- Raise Defined Execution Errors for invalid state (e.g., "not connected")

See [Implementation Patterns](#implementation-patterns) below.

### Step 5: Build the WebUI and Test

Edit `servers/<name>/<name>/custom_ui.html` — the scaffold provides a working React + SSE skeleton.

Install and run:
```bash
pip install -e servers/<snake_case_name>
python -m <snake_case_name> --insecure --port <PORT> --verbose
```

Validate compliance:
```bash
python -m sila_server_common.validate servers/<snake_case_name>
```

### Step 6: Create a Test Suite

Create `client_web_ui/test_suites/<snake_case_name>.json` with scripted tests for simulation mode and guided tests for real hardware. Run the suite at `/tests/<snake_case_name>` in the web UI.

See the [Testing](#testing) section below for the full test suite format, step DSL reference, and recommended categories.

---

## Architecture Overview

```
Browser (React WebUI in custom_ui.html)
    |
    | EventSource (SSE)
    v
Flask client_web_ui (/api/sse/<host>/<port>/<feature>/DeviceStatus)
    |
    | gRPC streaming (observable property subscription)
    v
SiLA 2 Server (gRPC)
    |
    | update_DeviceStatus(json) <-- called after every command
    v
Observable Property subscribers (SSE, SiLAPlugin, any SiLA client)
```

### What You Write vs What's Provided

| You Write | Provided by `sila_server_common` |
|-----------|----------------------------------|
| Device FDL (`<Feature>.sila.xml`) | 7 standard feature FDLs |
| Device implementation (`<feature>_impl.py`) | BaseInstrumentServer (auto-registers 8 standard features) |
| Custom WebUI (`custom_ui.html`) | Shared CLI, logging, transport modules |
| Test suite (`test_suites/<name>.json`) | Test runner UI (React app at `/tests/<name>`) |
| | LockController, SimulationController, ScreenStreamer |
| | MessagingClient, WebUIProvider, UserManualProvider |
| | ServerLogProvider, ScriptRunner |

### Standard Features (Auto-Registered)

`BaseInstrumentServer` automatically registers these features — you do NOT need to write implementations for them:

| Feature | Purpose |
|---------|---------|
| LockController | Device locking with timeout (sila2 built-in) |
| SimulationController | Toggle simulation/real mode |
| ScreenStreamer | Win32 window capture with Session 0 helper proxy. Persists selected window title to `screen_capture.json` and auto-restores on restart. |
| MessagingClient | WebSocket lab messaging |
| WebUIProvider | Serves `custom_ui.html` as a SiLA property |
| UserManualProvider | Serves `user_manual.pdf` + extracted text for LLM |
| ServerLogProvider | Structured SQLite logging with SiLA query interface |
| ScriptRunner | Per-server Python automation scripts |

### Optional Features

These features are **not** registered automatically. Servers opt in by adding them to `server.py`:

| Feature | Purpose |
|---------|---------|
| CameraStreamProvider | IP/USB camera streaming (RTSP/HTTP/webcam via OpenCV) |

**Adding CameraStreamProvider to an existing server:**

1. Copy the FDL: `cp packages/sila_server_common/sila_server_common/fdl/CameraStreamProvider.sila.xml servers/<name>/`
2. Re-run codegen with the new FDL file appended
3. Register in `server.py`:
   ```python
   import importlib
   from sila_server_common.feature_implementations.camerastreamprovider_impl import create_camerastreamprovider_impl
   from sila_server_common.transports.camera_capture import load_camera_config

   # In __init__:
   csp_gen = importlib.import_module(f"{self._server_package}.generated.camerastreamprovider")
   CameraStreamProviderImpl = create_camerastreamprovider_impl(csp_gen)
   self.camerastreamprovider = CameraStreamProviderImpl(self)
   self.set_feature_implementation(csp_gen.CameraStreamProviderFeature, self.camerastreamprovider)

   # In on_simulation_mode_changed:
   self.camerastreamprovider._simulation_mode = simulation_mode
   ```
4. Create `camera.json` in the server root directory:
   ```json
   {
       "source": "rtsp://192.168.1.3:8554/profile0",
       "type": "ip",
       "auto_start": true,
       "jpeg_quality": 80,
       "fps": 15
   }
   ```
5. For auto-start, override `start_insecure`/`start` to call `_auto_start_camera()` after super.

**Scaffold shortcut:** Use `--camera` flag when scaffolding a new server:
```bash
python -m sila_server_common.scaffold --name my_device --port 50062 --camera
```

### Server Structure (After Scaffold + Codegen)

```
servers/<name>/
├── <FeatureName>.sila.xml          # YOUR device FDL
├── SimulationController.sila.xml   # Standard (from sila_server_common)
├── ScreenStreamer.sila.xml         # Standard
├── MessagingClient.sila.xml       # Standard
├── WebUIProvider.sila.xml         # Standard
├── UserManualProvider.sila.xml    # Standard
├── ServerLogProvider.sila.xml     # Standard
├── ScriptRunner.sila.xml          # Standard
├── pyproject.toml
├── deploy.bat
├── start_server.bat
└── <name>/
    ├── __init__.py                # Exports Server class
    ├── __main__.py                # 5 lines — uses create_main()
    ├── server.py                  # Subclasses BaseInstrumentServer
    ├── custom_ui.html             # YOUR React WebUI
    ├── icon.png                   # YOUR device icon
    ├── user_manual.pdf            # YOUR device manual (optional)
    ├── py.typed
    ├── feature_implementations/
    │   ├── __init__.py
    │   └── <featurename>_impl.py  # YOUR device implementation
    └── generated/                 # Auto-generated by sila2-codegen (DO NOT EDIT)
        ├── __init__.py
        ├── client.py
        ├── <featurename>/
        ├── lockcontroller/
        ├── simulationcontroller/
        ├── screenstreamer/
        ├── messagingclient/
        ├── webuiprovider/
        ├── usermanualprovider/
        ├── serverlogprovider/
        └── scriptrunner/
```

---

## FDL Reference

### Data Types

```xml
<!-- Basic types -->
<DataType><Basic>Boolean</Basic></DataType>
<DataType><Basic>Integer</Basic></DataType>
<DataType><Basic>Real</Basic></DataType>
<DataType><Basic>String</Basic></DataType>
<DataType><Basic>Binary</Basic></DataType>

<!-- Constrained numeric (min/max) -->
<DataType>
    <Constrained>
        <DataType><Basic>Real</Basic></DataType>
        <Constraints>
            <MinimalInclusive>0</MinimalInclusive>
            <MaximalInclusive>100</MaximalInclusive>
        </Constraints>
    </Constrained>
</DataType>

<!-- Use MinimalExclusive / MaximalExclusive for exclusive bounds -->

<!-- Enum-like (allowed values) -->
<DataType>
    <Constrained>
        <DataType><Basic>Integer</Basic></DataType>
        <Constraints>
            <Set>
                <Value>24</Value>
                <Value>96</Value>
                <Value>384</Value>
            </Set>
        </Constraints>
    </Constrained>
</DataType>

<!-- List type -->
<DataType>
    <List>
        <DataType><Basic>Integer</Basic></DataType>
    </List>
</DataType>

<!-- With SI units (e.g., degrees Celsius) -->
<DataType>
    <Constrained>
        <DataType><Basic>Real</Basic></DataType>
        <Constraints>
            <Unit>
                <Label>degC</Label>
                <Factor>1</Factor>
                <Offset>273.15</Offset>
                <UnitComponent>
                    <SIUnit>Kelvin</SIUnit>
                    <Exponent>1</Exponent>
                </UnitComponent>
            </Unit>
            <MinimalInclusive>0</MinimalInclusive>
            <MaximalInclusive>200</MaximalInclusive>
        </Constraints>
    </Constrained>
</DataType>
```

### Command Patterns

> **Important:** The `<Description>` fields on commands, parameters, and responses are surfaced to the AI script generator (Gemini). Write clear, specific descriptions — they directly affect the quality of AI-generated automation scripts. Include expected value formats, units, and valid ranges in parameter descriptions (e.g., "Speed 1-5 where 1=slowest", "Volume in µL, range 1-1000").

**Unobservable command** (completes immediately):
```xml
<Command>
    <Identifier>DoSomething</Identifier>
    <DisplayName>Do Something</DisplayName>
    <Description>What this command does.</Description>
    <Observable>No</Observable>
    <Parameter>
        <Identifier>ParamName</Identifier>
        <DisplayName>Param Name</DisplayName>
        <Description>What this parameter is.</Description>
        <DataType><Basic>String</Basic></DataType>
    </Parameter>
    <Response>
        <Identifier>ResultValue</Identifier>
        <DisplayName>Result Value</DisplayName>
        <Description>What is returned.</Description>
        <DataType><Basic>String</Basic></DataType>
    </Response>
    <DefinedExecutionErrors>
        <Identifier>SomeError</Identifier>
    </DefinedExecutionErrors>
</Command>
```

**Observable command** (long-running with progress):
```xml
<Command>
    <Identifier>LongTask</Identifier>
    <DisplayName>Long Task</DisplayName>
    <Description>A task that takes time and reports progress.</Description>
    <Observable>Yes</Observable>
    <Parameter>
        <Identifier>Duration</Identifier>
        <DisplayName>Duration</DisplayName>
        <Description>How long to run.</Description>
        <DataType><Basic>Real</Basic></DataType>
    </Parameter>
    <!-- IMPORTANT: Response MUST come BEFORE IntermediateResponse (SiLA schema order) -->
    <Response>
        <Identifier>FinalResult</Identifier>
        <DisplayName>Final Result</DisplayName>
        <Description>The result when complete.</Description>
        <DataType><Basic>String</Basic></DataType>
    </Response>
    <IntermediateResponse>
        <Identifier>ProgressInfo</Identifier>
        <DisplayName>Progress Info</DisplayName>
        <Description>Periodic update during execution.</Description>
        <DataType><Basic>String</Basic></DataType>
    </IntermediateResponse>
</Command>
```

### Property Patterns

```xml
<!-- Unobservable: client must poll -->
<Property>
    <Identifier>SomeValue</Identifier>
    <DisplayName>Some Value</DisplayName>
    <Description>A readable value.</Description>
    <Observable>No</Observable>
    <DataType><Basic>Real</Basic></DataType>
</Property>

<!-- Observable: server pushes updates to subscribers -->
<Property>
    <Identifier>IsConnected</Identifier>
    <DisplayName>Is Connected</DisplayName>
    <Description>Whether the instrument is connected.</Description>
    <Observable>Yes</Observable>
    <DataType><Basic>Boolean</Basic></DataType>
</Property>
```

### Error Declarations

Errors are declared at the Feature level (after all Commands and Properties) and referenced by commands:

```xml
<!-- Declaration (SINGULAR tag, at Feature level) -->
<DefinedExecutionError>
    <Identifier>NotConnected</Identifier>
    <DisplayName>Not Connected</DisplayName>
    <Description>The instrument is not connected.</Description>
</DefinedExecutionError>

<!-- Reference inside a command (PLURAL wrapper tag) -->
<DefinedExecutionErrors>
    <Identifier>NotConnected</Identifier>
    <Identifier>InvalidParameter</Identifier>
</DefinedExecutionErrors>
```

### Required Properties in Device FDL

Every device FDL MUST include these three properties:

```xml
<!-- Drives the WebUI via SSE — push updates after every command -->
<Property>
    <Identifier>DeviceStatus</Identifier>
    <DisplayName>Device Status</DisplayName>
    <Description>Current device status as JSON (for SSE streaming to WebUI).</Description>
    <Observable>Yes</Observable>
    <DataType><Basic>String</Basic></DataType>
</Property>

<!-- PNG icon for client UIs -->
<Property>
    <Identifier>DisplayIcon</Identifier>
    <DisplayName>Display Icon</DisplayName>
    <Description>Icon for the device.</Description>
    <Observable>No</Observable>
    <DataType><Basic>Binary</Basic></DataType>
</Property>

<!-- Rich text for LLM/MCP system prompts -->
<Property>
    <Identifier>DeviceDescription</Identifier>
    <DisplayName>Device Description</DisplayName>
    <Description>Rich text description of device capabilities.</Description>
    <Observable>No</Observable>
    <DataType><Basic>String</Basic></DataType>
</Property>
```

---

## Implementation Patterns

### Device Feature Implementation

The scaffold generates a placeholder. Key things to implement:

```python
class MyDeviceImpl(MyDeviceBase):
    def __init__(self, parent_server: Server) -> None:
        super().__init__(parent_server=parent_server)
        self._simulation_mode: bool = True
        self._activity_log: list[str] = []
        # Your device state here

    def start(self) -> None:
        super().start()
        # Push initial values for all observable properties
        self.update_IsConnected(False)
        self._push_device_status()

    def _push_device_status(self, activity: str | None = None) -> None:
        """Push full device state to WebUI via SSE. Call after every command."""
        if activity:
            ts = time.strftime("%H:%M:%S")
            self._activity_log.append(f"[{ts}] {activity}")
            if len(self._activity_log) > 100:
                self._activity_log = self._activity_log[-100:]

        status = {
            "simulationMode": self._simulation_mode,
            "isConnected": self._connected,
            # ... all your state fields
            "activityLog": self._activity_log[-50:],
        }
        self.update_DeviceStatus(json.dumps(status))
```

### Unobservable Property Getter

```python
def get_DisplayIcon(self, *, metadata: MetadataDict) -> bytes:
    return Path(__file__).parent.parent / "icon.png").read_bytes()
```

### Observable Property (No Getter — Push Updates)

```python
def start(self) -> None:
    super().start()
    self.update_IsConnected(False)  # Push initial value

# Later, when state changes:
self.update_IsConnected(True)
```

### Unobservable Command

```python
def Connect(self, ConnectionString: str, *, metadata: MetadataDict) -> Connect_Responses:
    logger.info("Connect: %s, simulation=%s", ConnectionString, self._simulation_mode)

    if self._simulation_mode:
        self._connected = True
        self.update_IsConnected(True)
        self._push_device_status(f"Connected to {ConnectionString} (simulated)")
        return Connect_Responses(InstrumentName="Simulated Device")

    # Real hardware logic
    try:
        self._transport.connect(ConnectionString)
    except Exception as e:
        raise ConnectionFailed(str(e))

    self._connected = True
    self.update_IsConnected(True)
    self._push_device_status(f"Connected to {ConnectionString}")
    return Connect_Responses(InstrumentName=self._transport.instrument_name)
```

### Observable Command (Long-Running with Progress)

```python
def RunProcess(
    self,
    Duration: float,
    *,
    metadata: MetadataDict,
    instance: ObservableCommandInstanceWithIntermediateResponses[RunProcess_IntermediateResponses],
) -> RunProcess_Responses:
    # 1. MUST call begin_execution() first
    instance.begin_execution()
    instance.estimated_remaining_time = timedelta(seconds=Duration)

    # 2. Loop with progress updates
    start = time.time()
    while time.time() - start < Duration:
        elapsed = time.time() - start
        instance.progress = elapsed / Duration  # 0.0 to 1.0 (NOT 0 to 100!)
        instance.estimated_remaining_time = timedelta(seconds=Duration - elapsed)
        instance.send_intermediate_response(
            RunProcess_IntermediateResponses(StatusMessage=f"Running... {elapsed:.0f}s")
        )
        time.sleep(0.5)

    # 3. Return final response
    self._push_device_status("Process complete")
    return RunProcess_Responses(Result="Done")
```

### Raising Errors

```python
if not self._connected:
    raise NotConnected("Must connect before running commands")
```

### Simulation Mode Callback

In `server.py`, the scaffold generates `on_simulation_mode_changed()`. Add your device-specific cleanup:

```python
def on_simulation_mode_changed(self, simulation_mode: bool) -> None:
    super().on_simulation_mode_changed(simulation_mode)
    self.mydevice._simulation_mode = simulation_mode
    # Disconnect real hardware if switching to simulation
    if simulation_mode and self.mydevice._transport.is_connected:
        self.mydevice._transport.disconnect()
    self.mydevice._connected = False
    self.mydevice.update_IsConnected(False)
    self.mydevice._push_device_status(
        "Entered simulation mode" if simulation_mode else "Entered real mode"
    )
```

### Structured Logging

Add structured `extra` fields to log calls for richer ServerLogProvider queries:

```python
logger.info("Connect: port=%s", port, extra={"category": "command", "command_name": "Connect"})
logger.debug("TX: %r", cmd, extra={"category": "serial", "direction": "tx"})
logger.info("Entering simulation mode", extra={"category": "state_change"})
```

To add device-specific feature names to the log handler's mapping, pass a `feature_map` when setting up logging. The `create_main()` function handles this — the default map covers all standard features. If you want to add device-specific mappings, customize `structured_logging.py`'s `DEFAULT_FEATURE_MAP` by adding entries at server startup:

```python
from sila_server_common.transports.structured_logging import DEFAULT_FEATURE_MAP
DEFAULT_FEATURE_MAP["mydevice_impl"] = "MyDevice"
DEFAULT_FEATURE_MAP["my_transport"] = "MyTransport"
```

---

## WebUI Patterns

### Core Structure (React + Babel CDN)

```html
<script src="https://unpkg.com/react@18/umd/react.production.min.js" crossorigin></script>
<script src="https://unpkg.com/react-dom@18/umd/react-dom.production.min.js" crossorigin></script>
<script src="https://unpkg.com/@babel/standalone/babel.min.js"></script>

<script type="text/babel" data-type="module">
const { useState, useEffect, useRef, useCallback } = React;

// Extract SiLA server host/port from iframe URL path
const _urlParts = window.location.pathname.split('/');
const SILA_HOST = _urlParts[3] || 'localhost';
const SILA_PORT = _urlParts[4] || '50052';
const API_BASE = `${window.location.origin}/api`;
const FEATURE_ID = 'MyDevice';
```

### SSE Hook (Real-Time State from Server)

```javascript
function useDeviceStatus() {
  const [status, setStatus] = useState({ simulationMode: true, activityLog: [] });
  const [sseConnected, setSseConnected] = useState(false);

  useEffect(() => {
    const url = `${API_BASE}/sse/${SILA_HOST}/${SILA_PORT}/${FEATURE_ID}/DeviceStatus`;
    const es = new EventSource(url);
    es.onopen = () => setSseConnected(true);
    es.onmessage = (event) => {
      const parsed = JSON.parse(event.data);
      const deviceStatus = typeof parsed === 'string' ? JSON.parse(parsed) : parsed;
      setStatus(deviceStatus);
    };
    es.onerror = () => setSseConnected(false);
    return () => es.close();
  }, []);

  // Fallback: poll if SSE disconnects
  useEffect(() => {
    if (sseConnected) return;
    const interval = setInterval(async () => {
      try {
        const resp = await fetch(`${API_BASE}/property/${SILA_HOST}/${SILA_PORT}/${FEATURE_ID}/DeviceStatus`);
        const data = await resp.json();
        if (data.value) setStatus(typeof data.value === 'string' ? JSON.parse(data.value) : data.value);
      } catch {}
    }, 3000);
    return () => clearInterval(interval);
  }, [sseConnected]);

  return { status, sseConnected };
}
```

### Command Execution with Error Modal

```javascript
const [errorModal, setErrorModal] = useState(null);

const executeCommand = async (feature, command, params) => {
  const resp = await fetch(`${API_BASE}/command/${SILA_HOST}/${SILA_PORT}/${feature}/${command}`, {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(params),
  });
  const data = await resp.json();
  if (!resp.ok || data.status === 'error') {
    setErrorModal({ command, message: data.message, errorType: data.error_type });
    throw new Error(data.message);
  }
  return data;
};
```

### Settings Persistence with localStorage

```javascript
const [serialPort, setSerialPort] = useState(() =>
  localStorage.getItem('serialPort') || 'COM3'
);
useEffect(() => localStorage.setItem('serialPort', serialPort), [serialPort]);
```

### Mode-Specific UI

```javascript
{status.isConnected && <DeviceControls />}
{!status.isConnected && <ConnectionForm />}
```

---

## Parameter Validation

### FDL Constraints vs Server-Side Validation

Use FDL `<Constraints>` for simple range/pattern validation — the framework enforces these before your code runs. Use Defined Execution Errors for complex, state-dependent validation.

**Important:** FDL constraint violations raise `ValidationError` at the framework level. Server-side checks raise your named `DefinedExecutionError`. Tests should account for which layer catches the error.

### Command Parameter Ordering

SiLA commands pass parameters positionally based on **FDL definition order**, not alphabetically. The `device_helpers.py` and Flask API handle this automatically using command metadata.

---

## Serial Communication Robustness

When wrapping serial instruments:

### Buffer Drain on Connect
```python
self._serial.reset_input_buffer()
self._serial.reset_output_buffer()
old_timeout = self._serial.timeout
self._serial.timeout = 0.3
while True:
    stale = self._serial.readline()
    if not stale:
        break
self._serial.timeout = old_timeout
```

### Error State Recovery
```python
try:
    lines = self._send_and_receive("VER", timeout=timeout)
except Exception:
    logger.warning("VER failed, sending EAK to clear error state...")
    try:
        self._send_and_receive("EAK", timeout=timeout)
    except Exception:
        pass
    lines = self._send_and_receive("VER", timeout=timeout)
```

### Per-Command Timeouts
```python
def send_command(self, cmd: str, timeout: float | None = None) -> list[str]:
    original_timeout = self._serial.timeout
    if timeout is not None:
        self._serial.timeout = timeout
    try:
        return self._send_and_receive(cmd)
    finally:
        if timeout is not None:
            self._serial.timeout = original_timeout
```

---

## Testing

### Compliance Validator

```bash
python -m sila_server_common.validate servers/<name>
```

### Creating a Test Suite

Every server should have a test suite. Create `client_web_ui/test_suites/<name>.json` and run it at `/tests/<name>` in the web UI.

#### Test Suite Structure

```json
{
  "server": "MyDevice",
  "host": "localhost",
  "port": 50062,
  "description": "Test suite for MyDevice server",
  "categories": [
    {
      "id": "connection",
      "name": "Connection",
      "description": "Connect/disconnect and session management",
      "tests": [...]
    }
  ]
}
```

#### Test Types

| Type | Badge | Description |
|------|-------|-------------|
| `scripted` | Green | Fully automated — runs SiLA commands, checks responses, no user interaction |
| `guided` | Purple | Semi-automated — runs SiLA commands with user prompts and confirmations |

#### Scripted Tests

Scripted tests run automatically with no user interaction. Use for command validation, error handling, and state transitions.

```json
{
  "id": "conn_sim",
  "name": "Connect in simulation mode",
  "type": "scripted",
  "modes": ["simulation"],
  "description": "Connect in simulation and verify instrument name is returned.",
  "expected": "Connect succeeds, InstrumentName is not empty",
  "script": {
    "steps": [
      {"action": "ensure_connected"},
      {"action": "check_response", "field": "InstrumentName", "operator": "not_empty"}
    ]
  }
}
```

#### Guided Tests

Guided tests combine automated SiLA command execution with user interaction points. Use for tests that require physical actions (placing plates, swapping parts), visual confirmation (checking fill levels, observing UI), or timed interventions (aborting mid-operation).

Two interaction step types:

- **`prompt`** — Pauses execution, shows a message with a "Continue" button. Use to instruct the user to perform a physical action before proceeding.
- **`confirm`** — Pauses execution, shows a message with pass/fail buttons. If the user clicks fail, the test fails immediately.

```json
{
  "id": "disp_96well_real",
  "name": "96-well dispense (real)",
  "type": "guided",
  "modes": ["real"],
  "description": "Dispense to a 96-well plate and verify even fill.",
  "expected": "All 96 wells filled evenly with ~50 uL each",
  "script": {
    "steps": [
      {"action": "ensure_connected"},
      {"action": "command", "feature": "MyDevice", "command": "SetPlateType", "params": {"PlateType": 0}, "expect": "success"},
      {"action": "command", "feature": "MyDevice", "command": "Prime", "params": {"Volume": 5000}, "expect": "success"},
      {"action": "prompt", "message": "Place an empty 96-well plate on the instrument deck"},
      {"action": "command", "feature": "MyDevice", "command": "Dispense", "params": {}, "expect": "success"},
      {"action": "confirm", "message": "Are all 96 wells filled evenly?", "pass_label": "Even fill", "fail_label": "Uneven or missing"}
    ]
  }
}
```

Guided test patterns:

| Pattern | Steps |
|---------|-------|
| **Physical setup + automated command** | `prompt` (instruct user) → `command` → `confirm` (verify result) |
| **Abort during operation** | `prompt` (tell user to abort after Continue) → `command` with `expect: "any"` → `confirm` |
| **Error recovery** | `command` (trigger error) → `prompt` (physical fix) → `command` (retry) → `confirm` |
| **Visual inspection** | `command` (change state) → `confirm` (did UI update?) |
| **Multi-step comparison** | `command` → `confirm` → `command` → `confirm` (compare outcomes) |

#### Mode Tagging

Every test must specify which modes it runs in:

```json
"modes": ["simulation"]           // Only runs in simulation mode
"modes": ["real"]                 // Only runs with real hardware
"modes": ["simulation", "real"]   // Runs in both modes
```

The test runner UI filters tests by mode. `ensure_connected` infers whether to connect in simulation or real mode from the test's `modes` tag.

#### DSL Step Reference

| Action | Fields | Description |
|--------|--------|-------------|
| `command` | `feature`, `command`, `params`, `expect` | Execute a SiLA command. `expect`: `"success"`, `"error"`, or `"any"` |
| `check_response` | `field`, `operator`, `value` | Validate previous command's response field |
| `wait` | `ms` | Pause for N milliseconds |
| `loop` | `count`, `steps` | Repeat steps N times (use `$i` for iteration index) |
| `loop_values` | `values`, `variable`, `steps` | Iterate over array, binding each to `$variable` |
| `ensure_connected` | — | Smart connect: infers sim/real from test's `modes` tag |
| `prompt` | `message` | (Guided only) Pause with message + Continue button |
| `confirm` | `message`, `pass_label`, `fail_label` | (Guided only) Pause with pass/fail buttons |

Error testing:
```json
{"action": "command", "feature": "MyDevice", "command": "DoThing", "params": {}, "expect": "error", "error_type": "NotConnected"}
```

`check_response` operators: `equals`, `not_empty`, `contains`, `greater_than`, `less_than`, `matches` (regex).

#### Recommended Test Categories

When creating a test suite, organize tests into these categories as applicable:

| Category | What to Test |
|----------|-------------|
| **Connection** | Connect/disconnect in sim and real, reconnect after error |
| **Commands** | Each command with valid params (sim + real), verify responses |
| **Error Handling** | Invalid params, wrong state, boundary values |
| **Sequencing** | Multi-step workflows, prerequisite enforcement, abort |
| **Properties** | Observable property updates, DeviceStatus JSON |
| **LockController** | Lock/unlock, wrong token, commands while locked |
| **Physical/Hardware** | Guided tests for physical interactions (real mode) |
| **WebUI** | Guided tests for UI verification (SSE, badges, settings) |
| **Logging** | ServerLogProvider queries and filters |
| **ScriptRunner** | Script execution and output streaming |

#### Reference Test Suite

See `client_web_ui/test_suites/multidrop_combi.json` for a comprehensive example with 111 tests (85 scripted + 26 guided) across 10 categories.

---

## Deployment

Each server includes `deploy.bat` for Windows target machines and can be deployed via Ansible. See `deployment/` for fleet management.

## Reference Implementation

See `servers/multidrop_combi/` for the most complete server implementation with serial communication, full WebUI, and comprehensive test suite.

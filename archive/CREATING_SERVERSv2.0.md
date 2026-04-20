# How to Create a New SiLA 2 Server (v2.0)

This document tells Claude how to generate a new SiLA 2 device server with **v2.0 patterns**: Observable properties for real-time state push, React + Babel CDN WebUI, and SSE streaming.

> This builds on the v1.0 patterns in `CREATING_SERVERS.md`. All v1 concepts (FDL XML, codegen, SimulationController, LockController, ScreenStreamer, MessagingClient, etc.) still apply. This document focuses on what's new in v2.

## What's New in v2.0

### Observable Properties for Real-Time State Push

In v1, device state properties (IsConnected, IsPrimed, etc.) were **unobservable** — clients had to poll. In v2, key state properties are **observable**, meaning the server pushes updates to clients automatically via gRPC streaming.

**How it works:**
1. FDL declares a property as `<Observable>Yes</Observable>`
2. Code generation creates `update_PropertyName(value)` methods instead of `get_PropertyName()` getters
3. The implementation calls `self.update_PropertyName(new_value)` whenever state changes
4. SiLA clients subscribe via gRPC streaming and receive updates in real-time

**Key pattern — the `DeviceStatus` observable property:**

Every v2 server should include a `DeviceStatus` observable property that carries a JSON string with the full device state. This single property drives the entire WebUI:

```xml
<Property>
    <Identifier>DeviceStatus</Identifier>
    <DisplayName>Device Status</DisplayName>
    <Description>Current device status as a JSON string with all state fields (for SSE streaming to WebUI).</Description>
    <Observable>Yes</Observable>
    <DataType><Basic>String</Basic></DataType>
</Property>
```

The implementation pushes updates after every command:

```python
def _push_device_status(self, activity: str | None = None) -> None:
    """Push a full device status update via the DeviceStatus observable property."""
    if activity:
        ts = time.strftime("%H:%M:%S")
        self._activity_log.append(f"[{ts}] {activity}")
        if len(self._activity_log) > 100:
            self._activity_log = self._activity_log[-100:]

    status = {
        "isConnected": ...,
        "isPrimed": ...,
        # ... all state fields
        "activityLog": self._activity_log[-50:],
    }
    self.update_DeviceStatus(json.dumps(status))
```

### React + Babel CDN WebUI (Single HTML File)

The WebUI is a React app served as a single HTML file via the `WebUIProvider` feature. React and Babel are loaded from CDN — no build step needed.

```html
<script src="https://unpkg.com/react@18/umd/react.production.min.js" crossorigin></script>
<script src="https://unpkg.com/react-dom@18/umd/react-dom.production.min.js" crossorigin></script>
<script src="https://unpkg.com/@babel/standalone/babel.min.js"></script>
```

JSX is transpiled in-browser by Babel standalone:

```html
<script type="text/babel" data-type="module">
const { useState, useEffect, useRef, useCallback } = React;
// ... React components with hooks
</script>
```

### SSE (Server-Sent Events) for Browser Push

The Flask client_web_ui has an SSE endpoint that bridges SiLA observable properties to the browser:

```
GET /api/sse/<host>/<port>/<featureId>/<propertyId>
```

This endpoint subscribes to the SiLA observable property via gRPC streaming and forwards each update as an SSE event. The React WebUI connects via `EventSource`:

```javascript
function useDeviceStatus() {
  const [status, setStatus] = useState({...defaults});
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

  // Fallback: poll if SSE not available
  useEffect(() => {
    if (sseConnected) return;
    const interval = setInterval(async () => { ... poll ... }, 3000);
    return () => clearInterval(interval);
  }, [sseConnected]);

  return { status, sseConnected };
}
```

### Application Layer Concept

The WebUIProvider creates an **application layer** for device control. This is important because:

1. **Humans** interact with instruments through the WebUI's forms, buttons, and plate maps
2. **Robots/automation systems** (like the autonomous_lab_mockup) interact through the same SiLA commands
3. **AI agents** interact through Gemini chat with SiLA commands as tools

The WebUI is not just a "remote control" — it's an **application** that understands device workflows (e.g., "you must prime before dispensing") and presents them appropriately. The same workflow logic is exposed via SiLA commands so that both human operators and automated systems follow the same rules.

**Consumer application context:** The SiLA servers are consumed by the `autonomous_lab_mockup` application, which:
- Uses a `SiLAPlugin` that wraps SiLA 2 clients and auto-discovers features/commands
- Defines instruments via YAML config files with host, port, features filter, poll_interval
- Embeds the WebUI in an iframe for human interaction alongside programmatic control
- Tracks observable command progress for timeline visualization

## Step-by-Step Process

### Step 1: Create the FDL XML File

Same as v1 (see `CREATING_SERVERS.md`), but with these v2 additions:

**Observable properties** — use `<Observable>Yes</Observable>`:

```xml
<Property>
    <Identifier>IsConnected</Identifier>
    <DisplayName>Is Connected</DisplayName>
    <Description>Whether the instrument is connected. Observable for real-time UI updates.</Description>
    <Observable>Yes</Observable>
    <DataType><Basic>Boolean</Basic></DataType>
</Property>
```

**Always include a DeviceStatus observable property** for driving the WebUI.

### Step 2: Copy Reusable Feature FDLs

Same as v1 — copy SimulationController, ScreenStreamer, MessagingClient, WebUIProvider, UserManualProvider, ServerLogProvider, ScriptRunner FDL files.

### Step 3: Run Code Generation

Same as v1:

```bash
source .venv/Scripts/activate

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

### Step 4: Copy Shared Files

Copy these unchanged transport modules from any existing server:
- `win32_capture.py` — Win32 window capture
- `messaging_transport.py` — WebSocket messaging
- `structured_logging.py` — SQLite structured logging for ServerLogProvider
- `device_helpers.py` — Per-server script helper for ScriptRunner
- `serial_transport.py` — Serial communication (if wrapping a serial device)
- `icon.png` — Device icon
- `user_manual.pdf` — Device manual (if available)

### Step 5: Customize server.py

Same pattern as v1 (see `CREATING_SERVERS.md`). Update server name, description, type, version, and feature registrations.

### Step 6: Customize __main__.py

Same as v1, but update:
- Default port number
- Log file name
- Package module name

### Step 7: Write the Feature Implementation

Follow the v1 pattern but with these v2 additions:

**Observable property — push initial values in `start()`:**

```python
def start(self) -> None:
    super().start()
    self.update_IsConnected(False)
    self.update_IsPrimed(False)
    self.update_InstrumentName("")
    self.update_FirmwareVersion("")
    self._push_device_status()
```

**Push updates after every state change:**

```python
def Connect(self, SerialPort: str, *, metadata: MetadataDict) -> Connect_Responses:
    # ... connect logic ...
    self.update_IsConnected(True)
    self.update_InstrumentName(info["instrument_name"])
    self._push_device_status(f"Connected to {SerialPort}")
    return Connect_Responses(...)
```

**SimulationController must also push observable updates:**

```python
def _disconnect_multidrop(self) -> None:
    combi = self.parent_server.multidropcombi
    # ... disconnect logic ...
    combi.update_IsConnected(False)
    combi.update_IsPrimed(False)
    combi._push_device_status("Disconnected due to simulation mode change")
```

### Step 8: Write the React WebUI (custom_ui.html)

Create a single HTML file with React + Babel CDN. Key patterns:

1. **API helpers** — direct `fetch()` calls using host/port from URL path
2. **SSE hook** — `useDeviceStatus()` custom hook for real-time state
3. **React components** — StatusBar, PlateMap, ActivityLog, ErrorModal, etc.
4. **State management** — `useState` for local UI state, SSE for device state
5. **Command execution** — `executeCommand()` with error recovery modal
6. **Settings persistence** — `localStorage` for saved configurations

```javascript
// Extract SiLA server host/port from iframe URL
const _urlParts = window.location.pathname.split('/');
const SILA_HOST = _urlParts[3];
const SILA_PORT = _urlParts[4];
const API_BASE = `${window.location.origin}/api`;
```

### Step 9: Copy Reusable Feature Implementations

Copy the implementations for ScreenStreamer, MessagingClient, WebUIProvider, UserManualProvider, LockController, ServerLogProvider, ScriptRunner from any existing server. These are identical across all servers.

### Step 10: Update pyproject.toml

Add all required dependencies:

```toml
[project]
name = "<snake_case_name>"
version = "0.0.0"
requires-python = ">=3.10"
dependencies = [
    "sila2",
    "typer",
    "pyserial",       # if wrapping serial device
    "pywin32",        # for ScreenStreamer
    "opencv-python",  # for ScreenStreamer
    "numpy",          # for ScreenStreamer
    "Pillow",         # for ScreenStreamer simulation placeholder
]
```

### Step 11: Create deploy.bat and start_server.bat

Copy from existing server and update:
- Server name in echo messages
- Port numbers (both in firewall rule and python -m commands)
- Package module name (`python -m <snake_case_name>`)

### Step 12: Install and Test

```bash
source .venv/Scripts/activate
pip install -e servers/<snake_case_name>
python -m <snake_case_name> --insecure --port <PORT> --verbose
```

### Step 13: Update CLAUDE.md

Add the new server to the project structure, port assignments, and server list.

## Architecture Overview

```
Browser (React WebUI)
    |
    | EventSource (SSE)
    v
Flask client_web_ui (SSE endpoint)
    |
    | gRPC streaming (observable property subscription)
    v
SiLA 2 Server (gRPC)
    |
    | update_DeviceStatus(json)  <-- called after every command
    v
Observable Property subscribers
    |
    +-- Flask SSE -> Browser (real-time UI updates)
    +-- SiLAPlugin (autonomous_lab_mockup) -> instrument status
    +-- Any other SiLA client
```

## Key Differences from v1

| Aspect | v1 | v2 |
|--------|----|----|
| State properties | Unobservable (polled) | Observable (pushed) |
| WebUI framework | Vanilla JavaScript | React 18 + Babel CDN |
| Real-time updates | `setInterval(pollStatus, 5000)` | SSE via `EventSource` |
| State management | DOM manipulation + globals | React hooks (`useState`, `useEffect`) |
| WebUI architecture | Imperative | Declarative/reactive |
| Activity log | Local to browser | Server-side (pushed via DeviceStatus) |
| SSE indicator | N/A | Badge showing SSE LIVE/OFF status |

## WebUI Patterns (Lessons from Multidrop Combi v2)

### Error Recovery Modal

When a command fails, show a modal with the error details and options to retry or dismiss. The SSE-driven state will auto-update once the user resolves the issue:

```javascript
const [errorModal, setErrorModal] = useState(null);

const executeCommand = async (feature, command, params) => {
  try {
    const resp = await fetch(`${API_BASE}/command/${host}/${port}/${feature}/${command}`, {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(params),
    });
    const data = await resp.json();
    if (!resp.ok || data.status === 'error') {
      setErrorModal({ command, message: data.message, errorType: data.error_type });
      throw new Error(data.message);
    }
    return data;
  } catch (err) { /* ... */ }
};
```

### Unit Conversion in Settings

Store user-preferred units in `localStorage` and convert on display:

```javascript
const [volumeUnit, setVolumeUnit] = useState(() =>
  localStorage.getItem('volumeUnit') || 'µL'
);
// Convert from server's native unit (µL) to display unit
const displayVolume = (ul) => volumeUnit === 'mL' ? (ul / 1000).toFixed(3) : ul;
```

### Settings Persistence with localStorage

Persist user configuration (serial port, plate type, cassette, volume unit) across sessions:

```javascript
const [serialPort, setSerialPort] = useState(() =>
  localStorage.getItem('serialPort') || 'COM3'
);
useEffect(() => localStorage.setItem('serialPort', serialPort), [serialPort]);
```

### Mode-Specific UI Elements

Show/hide UI sections based on device state from SSE:

```javascript
// Only show prime/dispense controls when connected
{status.isConnected && <DispenseControls />}
// Show connection form when disconnected
{!status.isConnected && <ConnectionForm />}
```

### Prime/Empty Continuous Mode

For commands that run until stopped (continuous prime, continuous empty), use a "running" state flag and an abort/stop button:

```javascript
const [continuousRunning, setContinuousRunning] = useState(false);
const startContinuous = async () => {
  setContinuousRunning(true);
  await executeCommand('MultidropCombi', 'Prime', { Volume: 0, Mode: 1 }); // Mode 1 = continuous
};
const stopContinuous = async () => {
  await executeCommand('MultidropCombi', 'StopDispense', {});
  setContinuousRunning(false);
};
```

## Serial Communication Robustness Patterns

When wrapping serial instruments, these patterns prevent common failure modes:

### Buffer Drain on Connect

The instrument's USB transmit buffer may hold unread data from a prior session. `reset_input_buffer()` only clears host-side buffers:

```python
# Drain stale data from previous sessions
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

### Error State Recovery on Connect (EAK Retry)

Some instruments persist error state across disconnect/reconnect. If the initial handshake command fails, clear the error and retry:

```python
# If VER fails (instrument in error state from previous session),
# send EAK to clear the error, then retry VER once.
try:
    lines = self._send_and_receive("VER", timeout=timeout)
except Exception as first_err:
    logger.warning("VER failed (%s), sending EAK and retrying...", first_err)
    try:
        self._send_and_receive("EAK", timeout=timeout)  # Clear error
    except Exception:
        pass  # EAK may itself return an error; that's fine
    try:
        lines = self._send_and_receive("VER", timeout=timeout)
    except Exception as e:
        self._serial.close()
        self._serial = None
        raise ConnectionError(f"VER command failed: {e}") from e
```

### Per-Command Timeout Management

Different commands need different timeouts. Dispense operations may take minutes; status queries should respond in seconds:

```python
def send_command(self, cmd: str, timeout: float | None = None) -> list[str]:
    original_timeout = self._serial.timeout
    if timeout is not None:
        self._serial.timeout = timeout
    try:
        # ... send and receive ...
    finally:
        if timeout is not None:
            self._serial.timeout = original_timeout
```

## Parameter Validation Patterns

### FDL Constraints vs Server-Side Validation

Use FDL constraints (`<Constraints>`) for simple range/pattern validation — the framework enforces these before the command reaches your code:

```xml
<Parameter>
    <Identifier>Speed</Identifier>
    <DataType>
        <Constrained>
            <DataType><Basic>Integer</Basic></DataType>
            <Constraints>
                <MinimalInclusive>1</MinimalInclusive>
                <MaximalInclusive>6</MaximalInclusive>
            </Constraints>
        </Constrained>
    </DataType>
</Parameter>
```

For complex, state-dependent validation (e.g., "can't dispense unless primed"), raise Defined Execution Errors in the implementation:

```python
def Dispense(self, ...):
    if not self._transport.is_primed:
        raise NotPrimed("Pump must be primed before dispensing")
```

**Important:** FDL constraint violations raise `ValidationError` at the framework level, while server-side checks raise your named `DefinedExecutionError`. Tests should account for which layer catches the error.

### Command Parameter Ordering

The SiLA command API passes parameters positionally based on definition order in the FDL, not alphabetically. When building API endpoints that accept JSON, look up the command metadata to get the correct order:

```python
cmd_meta = {
    **getattr(feature, "_unobservable_commands", {}),
    **getattr(feature, "_observable_commands", {}),
}.get(command_id)

args = []
if cmd_meta and cmd_meta.parameters:
    for p in cmd_meta.parameters:
        pid = p._identifier
        if pid in params:
            args.append(params[pid])
```

## Test Runner Framework

The project includes a generic test runner for automated and manual testing of any SiLA server, accessible from the Web UI.

### Architecture

```
client_web_ui/
├── test_suites/                    # JSON test suite definitions
│   └── multidrop_combi_v2.json     # Tests for Multidrop Combi v2
├── templates/
│   ├── test_suites.html            # Index page listing available suites
│   └── test_runner.html            # React-based test runner UI
└── app.py                          # Routes: /tests, /tests/<name>, /api/tests/<name>/list
```

### Test Suite JSON Format

Each test suite is a JSON file with metadata and categorized tests:

```json
{
  "server": "MultidropCombiV2",
  "host": "localhost",
  "port": 50055,
  "description": "Test suite for Multidrop Combi v2 server",
  "serial_port": "COM3",
  "categories": [
    {
      "name": "Communication",
      "tests": [
        {
          "id": "comm_connect_sim",
          "name": "Connect in simulation mode",
          "modes": ["simulation"],
          "type": "scripted",
          "steps": [
            { "action": "command", "feature": "SimulationController", "command": "StartSimulationMode", "params": {} },
            { "action": "command", "feature": "MultidropCombi", "command": "Connect", "params": { "SerialPort": "SIM" } },
            { "action": "check_response", "field": "InstrumentName", "operator": "not_empty" },
            { "action": "command", "feature": "MultidropCombi", "command": "Disconnect", "params": {} }
          ]
        }
      ]
    }
  ]
}
```

### Test DSL Actions

| Action | Description |
|--------|-------------|
| `command` | Execute a SiLA command. Use `expect: "error"` and `error_type` to test error cases |
| `check_response` | Validate a field from the last command response (`equals`, `not_empty`, `contains`, `greater_than`, etc.) |
| `wait` | Pause for `ms` milliseconds |
| `loop` | Repeat nested `steps` for `count` iterations with `$i` variable |
| `loop_values` | Iterate over `values` array, binding each to `variable` |
| `ensure_connected` | Smart connect: infers simulation vs real mode from test's `modes` tag |

### Mode Filtering

Tests are tagged with `"modes": ["simulation"]`, `"modes": ["real"]`, or `"modes": ["simulation", "real"]`. The runner UI has toggle buttons (Simulation / Real Hardware / All) that filter visible tests. The `ensure_connected` action auto-selects connection method based on the mode filter and the test's own mode tags.

### Manual (Checklist) Tests

Tests with `"type": "manual"` show a checklist UI instead of automated steps:

```json
{
  "id": "hw_cassette_install",
  "name": "Cassette installation detection",
  "modes": ["real"],
  "type": "manual",
  "checklist": [
    "Install a standard cassette in the instrument",
    "Verify cassette type is detected correctly",
    "Remove cassette and verify status updates"
  ]
}
```

### Running Tests

1. Navigate to `/tests` in the Web UI
2. Select a test suite
3. Choose mode filter (Simulation / Real / All)
4. Set serial port for real hardware tests
5. Click "Run All Scripted" or run individual tests
6. Manual tests: check off items and mark Pass/Fail/Skip
7. Export results as JSON

## ServerLogProvider (Structured Logging)

Every v2 server includes a `ServerLogProvider` feature that stores structured log entries in SQLite and exposes them via SiLA commands with filtering.

### Architecture

```
Python logging (all loggers)
    |
    +-- RotatingFileHandler → plain-text .log file (human debugging)
    +-- StructuredLogHandler → SQLite structured.db (query via SiLA)
```

### Transport Module: `structured_logging.py`

This is a reusable transport module (like `win32_capture.py`). **Do not diverge across servers.**

Key components:
- **`StructuredLogHandler`** — `logging.Handler` subclass that writes to SQLite with WAL mode, thread-local connections, and periodic pruning (50k row cap)
- **`query_logs()`** — parameterized SQL queries with time range, severity, feature, and max_entries filters
- **`get_distinct_features()`** — returns unique feature names in the DB
- **`get_log_stats()`** — summary statistics (total, counts by level, oldest/newest, DB size)

### Feature-Name Mapping

The handler maps Python module names to human-readable feature names. Customize `DEFAULT_FEATURE_MAP` per server:

```python
DEFAULT_FEATURE_MAP = {
    "multidropcombi_impl": "MultidropCombi",
    "simulationcontroller_impl": "SimulationController",
    "serial_transport": "SerialTransport",
    "__main__": "Server",
    # ... etc
}
```

### Enriching Log Calls

Add structured `extra` fields to existing log calls for richer query results:

```python
logger.info("Connect: port=%s", port, extra={"category": "command", "command_name": "Connect"})
logger.debug("TX: %r", cmd, extra={"category": "serial", "direction": "tx"})
logger.info("Entering simulation mode", extra={"category": "state_change"})
```

The `extra` fields are optional — the StructuredLogHandler captures them if present; existing plain-text handlers ignore them.

### Setup in `__main__.py`

```python
from .structured_logging import StructuredLogHandler

# In initialize_logging(), after the RotatingFileHandler:
structured_handler = StructuredLogHandler(log_dir / "structured.db")
structured_handler.setLevel(logging.DEBUG)
logging.getLogger().addHandler(structured_handler)
```

### Registration in `server.py`

```python
from .feature_implementations.serverlogprovider_impl import ServerLogProviderImpl
from .generated.serverlogprovider import ServerLogProviderFeature

self.serverlogprovider = ServerLogProviderImpl(self)
self.set_feature_implementation(ServerLogProviderFeature, self.serverlogprovider)
```

## ScriptRunner (Per-Server Scripting)

Every v2 server includes a `ScriptRunner` feature that runs Python automation scripts on the server with output streaming via observable command intermediate responses.

### Architecture

```
User submits ScriptCode via SiLA RunScript command
  -> ScriptRunnerImpl writes preamble + code to temp file
  -> Launches subprocess (python -u) for isolation
  -> Streams stdout line-by-line as IntermediateResponses
  -> Auto-locks device during execution (LockController)
  -> Returns ExitCode + FullOutput on completion
```

### Transport Module: `device_helpers.py`

This is a reusable transport module (like `win32_capture.py`). **Do not diverge across servers.**

Key components:
- **`DeviceHelper`** — Injected as `device` in per-server scripts. Connects to the local server via gRPC loopback.
  - `device.command("Feature", "Command", Param=value)` — Execute a SiLA command
  - `device.property("Feature", "Property")` — Read a property value
  - `device.features` — List feature identifiers
  - `device.commands("Feature")` — List commands for a feature
  - `device.status()` — Read DeviceStatus (Multidrop-specific)
  - `device.print()` / `device.sleep()` — Script utilities

### FDL: `ScriptRunner.sila.xml`

Commands:
- `RunScript(ScriptName, ScriptCode)` — Observable, streams OutputLine, returns ExitCode + FullOutput
- `StopScript` — Kill running script
- `ListScripts` / `SaveScript` / `LoadScript` / `DeleteScript` — Script persistence (`.py` files in `scripts/` dir)

Properties:
- `IsRunning` — Boolean, whether a script is executing

Errors: `ScriptError`, `AlreadyRunning`, `ScriptNotFound`

### Registration in server.py

```python
from .feature_implementations.scriptrunner_impl import ScriptRunnerImpl
from .generated.scriptrunner import ScriptRunnerFeature

self.scriptrunner = ScriptRunnerImpl(self)
self.set_feature_implementation(ScriptRunnerFeature, self.scriptrunner)
```

## Global Scripting Engine (Client Web UI)

The Client Web UI includes a global scripting environment at `/scripts` for orchestrating workflows across multiple servers.

### Key Files

- `client_web_ui/lab_helpers.py` — `LabHelper` class injected as `lab` in scripts
- `client_web_ui/script_engine.py` — Subprocess-based script execution with SSE output streaming
- `client_web_ui/templates/scripts.html` — CodeMirror editor + output panel
- `client_web_ui/saved_scripts.json` — Persisted scripts

### lab Helper API

```python
lab.connect("Server Name")          # Connect by name substring
lab.connect("host", port)           # Connect by host:port
lab.servers()                       # List all configured servers
lab.sleep(seconds)                  # Sleep with output
lab.print("message")                # Print to output

device = lab.connect("Multidrop")
device.command("Feature", "Cmd", Param=value)  # Execute command
device.property("Feature", "Prop")             # Read property
device.lock() / device.unlock()                # Lock/unlock
device.features / device.commands("F") / device.properties("F")
```

## Reference Implementation

See `servers/multidrop_combi_v2/` for the complete v2.0 reference implementation:
- `MultidropCombi.sila.xml` — FDL with observable properties
- `ServerLogProvider.sila.xml` — Structured log query feature
- `ScriptRunner.sila.xml` — Per-server Python scripting feature
- `multidrop_combi_v2/feature_implementations/multidropcombi_impl.py` — Observable property push pattern
- `multidrop_combi_v2/feature_implementations/scriptrunner_impl.py` — Script execution with intermediate responses
- `multidrop_combi_v2/structured_logging.py` — SQLite structured logging transport
- `multidrop_combi_v2/device_helpers.py` — Per-server script helper transport
- `multidrop_combi_v2/custom_ui.html` — React + SSE WebUI with log viewer + script panel
- `multidrop_combi_v2/serial_transport.py` — Serial communication with robustness patterns
- `client_web_ui/app.py` — SSE endpoint (`/api/sse/...`), test runner routes, scripting routes
- `client_web_ui/lab_helpers.py` — Global scripting helper library
- `client_web_ui/script_engine.py` — Subprocess script execution engine
- `client_web_ui/test_suites/multidrop_combi_v2.json` — Test suite (scripted + manual)
- `client_web_ui/templates/test_runner.html` — React test runner UI

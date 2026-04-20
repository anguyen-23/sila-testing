# Debugging Changelog

Track fixes and improvements that may need to be propagated across servers.

## 2026-03-18 — Test Runner: Editable Server Host/Port

### Problem
Test runner hardcoded `default_host` from the test suite JSON (`127.0.0.1`), making it impossible to run tests against remote servers without editing the JSON file.

### Changes Made

**`client_web_ui/templates/test_runner.html`**
- Added editable `Host` and `Port` fields to the test runner UI (merged with Variables bar)
- Defaults populated from test suite JSON (`default_host`, `default_port`)
- `executeCommand` uses the editable state instead of hardcoded suite values
- Exported results include `server: { host, port }` for traceability
- Removed unused `VariableBar` component (merged into combined server/variables bar)

### Notes
- Per-server ScriptRunner uses `127.0.0.1` loopback intentionally — scripts run as subprocesses on the server machine, so this is correct
- Global scripts (`/scripts`) connect via `LabHelper` which reads from `DEFAULT_SERVERS`/`custom_servers.json` — already supports remote hosts

---

## 2026-03-18 — Persist Config: Camera Source, COM Port, Screen Capture

### Problem
Camera source, COM port, and screen capture window selections were lost on server restart or client reconnect. Camera source was hardcoded in `camera.json` and never updated when changed via the UI.

### Changes Made

**`sila_server_common/transports/camera_capture.py`**
- Added `save_camera_config()` with merge semantics (preserves existing keys like `auto_start`, `fps`, etc.)
- Refactored path resolution into `_camera_config_path()`

**`sila_server_common/feature_implementations/camerastreamprovider_impl.py`**
- `StartStream` now persists the source to `camera.json` after successful start
- Added `_save_source()` helper

**`sila_server_common/transports/device_config.py`** (NEW)
- Generic per-server `device_config.json` persistence: `load_device_config()`, `save_device_config()` with merge semantics
- For device-specific settings that don't belong in shared feature configs

**`servers/multidrop_combi/multidrop_combi/feature_implementations/multidropcombi_impl.py`**
- `Connect` persists `serial_port` to `device_config.json` after successful connection
- `DeviceStatus` JSON includes `configuredSerialPort` for WebUI default
- Cached serial port loaded once at `start()`, updated on Connect

**`servers/multidrop_combi/multidrop_combi/custom_ui.html`**
- Serial port input defaults to `configuredSerialPort` from DeviceStatus (server-side persistence)
- Uses `useRef` guard to apply server default only once

### Config Files Summary
| File | Purpose | Merge on save |
|------|---------|---------------|
| `camera.json` | Camera source, quality, fps, auto_start | Yes |
| `screen_capture.json` | Screen capture window title | No (full replace) |
| `device_config.json` | Device-specific settings (COM port, etc.) | Yes |

### Propagation
- Camera and screen capture persistence: shared library changes, all servers benefit automatically
- Device config (COM port): device-specific, other serial servers (barcode_scanner, etc.) can adopt the same pattern

---

## 2026-03-18 — ScreenStreamer: Persist Window Title Selection

### Problem
When a server restarts, the previously selected window title for screen capture is lost. The user has to manually call `StartCapture` again with the same window title each time.

### Changes Made (in `sila_server_common`)

**`transports/win32_capture.py`**
- Added `load_screen_config()`, `save_screen_config()`, and `_screen_config_path()` — follows the same pattern as `camera_capture.py`'s `load_camera_config()`
- Config file: `screen_capture.json` in the server root directory (alongside `pyproject.toml`)

**`feature_implementations/screenstreamer_impl.py`**
- `StartCapture` now persists the window title to `screen_capture.json` after successful capture start
- Added `auto_start(config)` method — restores capture from persisted config on server start
- Added `_save_window_title()` and `_clear_window_title()` helpers

**`base_server.py`**
- Added `start_insecure()` and `start()` overrides that call `_auto_start_screen_capture()`
- Auto-start loads `screen_capture.json` and calls `screenstreamer.auto_start()` if a window title is set

### Config Format
```json
{
    "window_title": "VENUS"
}
```

### Propagation
This is a shared library change — all servers get it automatically via `sila_server_common`. No per-server changes needed. The `screen_capture.json` file is created automatically on first `StartCapture` call.

---

## 2026-03-18 — AI Script Generation Fixes

### Problem
AI-generated scripts (via Gemini) produced `import lab` and `import time`, causing `ModuleNotFoundError`. The `lab` object is injected by the runtime preamble, not a real module. Additionally, the AI had no visibility into command parameter names, types, or descriptions — only command names — leading to incorrect parameter usage (wrong types, wrong argument counts).

### Changes Made

**`client_web_ui/script_engine.py`**
- Added `time` to preamble imports (commonly needed by scripts)
- Added safety net: strips `import lab` and `import time` lines from user/AI code before prepending preamble

**`client_web_ui/app.py` — `/api/scripts/generate` endpoint**
- System prompt now explicitly tells Gemini not to write `import lab` or `import time`
- System prompt includes detailed `device.command()` usage examples with keyword argument syntax
- System prompt documents parameter type expectations (String→str, Integer→int, etc.)
- Server introspection now sends full command signatures to the AI:
  - Parameter names, types, and descriptions (from FDL `<Description>` fields)
  - Response identifiers and types
  - Command descriptions
  - (Previously only sent command name lists with no parameter info)

**`CREATING_SERVERS.md`**
- Added callout in Command Patterns section: FDL `<Description>` fields are surfaced to the AI script generator, so they should be clear and specific

**`CLAUDE.md`**
- Added "AI Script Generation" section documenting the preamble, introspection, and FDL description importance
- Added "Debugging Workflow" section with process for tracking and propagating fixes

---

## 2026-03-18 — Ansible Deployment Fixes

### Problem 1: Log file locked during update
`win_copy` failed because the SiLA service had the log file locked. The update playbook was syncing files while the service was still running.

### Fix
**`deployment/playbooks/update_windows_server.yml`**
- Added `nssm stop` step before file sync
- Changed final step from `nssm restart` to `nssm start` (since service is already stopped)

### Problem 2: `sila_server_common` not deployed to remote machines
`pip install -e .` failed because `sila_server_common` is a local dependency (not on PyPI) and was never synced to the remote machine.

### Fix
**`deployment/playbooks/update_windows_server.yml`** and **`deployment/roles/sila_server/tasks/windows_server.yml`**
- Added step to sync `packages/sila_server_common/` to `C:\SiLA2\<package>\sila_server_common\` on remote
- Added step to `pip install -e sila_server_common` before installing the server package
- Layout on remote: `C:\SiLA2\<package>\` contains both the server code and `sila_server_common\` subdirectory

---

### Servers to Review
All servers should have good FDL descriptions on commands, parameters, and responses. Review and improve descriptions for:
- [ ] temperature_controller
- [ ] pump_controller
- [ ] plate_reader
- [ ] multidrop_combi
- [ ] venus_api
- [ ] barcode_scanner
- [ ] phenix_imager
- [ ] micronic_tube_scanner
- [ ] xarm6

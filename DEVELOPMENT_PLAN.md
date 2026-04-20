# Server Development Standardization Plan

## Goal
Make SiLA 2 server development robust, consistent, and hand-off ready. Any developer (with Claude) should be able to create a production-quality instrument server that matches the standard architecture by writing only three files: device FDL, device feature implementation, and custom WebUI.

## Phase 1: Shared Library Package (`sila_server_common`) -- COMPLETE
**Status:** Complete
**Priority:** Highest -- eliminates file drift permanently

Created `packages/sila_server_common/` containing:
- **Transport modules** (canonical copies, no per-server duplicates):
  - `win32_capture.py`, `messaging_transport.py`, `structured_logging.py`, `device_helpers.py`
- **Shared FDL files** (7): SimulationController, ScreenStreamer, MessagingClient, WebUIProvider, UserManualProvider, ServerLogProvider, ScriptRunner
- **Feature implementation factories** (7): Each is a `create_*_impl(generated_module)` function that returns an implementation class bound to the server's generated code
  - `lockcontroller_impl.py` -- direct class (uses sila2 built-in types, no factory needed)
  - `screenstreamer_impl.py`, `messagingclient_impl.py`, `webuiprovider_impl.py`, `usermanualprovider_impl.py`, `serverlogprovider_impl.py`, `scriptrunner_impl.py` -- factory functions
- **`BaseInstrumentServer`** (`base_server.py`): Subclass of `SilaServer` that auto-registers all 8 standard features. Device servers subclass this and only register their device-specific feature.
- **`create_main()`** (`server_main.py`): Shared CLI entry point with logging setup (console + RotatingFileHandler + StructuredLogHandler). Device servers' `__main__.py` is 5 lines.

Key design decision: Factory pattern for feature implementations. Since generated base classes live in each server's package, the shared library provides `create_*_impl(generated_module)` functions that dynamically create implementation classes bound to the right types. This avoids import path issues while keeping all logic in one place.

## Phase 2: Server Scaffold/Template Generator -- COMPLETE
**Status:** Complete
**Priority:** High -- makes server creation a 5-minute task

CLI tool: `python -m sila_server_common.scaffold --name my_device --port 50062`

Generates a complete server package with:
- All 7 shared FDL files copied from the canonical source
- Placeholder device FDL with DeviceStatus, DisplayIcon, DeviceDescription
- `server.py` using `BaseInstrumentServer` (device feature registration only)
- `__main__.py` using `create_main()` (5 lines)
- Placeholder device impl with TODO markers and `_push_device_status()` pattern
- Placeholder React WebUI with SSE hook and activity log
- `pyproject.toml` depending on `sila_server_common`
- `deploy.bat` and `start_server.bat`
- Placeholder icon
- Per-server `CLAUDE.md` for AI-assisted development

After scaffolding, the developer:
1. Edits the device FDL (add commands/properties)
2. Runs `sila2-codegen` (exact command printed by scaffold)
3. Implements the device feature (TODO markers guide them)
4. Builds the React WebUI

## Phase 3: Server Compliance Validator -- COMPLETE
**Status:** Complete
**Priority:** Medium -- catches mistakes after creation

CLI tool: `python -m sila_server_common.validate servers/my_device`

Checks:
- All 7 required FDL files present
- Device-specific FDL has DeviceStatus observable property
- Package structure (feature_implementations/, __init__.py, __main__.py, server.py, custom_ui.html)
- `pyproject.toml` depends on `sila_server_common`
- `server.py` uses `BaseInstrumentServer` and implements `on_simulation_mode_changed()`
- `__main__.py` uses `create_main()`
- No duplicate transport files (should import from sila_server_common)
- No duplicate boilerplate implementations (handled by BaseInstrumentServer)
- `deploy.bat` and `start_server.bat` exist

## Phase 4: Developer Documentation -- COMPLETE
**Status:** Complete
**Priority:** Medium -- makes it self-service

- Rewrote `CREATING_SERVERS.md` as unified guide for the scaffold-based workflow (FDL reference, implementation patterns, WebUI patterns, serial communication, testing, deployment)
- Scaffold generates a per-server `CLAUDE.md` with architecture context, key files, commands, and patterns
- No separate DEVELOPER_GUIDE.md needed -- `CREATING_SERVERS.md` covers architecture, workflow, and all patterns in one document

## Phase 5: Clean Slate & Server Migration -- IN PROGRESS
**Status:** In progress
**Priority:** Lower -- existing servers work, but should match the standard

**Last known working commit (pre-migration):** `b2cc7e7` — all servers functional with local copies of standard features.

- [x] Removed v1/v2 naming -- all servers use semantic versioning (1.0.0)
- [x] Archived old v1 servers (multidrop_combi_v1, venus_api_v1) to `archive/servers/`
- [x] Renamed v2 servers to canonical names (multidrop_combi, venus_api)
- [x] Cleaned all v2.0 references from docs, shared library, and server code
- [x] Updated pyproject.toml versions to semver across all servers
- [x] Migrate multidrop_combi to use `sila_server_common` (BaseInstrumentServer, create_main)
- [x] Migrate venus_api to use `sila_server_common` (BaseInstrumentServer, create_main)
- [ ] Migrate remaining v1 servers to use `sila_server_common` imports
- [ ] Add missing features to older servers (ServerLogProvider, ScriptRunner, etc.)
- [ ] Apply the unlocked guard fix to all lockcontroller implementations
- [ ] Remove duplicate transport/impl files from individual server directories

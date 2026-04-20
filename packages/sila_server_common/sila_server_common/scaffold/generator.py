"""Server scaffold generator — creates a complete SiLA 2 server package.

Generates:
    servers/<name>/
    ├── <FeatureName>.sila.xml          # Placeholder device FDL (TODO: customize)
    ├── SimulationController.sila.xml   # Copied from sila_server_common
    ├── ScreenStreamer.sila.xml          # ...
    ├── MessagingClient.sila.xml
    ├── WebUIProvider.sila.xml
    ├── UserManualProvider.sila.xml
    ├── ServerLogProvider.sila.xml
    ├── ScriptRunner.sila.xml
    ├── pyproject.toml
    ├── deploy.bat
    ├── start_server.bat
    └── <name>/
        ├── __init__.py
        ├── __main__.py
        ├── server.py
        ├── custom_ui.html              # Placeholder React WebUI (TODO: customize)
        ├── icon.png                    # Placeholder (TODO: replace)
        ├── py.typed
        └── feature_implementations/
            ├── __init__.py
            └── <featurename>_impl.py   # Placeholder device impl (TODO: customize)
"""
from __future__ import annotations

import argparse
import re
import shutil
from pathlib import Path

from sila_server_common.fdl import get_all_fdl_paths, get_fdl_path


def _to_snake_case(name: str) -> str:
    """Convert a name to snake_case."""
    s = re.sub(r'[^a-zA-Z0-9]', '_', name)
    s = re.sub(r'([A-Z]+)([A-Z][a-z])', r'\1_\2', s)
    s = re.sub(r'([a-z\d])([A-Z])', r'\1_\2', s)
    return s.lower().strip('_')


def _to_pascal_case(name: str) -> str:
    """Convert a name to PascalCase."""
    parts = re.split(r'[_\-\s]+', name)
    return ''.join(p.capitalize() for p in parts if p)


def _to_display_name(name: str) -> str:
    """Convert snake_case to a human-readable display name."""
    parts = re.split(r'[_\-\s]+', name)
    return ' '.join(p.capitalize() for p in parts if p)


def generate_server(
    name: str,
    port: int,
    output_dir: Path,
    feature_name: str | None = None,
    camera: bool = False,
) -> Path:
    """Generate a complete SiLA 2 server package.

    Args:
        name: Server name in snake_case (e.g., "centrifuge", "vortex_mixer").
        port: Default port number.
        output_dir: Parent directory for the server (e.g., "servers/").
        feature_name: Optional PascalCase feature name. Defaults to PascalCase of name.

    Returns:
        Path to the generated server directory.
    """
    snake = _to_snake_case(name)
    pascal = feature_name or _to_pascal_case(name)
    display = _to_display_name(name)
    feature_lower = pascal.lower()

    server_dir = output_dir / snake
    pkg_dir = server_dir / snake
    impl_dir = pkg_dir / "feature_implementations"

    if server_dir.exists():
        raise FileExistsError(f"Server directory already exists: {server_dir}")

    # Create directories
    impl_dir.mkdir(parents=True)

    # ── Copy shared FDL files ──
    for fdl_path in get_all_fdl_paths():
        shutil.copy2(fdl_path, server_dir / fdl_path.name)

    # ── Optional: CameraStreamProvider ──
    if camera:
        camera_fdl = get_fdl_path("CameraStreamProvider")
        shutil.copy2(camera_fdl, server_dir / camera_fdl.name)
        (server_dir / "camera.json").write_text(
            '{\n'
            '    "source": "",\n'
            '    "type": "ip",\n'
            '    "auto_start": false,\n'
            '    "jpeg_quality": 80,\n'
            '    "fps": 15\n'
            '}\n',
            encoding="utf-8",
        )

    # ── Generate device FDL ──
    (server_dir / f"{pascal}.sila.xml").write_text(_fdl_template(pascal, display), encoding="utf-8")

    # ── Generate Python package files ──
    (pkg_dir / "__init__.py").write_text(_init_template(), encoding="utf-8")
    (pkg_dir / "__main__.py").write_text(_main_template(snake, port), encoding="utf-8")
    (pkg_dir / "server.py").write_text(_server_template(snake, pascal, feature_lower, display, camera=camera), encoding="utf-8")
    (pkg_dir / "py.typed").write_text("", encoding="utf-8")
    (impl_dir / "__init__.py").write_text("", encoding="utf-8")
    (impl_dir / f"{feature_lower}_impl.py").write_text(
        _device_impl_template(snake, pascal, feature_lower), encoding="utf-8"
    )

    # ── Generate WebUI placeholder ──
    (pkg_dir / "custom_ui.html").write_text(_webui_template(pascal, display, port), encoding="utf-8")

    # ── Generate pyproject.toml ──
    (server_dir / "pyproject.toml").write_text(_pyproject_template(snake), encoding="utf-8")

    # ── Generate deploy.bat and start_server.bat ──
    (server_dir / "deploy.bat").write_text(_deploy_bat_template(snake, display, port), encoding="utf-8")
    (server_dir / "start_server.bat").write_text(_start_bat_template(snake, port), encoding="utf-8")

    # ── Generate placeholder icon ──
    _generate_placeholder_icon(pkg_dir / "icon.png")

    # ── Generate CLAUDE.md for AI-assisted development ──
    (server_dir / "CLAUDE.md").write_text(_claude_md_template(snake, pascal, display, port), encoding="utf-8")

    print(f"Server scaffold generated: {server_dir}")
    print(f"")
    print(f"Next steps:")
    print(f"  1. Edit {server_dir / f'{pascal}.sila.xml'} — define your device commands and properties")
    print(f"  2. Run codegen:")
    print(f"     sila2-codegen new-package -n {snake} -o {server_dir} --lock-controller \\")
    print(f"       {server_dir / f'{pascal}.sila.xml'} \\")
    for fdl_path in get_all_fdl_paths():
        print(f"       {server_dir / fdl_path.name} \\")
    if camera:
        print(f"       {server_dir / 'CameraStreamProvider.sila.xml'} \\")
    print(f"  3. Edit {impl_dir / f'{feature_lower}_impl.py'} — implement your device commands")
    print(f"  4. Edit {pkg_dir / 'custom_ui.html'} — build your React WebUI")
    print(f"  5. Install: pip install -e {server_dir}")
    print(f"  6. Run: python -m {snake} --insecure --port {port} --verbose")

    return server_dir


def _generate_placeholder_icon(path: Path) -> None:
    """Generate a simple placeholder PNG icon."""
    try:
        from PIL import Image, ImageDraw
        img = Image.new('RGBA', (64, 64), color=(70, 130, 180, 255))
        draw = ImageDraw.Draw(img)
        draw.rectangle([8, 8, 56, 56], outline=(255, 255, 255, 200), width=2)
        draw.text((18, 20), "SiLA", fill=(255, 255, 255, 230))
        img.save(path, format='PNG')
    except ImportError:
        # Write a minimal 1x1 transparent PNG if Pillow isn't available
        import base64
        minimal_png = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
        )
        path.write_bytes(minimal_png)


# ── Templates ──────────────────────────────────────────────────────────────


def _fdl_template(pascal: str, display: str) -> str:
    return f"""\
<?xml version="1.0" encoding="utf-8" ?>
<Feature xmlns="http://www.sila-standard.org"
         xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
         SiLA2Version="1.1"
         FeatureVersion="1.0"
         Originator="org.silastandard"
         Category="instruments"
         MaturityLevel="Draft">

    <Identifier>{pascal}</Identifier>
    <DisplayName>{display}</DisplayName>
    <Description>SiLA 2 feature for controlling the {display} instrument.</Description>

    <!-- ═══════════════════════════════════════════════════════════════
         TODO: Define your device commands here.

         Example command:
         <Command>
             <Identifier>Connect</Identifier>
             <DisplayName>Connect</DisplayName>
             <Description>Connect to the instrument.</Description>
             <Observable>No</Observable>
             <Parameter>
                 <Identifier>ConnectionString</Identifier>
                 <DisplayName>Connection String</DisplayName>
                 <Description>Connection string (e.g. COM port, IP address).</Description>
                 <DataType><Basic>String</Basic></DataType>
             </Parameter>
             <Response>
                 <Identifier>InstrumentName</Identifier>
                 <DisplayName>Instrument Name</DisplayName>
                 <Description>Name of the connected instrument.</Description>
                 <DataType><Basic>String</Basic></DataType>
             </Response>
             <DefinedExecutionError>
                 <Identifier>ConnectionFailed</Identifier>
                 <DisplayName>Connection Failed</DisplayName>
                 <Description>Failed to connect to the instrument.</Description>
             </DefinedExecutionError>
         </Command>
         ═══════════════════════════════════════════════════════════════ -->

    <!-- ═══════════════════════════════════════════════════════════════
         TODO: Define observable properties for real-time state push.

         Example:
         <Property>
             <Identifier>IsConnected</Identifier>
             <DisplayName>Is Connected</DisplayName>
             <Description>Whether the instrument is connected.</Description>
             <Observable>Yes</Observable>
             <DataType><Basic>Boolean</Basic></DataType>
         </Property>
         ═══════════════════════════════════════════════════════════════ -->

    <!-- ── DeviceStatus (REQUIRED — drives the WebUI via SSE) ──────── -->
    <Property>
        <Identifier>DeviceStatus</Identifier>
        <DisplayName>Device Status</DisplayName>
        <Description>Current device status as a JSON string with all state fields (for SSE streaming to WebUI).</Description>
        <Observable>Yes</Observable>
        <DataType><Basic>String</Basic></DataType>
    </Property>

    <!-- ── Standard Properties (REQUIRED for all servers) ─────────── -->
    <Property>
        <Identifier>DisplayIcon</Identifier>
        <DisplayName>Display Icon</DisplayName>
        <Description>Icon for the device, displayed in clients and dashboards.</Description>
        <Observable>No</Observable>
        <DataType><Basic>Binary</Basic></DataType>
    </Property>

    <Property>
        <Identifier>DeviceDescription</Identifier>
        <DisplayName>Device Description</DisplayName>
        <Description>Rich text description of the device, used as system prompt context for LLM/MCP integrations.</Description>
        <Observable>No</Observable>
        <DataType><Basic>String</Basic></DataType>
    </Property>

</Feature>
"""


def _init_template() -> str:
    return """\
from .server import Server

__all__ = ["Server"]
"""


def _main_template(snake: str, port: int) -> str:
    return f"""\
from sila_server_common.server_main import create_main
from .server import Server

main = create_main(
    Server,
    default_port={port},
    server_package="{snake}",
    log_filename="{snake}.log",
)

if __name__ == "__main__":
    import typer
    typer.run(main)
"""


def _server_template(snake: str, pascal: str, feature_lower: str, display: str, camera: bool = False) -> str:
    camera_imports = ""
    camera_registration = ""
    camera_sim_propagation = ""
    camera_auto_start = ""

    if camera:
        camera_imports = f"""
import importlib
from sila_server_common.feature_implementations.camerastreamprovider_impl import create_camerastreamprovider_impl
from sila_server_common.transports.camera_capture import load_camera_config
"""
        camera_registration = f"""
        # CameraStreamProvider (optional)
        csp_gen = importlib.import_module(f"{{self._server_package}}.generated.camerastreamprovider")
        CameraStreamProviderImpl = create_camerastreamprovider_impl(csp_gen)
        self.camerastreamprovider = CameraStreamProviderImpl(self)
        self.set_feature_implementation(csp_gen.CameraStreamProviderFeature, self.camerastreamprovider)
"""
        camera_sim_propagation = """        self.camerastreamprovider._simulation_mode = simulation_mode
"""
        camera_auto_start = f"""
    def _auto_start_camera(self) -> None:
        \"\"\"Auto-start camera if configured in camera.json.\"\"\"
        config = load_camera_config(self._server_package)
        if config and config.get("auto_start"):
            self.camerastreamprovider.auto_start(config)
"""

    return f"""\
from typing import Optional
from uuid import UUID

from sila_server_common.base_server import BaseInstrumentServer

from .feature_implementations.{feature_lower}_impl import {pascal}Impl
from .generated.{feature_lower} import {pascal}Feature
{camera_imports}

class Server(BaseInstrumentServer):
    def __init__(
        self,
        server_uuid: Optional[UUID] = None,
        name: Optional[str] = None,
        description: Optional[str] = None,
    ):
        if name is None:
            name = "{display}"
        if description is None:
            description = "{display} SiLA 2 instrument server"
        super().__init__(
            server_name=name,
            server_description=description,
            server_type="{pascal}",
            server_version="2.0",
            server_package="{snake}",
            server_uuid=server_uuid,
        )

        # Device-specific feature
        self.{feature_lower} = {pascal}Impl(self)
        self.set_feature_implementation({pascal}Feature, self.{feature_lower})
{camera_registration}
    def on_simulation_mode_changed(self, simulation_mode: bool) -> None:
        \"\"\"Propagate simulation mode to all features.\"\"\"
        super().on_simulation_mode_changed(simulation_mode)
        self.{feature_lower}._simulation_mode = simulation_mode
{camera_sim_propagation}\
        # TODO: Add device-specific disconnect/cleanup logic here.
        # Example: if connected to real hardware, disconnect before mode switch.
        self.{feature_lower}._push_device_status(
            "Entered simulation mode" if simulation_mode else "Entered real mode"
        )
{camera_auto_start}\
"""


def _device_impl_template(snake: str, pascal: str, feature_lower: str) -> str:
    return f"""\
\"\"\"TODO: Implement {pascal} device feature.

This is the only feature implementation you need to write.
All standard features (ScreenStreamer, MessagingClient, LockController, etc.)
are provided by sila_server_common.
\"\"\"
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING

from sila2.server import MetadataDict

from ..generated.{feature_lower} import (
    {pascal}Base,
    # TODO: Import your command responses and errors here, e.g.:
    # Connect_Responses,
    # ConnectionFailed,
)

if TYPE_CHECKING:
    from ..server import Server

logger = logging.getLogger(__name__)


class {pascal}Impl({pascal}Base):
    \"\"\"Implementation of the {pascal} SiLA 2 feature.\"\"\"

    def __init__(self, parent_server: Server) -> None:
        super().__init__(parent_server=parent_server)
        self._simulation_mode: bool = True
        self._activity_log: list[str] = []

    def start(self) -> None:
        super().start()
        self._push_device_status()

    def _push_device_status(self, activity: str | None = None) -> None:
        \"\"\"Push a full device status update via the DeviceStatus observable property.\"\"\"
        if activity:
            ts = time.strftime("%H:%M:%S")
            self._activity_log.append(f"[{{ts}}] {{activity}}")
            if len(self._activity_log) > 100:
                self._activity_log = self._activity_log[-100:]

        status = {{
            "simulationMode": self._simulation_mode,
            # TODO: Add your device state fields here, e.g.:
            # "isConnected": self._connected,
            # "firmwareVersion": self._firmware,
            "activityLog": self._activity_log[-50:],
        }}
        self.update_DeviceStatus(json.dumps(status))

    # ── Standard Properties ──────────────────────────────────────────

    def get_DisplayIcon(self, *, metadata: MetadataDict) -> bytes:
        icon_path = Path(__file__).parent.parent / "icon.png"
        return icon_path.read_bytes()

    def get_DeviceDescription(self, *, metadata: MetadataDict) -> str:
        return (
            "{pascal} SiLA 2 Server\\n"
            "\\n"
            "TODO: Add a rich text description of this device for LLM/MCP context.\\n"
            "Include available commands, typical workflows, and constraints."
        )

    # ── Device Commands ──────────────────────────────────────────────
    # TODO: Implement your device commands here.
    #
    # Example:
    # def Connect(self, ConnectionString: str, *, metadata: MetadataDict) -> Connect_Responses:
    #     logger.info("Connect: %s, simulation=%s", ConnectionString, self._simulation_mode)
    #     if self._simulation_mode:
    #         self._push_device_status(f"Connected to {{ConnectionString}} (simulated)")
    #         return Connect_Responses(InstrumentName="Simulated {pascal}")
    #     # Real hardware connection logic here
    #     ...
"""


def _webui_template(pascal: str, display: str, port: int) -> str:
    return f"""\
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{display} WebUI</title>
    <script src="https://unpkg.com/react@18/umd/react.production.min.js" crossorigin></script>
    <script src="https://unpkg.com/react-dom@18/umd/react-dom.production.min.js" crossorigin></script>
    <script src="https://unpkg.com/@babel/standalone/babel.min.js"></script>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #1a1a2e; color: #e0e0e0; }}
        .container {{ max-width: 1200px; margin: 0 auto; padding: 20px; }}
        .header {{ display: flex; align-items: center; justify-content: space-between; margin-bottom: 20px; padding: 16px; background: #16213e; border-radius: 8px; }}
        .header h1 {{ font-size: 1.4em; }}
        .status-badge {{ padding: 4px 12px; border-radius: 12px; font-size: 0.85em; font-weight: 600; }}
        .status-badge.connected {{ background: #2d6a4f; color: #b7e4c7; }}
        .status-badge.disconnected {{ background: #6b2c2c; color: #f4a6a6; }}
        .status-badge.sse {{ background: #1a535c; color: #a7d8de; margin-left: 8px; }}
        .card {{ background: #16213e; border-radius: 8px; padding: 20px; margin-bottom: 16px; }}
        .card h2 {{ font-size: 1.1em; margin-bottom: 12px; color: #7ec8e3; }}
        .activity-log {{ font-family: 'Consolas', monospace; font-size: 0.85em; max-height: 200px; overflow-y: auto; padding: 12px; background: #0f0f23; border-radius: 4px; }}
        .activity-log div {{ padding: 2px 0; color: #a0a0a0; }}
        .placeholder {{ text-align: center; padding: 40px; color: #666; }}
    </style>
</head>
<body>
<div id="root"></div>
<script type="text/babel" data-type="module">
const {{ useState, useEffect }} = React;

// Extract SiLA server host/port from iframe URL
const _urlParts = window.location.pathname.split('/');
const SILA_HOST = _urlParts[3] || 'localhost';
const SILA_PORT = _urlParts[4] || '{port}';
const API_BASE = `${{window.location.origin}}/api`;
const FEATURE_ID = '{pascal}';

function useDeviceStatus() {{
    const [status, setStatus] = useState({{
        simulationMode: true,
        activityLog: [],
    }});
    const [sseConnected, setSseConnected] = useState(false);

    useEffect(() => {{
        const url = `${{API_BASE}}/sse/${{SILA_HOST}}/${{SILA_PORT}}/${{FEATURE_ID}}/DeviceStatus`;
        const es = new EventSource(url);
        es.onopen = () => setSseConnected(true);
        es.onmessage = (event) => {{
            try {{
                const parsed = JSON.parse(event.data);
                const deviceStatus = typeof parsed === 'string' ? JSON.parse(parsed) : parsed;
                setStatus(deviceStatus);
            }} catch (e) {{}}
        }};
        es.onerror = () => setSseConnected(false);
        return () => es.close();
    }}, []);

    return {{ status, sseConnected }};
}}

function App() {{
    const {{ status, sseConnected }} = useDeviceStatus();

    return (
        <div className="container">
            <div className="header">
                <h1>{display}</h1>
                <div>
                    <span className={{`status-badge ${{status.simulationMode ? 'disconnected' : 'connected'}}`}}>
                        {{status.simulationMode ? 'SIMULATION' : 'REAL'}}
                    </span>
                    <span className="status-badge sse">
                        SSE {{sseConnected ? 'LIVE' : 'OFF'}}
                    </span>
                </div>
            </div>

            <div className="card">
                <h2>Device Controls</h2>
                <div className="placeholder">
                    TODO: Add your device-specific controls here.
                </div>
            </div>

            <div className="card">
                <h2>Activity Log</h2>
                <div className="activity-log">
                    {{(status.activityLog || []).slice().reverse().map((line, i) => (
                        <div key={{i}}>{{line}}</div>
                    ))}}
                    {{(!status.activityLog || status.activityLog.length === 0) && (
                        <div>No activity yet.</div>
                    )}}
                </div>
            </div>
        </div>
    );
}}

const root = ReactDOM.createRoot(document.getElementById('root'));
root.render(<App />);
</script>
</body>
</html>
"""


def _pyproject_template(snake: str) -> str:
    return f"""\
[project]
name = "{snake}"
version = "0.0.0"
requires-python = ">=3.10"
dependencies = [
    "sila2",
    "typer",
    "sila_server_common",
]

[build-system]
requires = ["setuptools>=61.0.0"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
include = ["{snake}*"]

[tool.setuptools.package-data]
"{snake}.generated" = [
    "*/*.sila.xml",
    "*/*.proto",
]
"""


def _deploy_bat_template(snake: str, display: str, port: int) -> str:
    return f"""\
@echo off
echo === {display} Server Deployment ===
echo.
echo Installing {snake} server...
pip install -e "%~dp0"
echo.
echo Adding firewall rule for port {port}...
netsh advfirewall firewall add rule name="{display} SiLA" dir=in action=allow protocol=TCP localport={port}
echo.
echo Done. Start the server with:
echo   python -m {snake} --insecure --port {port} -a 0.0.0.0 --verbose
pause
"""


def _start_bat_template(snake: str, port: int) -> str:
    return f"""\
@echo off
python -m {snake} --insecure --port {port} -a 0.0.0.0 --verbose
pause
"""


def _claude_md_template(snake: str, pascal: str, display: str, port: int) -> str:
    return f"""\
# {display} SiLA 2 Server

## What This Is
A SiLA 2 instrument server for the {display}. Part of the sila-testing platform.

## Architecture
This server uses the `sila_server_common` shared library. You only need to modify three files:
1. **`{pascal}.sila.xml`** -- Device FDL (commands, properties, errors)
2. **`{snake}/feature_implementations/{pascal.lower()}_impl.py`** -- Device feature implementation
3. **`{snake}/custom_ui.html`** -- React + Babel CDN WebUI

Everything else (LockController, SimulationController, ScreenStreamer, MessagingClient,
ServerLogProvider, ScriptRunner, WebUIProvider, UserManualProvider) is auto-registered
by `BaseInstrumentServer` from `sila_server_common`.

## Key Files
```
{snake}/
├── {pascal}.sila.xml                    # Device feature definition (edit this)
├── SimulationController.sila.xml       # Standard features (do not edit)
├── ScreenStreamer.sila.xml
├── MessagingClient.sila.xml
├── WebUIProvider.sila.xml
├── UserManualProvider.sila.xml
├── ServerLogProvider.sila.xml
├── ScriptRunner.sila.xml
├── pyproject.toml
├── deploy.bat
├── start_server.bat
└── {snake}/
    ├── __init__.py
    ├── __main__.py                      # Entry point (uses create_main from sila_server_common)
    ├── server.py                        # Server class (uses BaseInstrumentServer)
    ├── custom_ui.html                   # React WebUI (edit this)
    ├── icon.png                         # Device icon (replace with real icon)
    └── feature_implementations/
        └── {pascal.lower()}_impl.py     # Device implementation (edit this)
```

## Commands
```bash
# Run the server
python -m {snake} --insecure --port {port} --verbose

# Run with simulation mode
python -m {snake} --insecure --port {port} --verbose --simulation

# Validate compliance
python -m sila_server_common.validate servers/{snake}
```

## Patterns to Follow
- Every command must call `self._push_device_status("description")` after execution
- Support simulation mode: check `self._simulation_mode` in every command
- Use `self.update_PropertyName(value)` for observable properties (no getter methods)
- DeviceStatus is a JSON string observable property that drives the WebUI via SSE
- Raise Defined Execution Errors for invalid state (e.g., not connected, not primed)
- The WebUI connects to SSE at `/api/sse/<host>/<port>/{pascal}/DeviceStatus`

## Reference
- Full guide: `CREATING_SERVERS.md` in the project root
- Reference server: `servers/multidrop_combi/`
- Shared library: `packages/sila_server_common/`
"""


def main():
    parser = argparse.ArgumentParser(
        description="Generate a new SiLA 2 instrument server package",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Examples:
  python -m sila_server_common.scaffold --name centrifuge --port 50062
  python -m sila_server_common.scaffold --name vortex_mixer --port 50063 --feature VortexMixer
  python -m sila_server_common.scaffold --name liquid_handler --port 50064 -o /path/to/servers
""",
    )
    parser.add_argument("--name", "-n", required=True, help="Server name in snake_case (e.g. 'centrifuge')")
    parser.add_argument("--port", "-p", type=int, required=True, help="Default port number (e.g. 50062)")
    parser.add_argument("--feature", "-f", default=None, help="PascalCase feature name (default: derived from name)")
    parser.add_argument("--output-dir", "-o", default="servers", help="Output directory (default: servers/)")
    parser.add_argument("--camera", action="store_true", help="Include optional CameraStreamProvider feature")

    args = parser.parse_args()
    output_dir = Path(args.output_dir)

    generate_server(
        name=args.name,
        port=args.port,
        output_dir=output_dir,
        feature_name=args.feature,
        camera=args.camera,
    )

# Deploying SiLA 2 Servers

Each server includes a `deploy.bat` script for one-click deployment on Windows target machines.
The script is self-contained: it creates a virtual environment, installs the package, opens
the firewall port, and starts the server.

## Prerequisites

- **Python 3.10+** installed and in PATH on the target machine
- **Administrator access** (optional, for firewall rule creation)
- **Network access** to the target machine on the server's port

## Quick Start

1. Copy the server folder (e.g. `servers/venus_api/`) to the target machine
2. Double-click `deploy.bat` or run from a command prompt:

```batch
:: Default: simulation mode (no hardware needed)
deploy.bat

:: Real mode: connects to actual hardware
deploy.bat --real

:: Install only (don't start the server)
deploy.bat --install
```

## What deploy.bat Does

1. **Checks Python** - Verifies Python 3.10+ is installed and in PATH
2. **Creates venv** - Creates a `.venv/` virtual environment inside the server folder (skips if it already exists)
3. **Installs package** - Runs `pip install -e .` to install the server package and all its dependencies
4. **Opens firewall** - Adds a Windows Firewall inbound rule for the server's port (requires admin; warns if it can't)
5. **Starts server** - Launches the SiLA 2 server bound to `0.0.0.0` (all interfaces) with `--insecure` and `--verbose`

## Modes

| Flag | Description |
|------|-------------|
| (none) | Simulation mode - no hardware connection needed, returns simulated data |
| `--real` | Real mode - connects to actual hardware (serial port, REST API, COM, etc.) |
| `--install` | Install only - sets up venv and installs package, does not start the server |

## Server Ports

| Server | Port | Firewall Rule Name |
|--------|------|-------------------|
| Temperature Controller | 50052 | SiLA Temperature Controller |
| Pump Controller | 50053 | SiLA Pump Controller |
| Plate Reader | 50054 | SiLA Plate Reader |
| Multidrop Combi | 50055 | SiLA Multidrop Combi |
| Venus API | 50056 | SiLA Venus API |
| Barcode Scanner | 50057 | SiLA Barcode Scanner |
| Phenix Imager | 50058 | SiLA Phenix Imager |
| Micronic Tube Scanner | 50059 | SiLA Micronic Tube Scanner |

## Starting Manually

After running `deploy.bat --install`, you can start the server manually:

```batch
.venv\Scripts\python.exe -m <package_name> --insecure -a 0.0.0.0 -p <PORT> --verbose
```

For example:
```batch
.venv\Scripts\python.exe -m venus_api --insecure -a 0.0.0.0 -p 50056 --verbose
```

## Connecting from Another Machine

Once the server is running, connect to it from the Web UI or any SiLA 2 client using
the target machine's hostname or IP address and the server's port:

```
http://<hostname>:<port>
```

Add the server to the Web UI's `DEFAULT_SERVERS` list in `client_web_ui/app.py`:
```python
{"name": "Venus API (remote)", "host": "e372-w11-2428", "port": 50056},
```

## Troubleshooting

- **"Python is not installed"** - Install Python 3.10+ from https://python.org and ensure it's in PATH
- **"Could not add firewall rule"** - Right-click `deploy.bat` and select "Run as administrator"
- **"Installation failed"** - Check the pip output for missing system dependencies (e.g. pyserial, comtypes)
- **Server not reachable from other machines** - Verify the firewall rule was created, or manually add it:
  ```batch
  netsh advfirewall firewall add rule name="SiLA Server" dir=in action=allow protocol=tcp localport=50056
  ```

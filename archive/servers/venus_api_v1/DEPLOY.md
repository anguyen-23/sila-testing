# Venus API SiLA 2 Server - Deployment Guide

Deploy the Venus API SiLA 2 server on an instrument PC running Hamilton VENUS.

## Prerequisites

- **Python 3.10+** installed on the instrument PC
- **Hamilton VENUS** with the Web API option enabled
- VENUS Web API authentication mode set to **None** (no auth)
- Network access between the client PC and instrument PC on port 50056

## 1. Verify VENUS Web API

Open a browser on the instrument PC and check:

```
http://localhost:51745/api/vector/v2/system/version
```

You should get a JSON response with the VENUS version. If this fails, ensure VENUS is running and the Web API is enabled in VENUS configuration.

## 2. Install the Server

```bash
# Clone or copy the project to the instrument PC
git clone <repo-url>
cd keyser-sila-testing

# Create and activate a virtual environment
python -m venv .venv
source .venv/Scripts/activate    # Git Bash on Windows
# or: .venv\Scripts\activate.bat  # CMD

# Install dependencies
pip install -r requirements.txt
```

## 3. Start the Server

### Real mode (connects to VENUS)

```bash
python -m venus_api --insecure -a 0.0.0.0 -p 50056 --verbose
```

### Simulation mode (no VENUS needed)

```bash
python -m venus_api --insecure --simulation -a 0.0.0.0 -p 50056 --verbose
```

### Custom VENUS URL

If VENUS Web API runs on a non-default port:

```bash
python -m venus_api --insecure -a 0.0.0.0 -p 50056 --venus-url http://localhost:9999 --verbose
```

### Flags reference

| Flag | Default | Description |
|------|---------|-------------|
| `-a` / `--ip-address` | `127.0.0.1` | Bind address. Use `0.0.0.0` for network access |
| `-p` / `--port` | `50056` | SiLA server port |
| `--simulation` | off | Start in simulation mode |
| `--venus-url` | `http://localhost:51745` | VENUS Web API base URL |
| `--insecure` | off | Disable TLS (required for local dev) |
| `--verbose` | off | Enable info-level logging |

## 4. Windows Firewall

Allow inbound connections on the SiLA port:

```powershell
# Run as Administrator
netsh advfirewall firewall add rule name="SiLA Venus API" dir=in action=allow protocol=tcp localport=50056
```

## 5. Connect from a Client PC

### Option A: Web UI

Edit `client_web_ui/config.py` and add the instrument IP to `DEFAULT_SERVERS`:

```python
DEFAULT_SERVERS = [
    {"host": "192.168.1.100", "port": 50056, "insecure": True},
]
```

Then run the web UI: `python -m client_web_ui`

### Option B: Python SilaClient

```python
from sila2.client import SilaClient

client = SilaClient("192.168.1.100", 50056, insecure=True)
print(client.VenusMethodExecutor.BaseUrl)
```

## Troubleshooting

**"Cannot reach Venus Web API"**
- Verify VENUS is running and the Web API is enabled
- Check `http://localhost:51745/api/vector/v2/system/version` in a browser
- Ensure `--venus-url` matches the actual VENUS API port

**Connection refused from client PC**
- Confirm the server was started with `-a 0.0.0.0` (not the default `127.0.0.1`)
- Check Windows Firewall allows port 50056
- Verify network connectivity: `ping <instrument-ip>` from the client PC

**Server starts but commands fail**
- Check the VENUS authentication mode is set to `None`
- Look at server logs (`--verbose`) for detailed error messages
- Ensure no other process is using port 50056

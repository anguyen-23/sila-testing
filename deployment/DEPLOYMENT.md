# SiLA 2 Server Deployment with Ansible

Central deployment system for managing SiLA 2 servers across Windows and Linux instrument PCs.

## Architecture

```
┌─────────────────────────────────────┐
│  Control Node (this dev PC / WSL2)  │
│  - Ansible installed in venv        │
│  - Inventory of all target PCs      │
│  - Playbooks for deploy/update      │
└──────────┬──────────────────────────┘
           │
     ┌─────┴──────┐
     │  WinRM/SSH  │
     └─────┬──────┘
           │
  ┌────────┼──────────────────────┐
  │        │                      │
  ▼        ▼                      ▼
┌──────┐ ┌──────┐            ┌──────┐
│ PC 1 │ │ PC 2 │    ...     │ PC N │
│ Win  │ │ Win  │            │ Linux│
│Venus │ │Phenix│            │Temp  │
└──────┘ └──────┘            └──────┘
```

**Control node**: Your dev machine running WSL2 + Ansible. This is the only machine that needs Ansible or WSL2.

**Target PCs**: Instrument/control PCs. They only need:
- Windows: WinRM enabled (built-in, just needs config) + Python 3.10+
- Linux: SSH server running (usually already there) + Python 3.10+

## Prerequisites

### One-time: Control Node Setup (WSL2)

```bash
# In WSL2 (Ubuntu)
python3 -m venv ~/.ansible-venv
source ~/.ansible-venv/bin/activate
pip install ansible pywinrm

# Verify
ansible --version
```

Add to `~/.bashrc` for convenience:
```bash
alias ansible-env='source ~/.ansible-venv/bin/activate'
```

#### Ansible Vault (credential storage)

Credentials are stored encrypted using Ansible Vault. One-time setup:

```bash
# Set the ANSIBLE_CONFIG env var (required because /mnt/c/ is world-writable)
export ANSIBLE_CONFIG=/mnt/c/Users/keyser/source/repos/keyser-sila-testing/deployment/ansible.cfg

# Add to ~/.bashrc to make it permanent
echo 'export ANSIBLE_CONFIG=/mnt/c/Users/keyser/source/repos/keyser-sila-testing/deployment/ansible.cfg' >> ~/.bashrc

# Create the vault password file (Ansible reads this automatically)
echo 'your-vault-password' > ~/.ansible-vault-pass
chmod 600 ~/.ansible-vault-pass

# Create the encrypted credentials file
cd /mnt/c/Users/keyser/source/repos/keyser-sila-testing/deployment
export EDITOR=nano  # optional, default is vi
ansible-vault create inventory/group_vars/windows/vault.yml
```

In the vault editor, enter:
```yaml
vault_ansible_user: YOUR_WINDOWS_USERNAME
vault_ansible_password: YOUR_WINDOWS_PASSWORD
```

The vault file is git-ignored and never committed.

### One-time: Windows Target Setup

Each Windows target PC needs WinRM enabled. Run this once as Administrator in PowerShell:

```powershell
# Enable WinRM with basic auth (for local network / lab use)
winrm quickconfig -q
winrm set winrm/config/service '@{AllowUnencrypted="true"}'
winrm set winrm/config/service/auth '@{Basic="true"}'

# If needed, allow connections from your control node's subnet
# netsh advfirewall firewall add rule name="WinRM" dir=in action=allow protocol=TCP localport=5985
```

For production/secure networks, use HTTPS (port 5986) with certificates instead.

### One-time: Linux Target Setup

Usually no setup needed — just ensure SSH is running and you have credentials.

## Directory Structure

```
deployment/
├── DEPLOYMENT.md             # This file
├── ansible.cfg               # Ansible settings (inventory path, defaults)
├── inventory/
│   ├── hosts.yml             # All target machines, grouped by server type
│   └── group_vars/
│       ├── all.yml           # Shared vars (Python path, venv location, etc.)
│       ├── all/
│       │   └── vault.yml     # Shared secrets: Tailscale auth key (git-ignored)
│       ├── windows/
│       │   ├── main.yml      # WinRM connection settings
│       │   └── vault.yml     # Encrypted credentials (git-ignored)
│       └── linux.yml         # SSH connection settings
├── playbooks/
│   ├── deploy.yml            # Full deploy: install deps + copy code + start service
│   ├── update.yml            # Update code + restart service (faster than full deploy)
│   ├── uninstall.yml         # Stop service, remove registration, delete server files
│   ├── status.yml            # Report what's installed and running across fleet
│   ├── tailscale.yml         # Install and authenticate Tailscale on targets
│   └── headscale.yml         # Deploy Headscale control server on WSL2
├── roles/
│   ├── sila_server/
│   │   ├── handlers/
│   │   │   └── main.yml      # Service restart handler (Linux)
│   │   ├── tasks/
│   │   │   ├── main.yml      # Orchestrator (routes to Windows or Linux tasks)
│   │   │   ├── windows.yml   # Windows: create venv, pip install, nssm service
│   │   │   └── linux.yml     # Linux: create venv, pip install, systemd service
│   │   ├── templates/
│   │   │   ├── sila-server.service.j2   # systemd unit file template
│   │   │   └── run-server.bat.j2        # Windows batch file to run the server
│   │   └── vars/
│   │       └── main.yml      # Role defaults (install paths, service names)
│   ├── tailscale/
│   │   ├── tasks/
│   │   │   ├── main.yml      # Orchestrator (routes to Windows or Linux tasks)
│   │   │   ├── windows.yml   # Install via winget, authenticate with auth key
│   │   │   └── linux.yml     # Install via official script, authenticate
│   │   └── vars/
│   │       └── main.yml      # Auth key from vault + login server URL
│   └── headscale/
│       ├── tasks/
│       │   └── main.yml      # Install Headscale, configure, create user + pre-auth key
│       ├── templates/
│       │   └── config.yaml.j2  # Headscale server config (SQLite, DERP, DNS)
│       ├── handlers/
│       │   └── main.yml      # Restart handler for config changes
│       └── vars/
│           └── main.yml      # Version, ports, paths, user namespace
├── admin_console/            # Flask web app for fleet management (port 5001)
│   ├── app.py                # Routes, API endpoints, wizard pages
│   ├── inventory.py          # Parses hosts.yml for dashboard display
│   ├── ansible_runner.py     # Runs playbooks in background, streams output via SSE
│   └── templates/            # Dashboard, job output, setup wizards
└── screen_capture_helper/    # User-session helper for service-mode capture
```

## Usage

All commands run from WSL2, from this `deployment/` directory.

### Test connectivity

```bash
# Ping a specific host
ansible e372-w11-2428 -m win_ping

# Ping all hosts
ansible all -m ping
```

### Deploy a server to all its targets

```bash
# Deploy venus_api to all PCs in the [venus_api] group
ansible-playbook playbooks/deploy.yml -l venus_api

# Deploy ALL servers to ALL targets
ansible-playbook playbooks/deploy.yml

# Deploy to a single specific host
ansible-playbook playbooks/deploy.yml -l e372-w11-2428
```

### Push an update (code only, faster)

```bash
ansible-playbook playbooks/update.yml -l venus_api
```

### Uninstall a server

```bash
# Uninstall venus_api from all PCs in the [venus_api] group
ansible-playbook playbooks/uninstall.yml -l venus_api

# Uninstall from a single specific host
ansible-playbook playbooks/uninstall.yml -l e372-w11-2428

# Also remove the shared screen capture helper (only when removing the last server from a host)
ansible-playbook playbooks/uninstall.yml -l venus_api -e remove_helper=true
```

This stops and removes the service (nssm on Windows, systemd on Linux) and deletes the server directory. The screen capture helper is shared across all servers on a machine, so it is left in place by default.

### Check fleet status

```bash
ansible-playbook playbooks/status.yml
```

### Add a new target PC

1. On the target, enable WinRM (Windows) or SSH (Linux) — see Prerequisites above
2. On the target, install nssm (Windows): `winget install nssm`
3. On the target, add a firewall rule for the SiLA port (Windows): `netsh advfirewall firewall add rule name="SiLA <port>" dir=in action=allow protocol=TCP localport=<port>`
4. Add the host to `inventory/hosts.yml` under the appropriate server group
5. Run `ansible-playbook playbooks/deploy.yml -l <new-host>`

### Add a new server type

1. Add a new group in `inventory/hosts.yml` with `sila_package` and `sila_port` vars
2. Add the group to the `windows` or `linux` platform group
3. Run `ansible-playbook playbooks/deploy.yml -l <new-group>`

## How It Works

1. **Deploy playbook** connects to target via WinRM (Windows) or SSH (Linux)
2. Copies the server package from this repo to the target at `C:\SiLA2\<package>` (Windows) or `/opt/sila2/<package>` (Linux)
3. Creates a Python virtual environment and installs dependencies via pip
4. Generates a run script (`run-server.bat` on Windows)
5. Registers the server as a system service (nssm on Windows, systemd on Linux)
6. Starts the service

Updates follow the same flow but skip the initial setup steps — just sync code and restart.

## Target Install Layout

After deployment, each target PC has:

```
C:\SiLA2\venus_api\           # (or /opt/sila2/venus_api on Linux)
├── venus_api/                # Server package (copied from repo)
├── .venv/                    # Python virtual environment
├── requirements.txt          # Dependencies
├── pyproject.toml            # Package metadata
└── run-server.bat            # Generated startup script
```

## Windows Service (nssm)

To run servers as Windows services (auto-start on boot, run without login):

1. Install nssm on the target PC: `winget install nssm`
2. Verify the install path: `where.exe nssm` — update `nssm_path` in `inventory/group_vars/windows/main.yml` if different
3. Re-run the deploy playbook — it will automatically register and start the service

The service will be named `sila-<package_name>` (e.g., `sila-venus_api`).

### Firewall

Each target PC needs an inbound firewall rule for its SiLA port. Run in PowerShell as Administrator:

```powershell
netsh advfirewall firewall add rule name="SiLA 50056" dir=in action=allow protocol=TCP localport=50056
```

## Screen Capture Helper

SiLA servers run as Windows services in Session 0, which cannot access the
interactive desktop. To enable the ScreenStreamer feature, a lightweight HTTP
helper runs in the user's session and proxies window enumeration and capture.

- **Location**: `C:\SiLA2\screen_capture_helper\`
- **Listens on**: `127.0.0.1:8766` (localhost only)
- **Registered as**: Scheduled task "SiLA Screen Capture Helper" (runs at logon)
- **Deployed automatically** by the Ansible deploy playbook

The SiLA server's ScreenStreamer tries the helper first. If the helper isn't
running (e.g., local dev), it falls back to direct Win32 capture.

## Tailscale VPN

Tailscale creates a secure mesh VPN across your fleet, enabling the Cloud Run web UI to reach on-prem SiLA servers without exposing ports to the internet.

Two control plane options are supported:

| Option | Description |
|--------|-------------|
| **Headscale** (self-hosted) | Open-source Tailscale control server running on your WSL2 instance. No external account needed. |
| **Tailscale SaaS** | Managed control plane at login.tailscale.com. Easier setup, requires a Tailscale account. |

### Option A: Headscale (self-hosted control plane)

Headscale is an open-source, self-hosted implementation of the Tailscale control server.
In this setup, Headscale runs on your WSL2 instance and all Tailscale clients register with it.

#### Step 1: Deploy Headscale on WSL2

```bash
cd /mnt/c/Users/keyser/source/repos/keyser-sila-testing/deployment
export ANSIBLE_CONFIG=$(pwd)/ansible.cfg

ansible-playbook playbooks/headscale.yml --ask-become-pass
```

This installs Headscale (v0.25.1 .deb), creates a `sila` user namespace, and generates a
reusable pre-auth key. The output will show:
- The pre-auth key (for clients)
- The Headscale server URL (e.g., `http://172.x.x.x:8080`)

#### Step 2: Store the pre-auth key in vault

```bash
# Create or edit the shared vault file
ansible-vault create inventory/group_vars/all/vault.yml   # first time
ansible-vault edit inventory/group_vars/all/vault.yml      # subsequent

# Add:
#   vault_tailscale_auth_key: "<pre-auth key from step 1>"
```

#### Step 3: Set the Headscale server URL

Edit `inventory/group_vars/all.yml` and uncomment/set:

```yaml
headscale_server_url: "http://<WSL2_IP>:8080"
```

When this variable is set, the Tailscale role automatically adds `--login-server` to
point clients at your Headscale instance instead of Tailscale SaaS.

#### Step 4: Deploy Tailscale clients

```bash
ansible-playbook playbooks/tailscale.yml              # all hosts
ansible-playbook playbooks/tailscale.yml -l venus_api # one group
```

#### Managing Headscale

```bash
# List registered nodes
sudo headscale nodes list

# List pre-auth keys
sudo headscale preauthkeys list --user sila

# Generate a new pre-auth key (expires in 30 days)
sudo headscale preauthkeys create --user sila --reusable --expiration 720h

# Remove a node
sudo headscale nodes delete -i <NODE_ID>
```

#### WSL2 IP caveat

The WSL2 IP address can change on reboot. For a stable setup:
- **Port forwarding**: Use `netsh interface portproxy` on Windows to forward a fixed port to WSL2
- **Static IP**: Configure a static IP in `.wslconfig`
- **Move Headscale**: Deploy to a machine with a stable IP when ready for production use

### Option B: Tailscale SaaS (managed control plane)

1. Create a free account at [login.tailscale.com](https://login.tailscale.com)
2. Generate a reusable, pre-approved auth key at **Settings > Keys**
3. Store the key in vault (same as Option A, Step 2)
4. Make sure `headscale_server_url` is **not set** (commented out) in `group_vars/all.yml`
5. Deploy Tailscale to the fleet:

```bash
ansible-playbook playbooks/tailscale.yml              # all hosts
ansible-playbook playbooks/tailscale.yml -l venus_api # one group
```

### Verify

```bash
# Check Tailscale IPs via the status playbook
ansible-playbook playbooks/status.yml
# Output includes TailscaleIP=100.x.y.z for each host
```

### How it works

- **Windows**: Installed via `winget install Tailscale.Tailscale`, authenticated with the pre-auth key
- **Linux**: Installed via the official Tailscale install script, authenticated with the pre-auth key
- When `headscale_server_url` is set, `--login-server` is added to `tailscale up` so clients register with Headscale
- Each host gets a stable `100.x.y.z` Tailscale IP
- SiLA servers are reachable at their Tailscale IP + port (e.g., `100.64.1.5:50056`)

## Cloud Run Deployment

The Client Web UI can be deployed to Google Cloud Run with Tailscale for VPN access to on-prem servers.

### Files

- `Dockerfile` — Python 3.13-slim with Tailscale, gunicorn, client-only deps
- `entrypoint.sh` — Starts tailscaled in userspace networking mode, authenticates, then runs gunicorn
- `.dockerignore` — Excludes servers, .venv, .git, docs
- `client_web_ui/requirements-cloud.txt` — Minimal deps (no pywin32/pyserial/opencv)
- `client_web_ui/wsgi.py` — Gunicorn entry point

### Deploy

```bash
# Build container image
gcloud builds submit --tag gcr.io/YOUR_PROJECT/sila-web-ui

# Deploy to Cloud Run
gcloud run deploy sila-web-ui \
  --image gcr.io/YOUR_PROJECT/sila-web-ui \
  --platform managed \
  --region us-central1 \
  --allow-unauthenticated \
  --set-env-vars "TS_AUTHKEY=tskey-auth-...,GEMINI_API_KEY=..."
```

### Limitations

- The WebSocket message server (port 8765) is internal-only — lab instruments can't push messages to it
- The `custom_servers.json` file is ephemeral in the container — use the "Add Server" UI each time or update `DEFAULT_SERVERS` in `app.py` with Tailscale IPs

## Admin Console

A Flask web app for managing the SiLA fleet from a browser. Runs on the Ansible control node (WSL2).

### Features

- **Fleet dashboard** — visual grid of all hosts with platform, package, and port info
- **One-click actions** — deploy, update, uninstall, status check, and Tailscale install per host or for all hosts
- **Live job output** — ansible-playbook output streamed to the browser via SSE with syntax highlighting
- **Job history** — recent jobs with status, duration, and output viewer
- **Setup wizards** — step-by-step guides for Tailscale setup, Cloud Run deployment, and adding new hosts

### Run

```bash
cd deployment
pip install flask pyyaml
python -m admin_console
# Open http://localhost:5001
```

## Security Notes

- WinRM basic auth over HTTP is fine for isolated lab networks
- For networks with external access, switch to HTTPS (port 5986) with certificates
- Credentials are encrypted with Ansible Vault — the vault file is git-ignored
- The vault password file (`~/.ansible-vault-pass`) should only be readable by your user (`chmod 600`)
- Tailscale auth keys should be stored in Ansible Vault, never committed to git

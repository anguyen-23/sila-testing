#!/bin/sh
set -e

# Start Tailscale daemon in userspace networking mode (no TUN device needed
# in containerised environments like Cloud Run).
tailscaled --state=/var/lib/tailscale/tailscaled.state \
           --socket=/var/run/tailscale/tailscaled.sock \
           --tun=userspace-networking &

# Wait for the daemon socket to be ready
timeout=30
while [ ! -S /var/run/tailscale/tailscaled.sock ] && [ "$timeout" -gt 0 ]; do
  sleep 1
  timeout=$((timeout - 1))
done

# Authenticate if TS_AUTHKEY is set
if [ -n "$TS_AUTHKEY" ]; then
  tailscale up --authkey="$TS_AUTHKEY" --hostname=sila-web-ui
  echo "Tailscale connected. IP: $(tailscale ip -4)"
else
  echo "WARNING: TS_AUTHKEY not set — Tailscale not connected."
  echo "Set TS_AUTHKEY env var to a Tailscale auth key to enable VPN."
fi

# Start the Flask app via gunicorn
exec gunicorn \
  --bind "0.0.0.0:${PORT:-8080}" \
  --workers 2 \
  --threads 4 \
  --timeout 120 \
  "client_web_ui.wsgi:app"

#!/usr/bin/env bash
# Launches all SiLA 2 servers and the client web UI.
# Usage: ./start_all.sh
# Press Ctrl+C to stop everything.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Activate virtual environment
if [ -f .venv/Scripts/activate ]; then
    source .venv/Scripts/activate
elif [ -f .venv/bin/activate ]; then
    source .venv/bin/activate
else
    echo "ERROR: Could not find .venv. Run: python -m venv .venv && pip install -r requirements.txt"
    exit 1
fi

PIDS=()

cleanup() {
    echo ""
    echo "Stopping all processes..."
    for pid in "${PIDS[@]}"; do
        kill "$pid" 2>/dev/null || true
    done
    wait 2>/dev/null
    echo "All stopped."
}
trap cleanup EXIT INT TERM

echo "=== Starting SiLA 2 servers ==="

python -m temperature_controller --insecure --port 50052 &
PIDS+=($!)
echo "  Temperature Controller  -> port 50052  (PID $!)"

python -m pump_controller --insecure --port 50053 &
PIDS+=($!)
echo "  Pump Controller         -> port 50053  (PID $!)"

python -m plate_reader --insecure --port 50054 &
PIDS+=($!)
echo "  Plate Reader            -> port 50054  (PID $!)"

python -m multidrop_combi --insecure --port 50055 &
PIDS+=($!)
echo "  Multidrop Combi         -> port 50055  (PID $!)"

python -m venus_api --insecure --port 50056 &
PIDS+=($!)
echo "  Venus API               -> port 50056  (PID $!)"

python -m barcode_scanner --insecure --port 50057 &
PIDS+=($!)
echo "  Barcode Scanner         -> port 50057  (PID $!)"

python -m phenix_imager --insecure --port 50058 &
PIDS+=($!)
echo "  Phenix Imager           -> port 50058  (PID $!)"

python -m micronic_tube_scanner --insecure --port 50059 &
PIDS+=($!)
echo "  Micronic Tube Scanner   -> port 50059  (PID $!)"

echo ""
echo "=== Starting Client Web UI ==="
python -m client_web_ui &
PIDS+=($!)
echo "  Web UI                  -> http://localhost:5000  (PID $!)"

echo ""
echo "Everything is running. Press Ctrl+C to stop."
wait

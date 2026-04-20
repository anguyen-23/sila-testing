"""WSGI entry point for production deployment (gunicorn / Cloud Run)."""
from .app import create_app
from .message_server import start_ws_server

# Start the messaging WebSocket server in a background thread.
# Note: On Cloud Run only the main HTTP port is exposed, so the WS server
# (port 8765) won't be reachable from outside the container.  It still
# works for the messages UI within the same container.
start_ws_server(port=8765)

app = create_app()

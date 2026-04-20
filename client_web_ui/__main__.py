"""Run the SiLA 2 Client Web UI."""
from .app import create_app
from .message_server import start_ws_server

# Start the messaging WebSocket server on port 8765
start_ws_server(port=8765)

app = create_app()
# use_reloader=False avoids Flask spawning two processes which causes
# a port conflict on the WS server (port 8765).
app.run(host="0.0.0.0", port=5000, debug=True, use_reloader=False)

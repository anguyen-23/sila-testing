"""Flask app for browsing and interacting with SiLA 2 servers.

This is a learning tool -- a universal SiLA 2 client that can discover servers,
browse their features, execute commands, and subscribe to properties.
Not intended for production use.
"""
from __future__ import annotations

import base64
import json
import logging
import math
import os
import threading
import time
from datetime import timedelta
from typing import Any, Dict, List, Optional, Tuple

from dotenv import load_dotenv
from flask import Flask, Response, jsonify, make_response, render_template, request

from sila2.client import SilaClient
from sila2.framework.data_types.constrained import Constrained
from sila2.framework.constraints.minimal_inclusive import MinimalInclusive
from sila2.framework.constraints.maximal_inclusive import MaximalInclusive
from sila2.framework.errors.defined_execution_error import DefinedExecutionError
from sila2.framework.errors.validation_error import ValidationError

load_dotenv()
log = logging.getLogger(__name__)

# ── SiLA type → JSON Schema mapping ──────────────────────────────────

_SILA_TYPE_MAP: Dict[str, str] = {
    "String": "string",
    "Integer": "integer",
    "Real": "number",
    "Boolean": "boolean",
    "Binary": "string",
    "Date": "string",
    "Time": "string",
    "Timestamp": "string",
    "Any": "string",
}


def _build_json_schema(parameters) -> Dict[str, Any]:
    """Convert SiLA command parameters to a JSON Schema 'object' dict."""
    if not parameters:
        return {"type": "object", "properties": {}}
    props = {}
    required = []
    for p in parameters:
        identifier = p._identifier
        dt = getattr(p, "data_type", None) or getattr(p, "_data_type", None)
        type_name = type(dt).__name__ if dt else "String"
        schema: Dict[str, Any] = {"type": _SILA_TYPE_MAP.get(type_name, "string")}

        description = getattr(p, "_description", "")
        if description:
            schema["description"] = description

        # Extract constraints from Constrained wrappers
        if isinstance(dt, Constrained):
            for c in dt.constraints:
                if isinstance(c, MinimalInclusive):
                    schema["minimum"] = c.reference_value
                elif isinstance(c, MaximalInclusive):
                    schema["maximum"] = c.reference_value

        props[identifier] = schema
        required.append(identifier)

    return {"type": "object", "properties": props, "required": required}


# Features to skip when building Gemini tools (not useful for LLM interaction)
_SKIP_FEATURES = {"SiLAService", "LockController", "SimulationController", "WebUIProvider", "UserManualProvider", "CameraStreamProvider"}


# ── Server connection management ──────────────────────────────────────

# Configured servers (host, port, insecure)
DEFAULT_SERVERS = [
    {"name": "Temperature Controller", "host": "127.0.0.1", "port": 50052},
    {"name": "Pump Controller", "host": "127.0.0.1", "port": 50053},
    {"name": "Plate Reader", "host": "127.0.0.1", "port": 50054},
    {"name": "Multidrop Combi", "host": "127.0.0.1", "port": 50055},
    {"name": "Venus API", "host": "127.0.0.1", "port": 50056},
    {"name": "Venus API (e372)", "host": "e372-w11-2428", "port": 50056},
    {"name": "Barcode Scanner", "host": "127.0.0.1", "port": 50057},
    {"name": "Phenix Imager", "host": "127.0.0.1", "port": 50058},
    {"name": "Micronic Tube Scanner", "host": "127.0.0.1", "port": 50059},
    {"name": "xArm 6", "host": "127.0.0.1", "port": 50060},
]

# Custom servers added at runtime, persisted to a JSON file
_CUSTOM_SERVERS_FILE = os.path.join(os.path.dirname(__file__), "custom_servers.json")


def _load_custom_servers() -> List[Dict[str, Any]]:
    """Load user-added servers from the JSON file."""
    try:
        with open(_CUSTOM_SERVERS_FILE, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _save_custom_servers(servers: List[Dict[str, Any]]) -> None:
    """Persist user-added servers to JSON file."""
    with open(_CUSTOM_SERVERS_FILE, "w") as f:
        json.dump(servers, f, indent=2)


def get_all_servers() -> List[Dict[str, Any]]:
    """Return default servers + any user-added custom servers."""
    return DEFAULT_SERVERS + _load_custom_servers()

# Active client connections keyed by "host:port"
_clients: Dict[str, SilaClient] = {}
_clients_lock = threading.Lock()


def _client_key(host: str, port: int) -> str:
    return f"{host}:{port}"


def get_client(host: str, port: int) -> Optional[SilaClient]:
    """Get or create a SiLA client connection."""
    key = _client_key(host, port)
    with _clients_lock:
        if key in _clients:
            return _clients[key]
    try:
        client = SilaClient(host, port, insecure=True)
        with _clients_lock:
            _clients[key] = client
        return client
    except Exception:
        return None


def reconnect_client(host: str, port: int) -> Optional[SilaClient]:
    """Drop cached client and create a fresh connection."""
    key = _client_key(host, port)
    with _clients_lock:
        _clients.pop(key, None)
    return get_client(host, port)


def get_server_info(host: str, port: int) -> Dict[str, Any]:
    """Get server metadata via SiLAService."""
    client = get_client(host, port)
    if client is None:
        return {"connected": False, "host": host, "port": port}

    try:
        svc = client.SiLAService
        features = svc.ImplementedFeatures.get()
        return {
            "connected": True,
            "host": host,
            "port": port,
            "name": svc.ServerName.get(),
            "type": svc.ServerType.get(),
            "uuid": svc.ServerUUID.get(),
            "description": svc.ServerDescription.get(),
            "features": [str(f) for f in features],
        }
    except Exception as e:
        # Connection died, remove stale client
        with _clients_lock:
            _clients.pop(_client_key(host, port), None)
        return {"connected": False, "host": host, "port": port, "error": str(e)}


def get_feature_details(client: SilaClient, feature_id: str) -> Dict[str, Any]:
    """Introspect a feature to get its commands, properties, and metadata.

    The ClientFeature object has _unobservable_commands, _observable_commands,
    _unobservable_properties, _observable_properties as dicts of framework objects.
    """
    feature = getattr(client, feature_id, None)
    if feature is None:
        return {"error": f"Feature '{feature_id}' not found"}

    commands = []
    for cmd_id, cmd in {**feature._unobservable_commands, **feature._observable_commands}.items():
        params = []
        for p in cmd.parameters:
            params.append({
                "identifier": p._identifier,
                "display_name": p._display_name,
                "description": getattr(p, '_description', ''),
                "type": _type_name(p),
            })
        responses = []
        if hasattr(cmd, 'responses') and cmd.responses is not None:
            for r in cmd.responses:
                responses.append({
                    "identifier": r._identifier,
                    "display_name": getattr(r, '_display_name', r._identifier),
                    "type": _type_name(r),
                })
        commands.append({
            "identifier": cmd_id,
            "display_name": cmd._display_name,
            "description": getattr(cmd, '_description', ''),
            "observable": cmd_id in feature._observable_commands,
            "parameters": params,
            "responses": responses,
        })

    properties = []
    for prop_id, prop in {**feature._unobservable_properties, **feature._observable_properties}.items():
        properties.append({
            "identifier": prop_id,
            "display_name": prop._display_name,
            "description": getattr(prop, '_description', ''),
            "observable": prop_id in feature._observable_properties,
            "type": _type_name(prop),
        })

    return {
        "identifier": feature_id,
        "display_name": feature._display_name,
        "description": getattr(feature, '_description', ''),
        "commands": commands,
        "properties": properties,
    }


def _type_name(node) -> str:
    """Get a human-readable type name from a SiLA parameter/property/response node."""
    try:
        # Framework objects use data_type (public) not _data_type
        dt = getattr(node, 'data_type', None) or getattr(node, '_data_type', None)
        if dt is not None:
            return type(dt).__name__
    except Exception:
        pass
    return "unknown"


# SiLA basic type name → JSON Schema type
_SILA_TYPE_MAP = {
    "Integer": "integer",
    "Real": "number",
    "String": "string",
    "Boolean": "boolean",
    "Binary": "string",  # base64-encoded
}


def _build_json_schema(parameters) -> Dict[str, Any]:
    """Convert SiLA parameter metadata into a JSON Schema object."""
    properties: Dict[str, Any] = {}
    required: List[str] = []

    for p in parameters:
        dt = p.data_type
        prop: Dict[str, Any] = {}

        if isinstance(dt, Constrained):
            base_name = type(dt.base_type).__name__
            prop["type"] = _SILA_TYPE_MAP.get(base_name, "string")
            for con in dt.constraints:
                if isinstance(con, MinimalInclusive):
                    prop["minimum"] = con.reference_value
                elif isinstance(con, MaximalInclusive):
                    prop["maximum"] = con.reference_value
        else:
            type_name = type(dt).__name__
            prop["type"] = _SILA_TYPE_MAP.get(type_name, "string")

        desc = getattr(p, '_description', '')
        if desc:
            prop["description"] = desc

        properties[p._identifier] = prop
        required.append(p._identifier)

    return {
        "type": "object",
        "properties": properties,
        "required": required,
    }


# ── Flask app ─────────────────────────────────────────────────────────

def create_app() -> Flask:
    app = Flask(__name__)

    @app.route("/")
    def index():
        # Render page immediately with config only — no blocking connections.
        # JavaScript will fetch each server's status asynchronously.
        return render_template("index.html", servers=get_all_servers())

    @app.route("/api/server-info/<host>/<int:port>")
    def api_server_info(host: str, port: int):
        """Get a single server's status. Called async from the index page."""
        info = get_server_info(host, port)
        return jsonify(info)

    @app.route("/server/<host>/<int:port>")
    def server_detail(host: str, port: int):
        info = get_server_info(host, port)
        if not info.get("connected"):
            return render_template("server_offline.html", info=info)

        client = get_client(host, port)
        feature_details = []
        for fqi in info["features"]:
            # Extract feature identifier from FQI (e.g. "calico.automation/extended/TemperatureController/v1" -> "TemperatureController")
            parts = fqi.split("/")
            if len(parts) >= 3:
                feat_id = parts[-2]
            else:
                feat_id = parts[-1]
            details = get_feature_details(client, feat_id)
            details["fqi"] = fqi
            feature_details.append(details)

        # Check if server provides a custom UI
        has_custom_ui = any(
            "WebUIProvider" in fqi for fqi in info["features"]
        )
        # Check if server provides a user manual
        has_user_manual = any(
            "UserManualProvider" in fqi for fqi in info["features"]
        )
        # Check if server provides a camera stream
        has_camera = any(
            "CameraStreamProvider" in fqi for fqi in info["features"]
        )

        return render_template(
            "server_detail.html", info=info, features=feature_details,
            has_custom_ui=has_custom_ui, has_user_manual=has_user_manual,
            has_camera=has_camera,
        )

    @app.route("/api/property/<host>/<int:port>/<feature_id>/<property_id>")
    def api_get_property(host: str, port: int, feature_id: str, property_id: str):
        client = get_client(host, port)
        if client is None:
            return jsonify({"error": "Not connected"}), 503
        try:
            feature = getattr(client, feature_id)
            prop = getattr(feature, property_id)
            value = prop.get()
            value = _serialize(value)
            return jsonify({"value": value, "property": property_id})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/api/icon/<host>/<int:port>")
    def api_get_icon(host: str, port: int):
        """Serve a display icon from the first feature that exposes DisplayIcon."""
        client = get_client(host, port)
        if client is None:
            return Response(status=404)
        try:
            # Check each feature for a DisplayIcon property
            svc = client.SiLAService
            features = svc.ImplementedFeatures.get()
            for fqi in features:
                parts = str(fqi).split("/")
                feat_id = parts[-2] if len(parts) >= 3 else parts[-1]
                feature = getattr(client, feat_id, None)
                if feature is None:
                    continue
                if "DisplayIcon" in feature._unobservable_properties:
                    icon_bytes = feature.DisplayIcon.get()
                    resp = make_response(icon_bytes)
                    resp.headers["Content-Type"] = "image/png"
                    resp.headers["Cache-Control"] = "public, max-age=3600"
                    return resp
            return Response(status=404)
        except Exception:
            return Response(status=404)

    @app.route("/api/custom-ui/<host>/<int:port>")
    def api_custom_ui(host: str, port: int):
        """Serve the custom UI HTML from a server's WebUIProvider feature."""
        client = get_client(host, port)
        if client is None:
            return Response("Not connected", status=503)
        try:
            html = client.WebUIProvider.CustomUI.get()
            resp = make_response(html)
            resp.headers["Content-Type"] = "text/html; charset=utf-8"
            return resp
        except Exception:
            return Response("No custom UI available", status=404)

    @app.route("/api/user-manual/<host>/<int:port>")
    def api_user_manual(host: str, port: int):
        """Serve the user manual PDF from a server's UserManualProvider feature."""
        client = get_client(host, port)
        if client is None:
            return Response("Not connected", status=503)
        try:
            pdf_bytes = client.UserManualProvider.ManualDocument.get()
            resp = make_response(pdf_bytes)
            resp.headers["Content-Type"] = "application/pdf"
            resp.headers["Cache-Control"] = "public, max-age=3600"
            return resp
        except Exception:
            return Response("No user manual available", status=404)

    @app.route("/api/camera-stream/<host>/<int:port>")
    def api_camera_stream(host: str, port: int):
        """Serve an MJPEG stream by polling CameraStreamProvider.GetLatestFrame."""
        client = get_client(host, port)
        if client is None:
            return Response("Not connected", status=503)

        def generate():
            while True:
                try:
                    resp = client.CameraStreamProvider.GetLatestFrame()
                    frame = resp.Frame
                    yield (
                        b"--frame\r\n"
                        b"Content-Type: image/jpeg\r\n\r\n" + frame + b"\r\n"
                    )
                except Exception:
                    # Stream ended or error — send empty frame and stop
                    break
                time.sleep(0.1)  # ~10 fps

        return Response(
            generate(),
            mimetype="multipart/x-mixed-replace; boundary=frame",
        )

    @app.route("/api/camera-frame/<host>/<int:port>")
    def api_camera_frame(host: str, port: int):
        """Serve a single JPEG frame from CameraStreamProvider."""
        client = get_client(host, port)
        if client is None:
            return Response("Not connected", status=503)
        try:
            resp = client.CameraStreamProvider.GetLatestFrame()
            return Response(resp.Frame, mimetype="image/jpeg")
        except Exception as e:
            return Response(str(e), status=404)

    @app.route("/api/camera-config/<host>/<int:port>")
    def api_camera_config(host: str, port: int):
        """Return the camera config (from camera.json) and current streaming status."""
        client = get_client(host, port)
        if client is None:
            return jsonify({"error": "Not connected"}), 503
        result = {"source": "", "auto_start": False, "is_streaming": False}
        try:
            result["is_streaming"] = client.CameraStreamProvider.IsStreaming.get()
        except Exception:
            pass
        # Try to load camera.json from the server's package directory
        try:
            from sila_server_common.transports.camera_capture import load_camera_config
            # Infer server package from the server info
            info = get_server_info(host, port)
            if info:
                server_type = info.get("type", "")
                # Convert PascalCase server type to snake_case package name
                import re
                snake = re.sub(r'([A-Z]+)([A-Z][a-z])', r'\1_\2', server_type)
                snake = re.sub(r'([a-z\d])([A-Z])', r'\1_\2', snake).lower()
                config = load_camera_config(snake)
                if config:
                    result["source"] = config.get("source", "")
                    result["auto_start"] = config.get("auto_start", False)
        except Exception:
            pass
        return jsonify(result)

    @app.route("/api/command/<host>/<int:port>/<feature_id>/<command_id>", methods=["POST"])
    def api_execute_command(host: str, port: int, feature_id: str, command_id: str):
        client = get_client(host, port)
        if client is None:
            return jsonify({"error": "Not connected"}), 503

        try:
            feature = getattr(client, feature_id)
            command = getattr(feature, command_id)

            # Parse parameters from request, ordered by command definition
            params = request.json or {}

            # Look up command metadata to get correct parameter order
            cmd_meta = {
                **getattr(feature, "_unobservable_commands", {}),
                **getattr(feature, "_observable_commands", {}),
            }.get(command_id)

            args = []
            if cmd_meta and cmd_meta.parameters:
                for p in cmd_meta.parameters:
                    pid = p._identifier
                    if pid in params:
                        val = params[pid]
                        # Only JSON-parse non-String parameters (avoid "0" -> 0 coercion).
                        # Unwrap Constrained<T> to look at T — otherwise Constrained<String>
                        # parameters like the EL406 TravelRate set get json.loads'd and
                        # numeric-looking strings get coerced into ints, failing Set checks.
                        dt = getattr(p, "data_type", None)
                        effective_dt = dt.base_type if isinstance(dt, Constrained) else dt
                        type_name = type(effective_dt).__name__ if effective_dt else "String"
                        if isinstance(val, str) and type_name not in ("String", "Binary"):
                            try:
                                val = json.loads(val)
                            except (json.JSONDecodeError, TypeError):
                                pass
                        args.append(val)
            else:
                # Fallback: no metadata, use dict order
                for key, value in params.items():
                    try:
                        value = json.loads(value) if isinstance(value, str) else value
                    except (json.JSONDecodeError, TypeError):
                        pass
                    args.append(value)

            # Execute the command
            result = command(*args)

            # Check if this is an observable command instance
            if hasattr(result, 'done'):
                # Observable command - wait for completion
                intermediates = []
                try:
                    sub = result.subscribe_to_intermediate_responses()
                    sub.add_callback(lambda r: intermediates.append(str(r)))
                except Exception:
                    pass

                timeout = 60
                start = time.time()
                while not result.done and (time.time() - start) < timeout:
                    time.sleep(0.3)

                if result.done:
                    responses = result.get_responses()
                    return jsonify({
                        "status": "completed",
                        "responses": {k: _serialize(v) for k, v in responses._asdict().items()},
                        "intermediates": intermediates[-5:],  # Last 5 intermediates
                    })
                else:
                    return jsonify({"status": "timeout", "message": "Command did not complete within 60s"})
            else:
                # Unobservable command - result is the response directly
                if hasattr(result, '_asdict'):
                    return jsonify({
                        "status": "completed",
                        "responses": {k: _serialize(v) for k, v in result._asdict().items()},
                    })
                else:
                    return jsonify({"status": "completed", "responses": {}})

        except ValidationError as e:
            return jsonify({"status": "error", "error_type": "ValidationError", "message": str(e)}), 400
        except DefinedExecutionError as e:
            return jsonify({"status": "error", "error_type": e.identifier, "message": e.message}), 400
        except Exception as e:
            return jsonify({"status": "error", "error_type": type(e).__name__, "message": str(e)}), 500

    @app.route("/api/lock/<host>/<int:port>", methods=["POST"])
    def api_lock_server(host: str, port: int):
        client = get_client(host, port)
        if client is None:
            return jsonify({"error": "Not connected"}), 503

        data = request.json or {}
        action = data.get("action", "status")
        token = data.get("token", "webui-lock")
        timeout_sec = data.get("timeout", 300)

        try:
            lock = client.LockController
            if action == "lock":
                lock.LockServer(token, timeout_sec)
                return jsonify({"locked": True, "token": token})
            elif action == "unlock":
                lock.UnlockServer(token)
                return jsonify({"locked": False})
            else:
                is_locked = lock.IsLocked.get()
                return jsonify({"locked": is_locked})
        except AttributeError:
            return jsonify({"error": "Server does not support LockController"}), 400
        except DefinedExecutionError as e:
            return jsonify({"error": f"{e.identifier}: {e.message}"}), 400
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/api/simulation/<host>/<int:port>", methods=["POST"])
    def api_simulation(host: str, port: int):
        client = get_client(host, port)
        if client is None:
            return jsonify({"error": "Not connected"}), 503

        data = request.json or {}
        action = data.get("action", "status")

        try:
            sim = client.SimulationController
            if action == "start":
                sim.StartSimulationMode()
                return jsonify({"simulation": True})
            elif action == "stop":
                sim.StopSimulationMode()
                return jsonify({"simulation": False})
            else:
                mode = sim.SimulationMode.subscribe()
                value = next(iter(mode))
                mode.cancel()
                return jsonify({"simulation": value})
        except AttributeError:
            return jsonify({"error": "Server does not support SimulationController"}), 400
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/api/reconnect/<host>/<int:port>", methods=["POST"])
    def api_reconnect(host: str, port: int):
        """Drop cached client and reconnect to pick up server changes."""
        client = reconnect_client(host, port)
        if client is None:
            return jsonify({"error": "Failed to reconnect"}), 503
        return jsonify({"status": "reconnected"})

    @app.route("/api/sse/<host>/<int:port>/<feature_id>/<property_id>")
    def api_sse_property(host: str, port: int, feature_id: str, property_id: str):
        """Stream an observable property via Server-Sent Events (SSE).

        Subscribes to the SiLA observable property via gRPC streaming and
        forwards each update as an SSE event to the browser. The React WebUI
        connects to this endpoint via EventSource for real-time state push.
        """
        client = get_client(host, port)
        if client is None:
            return Response("Not connected", status=503)

        def generate():
            try:
                feature = getattr(client, feature_id)
                prop = getattr(feature, property_id)
                subscription = prop.subscribe()
                for value in subscription:
                    serialized = _serialize(value)
                    data = json.dumps(serialized)
                    yield f"data: {data}\n\n"
            except GeneratorExit:
                pass
            except Exception as e:
                yield f"data: {json.dumps({'error': str(e)})}\n\n"

        return Response(
            generate(),
            mimetype="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )

    @app.route("/api/mcp-tools/<host>/<int:port>")
    def api_mcp_tools(host: str, port: int):
        """Return MCP tool definitions built from SiLA introspection."""
        client = get_client(host, port)
        if client is None:
            return jsonify({"error": "Not connected"}), 503

        try:
            svc = client.SiLAService
            server_name = svc.ServerName.get()
            features = svc.ImplementedFeatures.get()

            device_description = None
            tools: List[Dict[str, Any]] = []

            for fqi in features:
                parts = str(fqi).split("/")
                feat_id = parts[-2] if len(parts) >= 3 else parts[-1]
                feature = getattr(client, feat_id, None)
                if feature is None:
                    continue

                # Check for DeviceDescription property
                if device_description is None and "DeviceDescription" in feature._unobservable_properties:
                    try:
                        device_description = feature.DeviceDescription.get()
                    except Exception:
                        pass

                # Build tool definitions from commands
                all_commands = {**feature._unobservable_commands, **feature._observable_commands}
                for cmd_id, cmd in all_commands.items():
                    tool_def: Dict[str, Any] = {
                        "name": f"{feat_id}_{cmd_id}",
                        "description": getattr(cmd, '_description', ''),
                        "inputSchema": _build_json_schema(cmd.parameters),
                    }
                    tools.append(tool_def)

            return jsonify({
                "server_name": server_name,
                "device_description": device_description,
                "tools": tools,
            })
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/api/servers")
    def api_servers():
        """Return the configured server list (no connection attempts).

        Use /api/server-info/<host>/<port> to get live status for each server.
        """
        return jsonify(get_all_servers())

    @app.route("/api/servers/add", methods=["POST"])
    def api_add_server():
        """Add a custom server to the list."""
        data = request.json or {}
        host = data.get("host", "").strip()
        port = data.get("port")
        name = data.get("name", "").strip()

        if not host or not port:
            return jsonify({"error": "host and port are required"}), 400
        try:
            port = int(port)
        except (ValueError, TypeError):
            return jsonify({"error": "port must be a number"}), 400

        # Check for duplicates across all servers
        for s in get_all_servers():
            if s["host"] == host and s["port"] == port:
                return jsonify({"error": f"Server {host}:{port} already exists"}), 409

        # Auto-detect name if not provided by probing the server
        if not name:
            name = f"{host}:{port}"
            try:
                client = SilaClient(host, port, insecure=True)
                name = client.SiLAService.ServerName.get()
            except Exception:
                pass

        entry = {"name": name, "host": host, "port": port, "custom": True}
        custom = _load_custom_servers()
        custom.append(entry)
        _save_custom_servers(custom)
        return jsonify(entry), 201

    @app.route("/api/servers/remove", methods=["POST"])
    def api_remove_server():
        """Remove a custom server from the list."""
        data = request.json or {}
        host = data.get("host", "").strip()
        port = data.get("port")

        if not host or not port:
            return jsonify({"error": "host and port are required"}), 400
        port = int(port)

        custom = _load_custom_servers()
        updated = [s for s in custom if not (s["host"] == host and s["port"] == port)]
        if len(updated) == len(custom):
            return jsonify({"error": "Server not found in custom list"}), 404
        _save_custom_servers(updated)

        # Also drop cached client
        with _clients_lock:
            _clients.pop(_client_key(host, port), None)

        return jsonify({"status": "removed"})

    # ── Gemini chat ───────────────────────────────────────────────────

    @app.route("/chat/<host>/<int:port>")
    def chat_page(host: str, port: int):
        info = get_server_info(host, port)
        if not info.get("connected"):
            return render_template("server_offline.html", info=info)
        return render_template("chat.html", info=info)

    @app.route("/api/chat/<host>/<int:port>", methods=["POST"])
    def api_chat(host: str, port: int):
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            return jsonify({"error": "GEMINI_API_KEY not set in environment"}), 500

        client = get_client(host, port)
        if client is None:
            return jsonify({"error": "Not connected to server"}), 503

        data = request.json or {}
        user_message = data.get("message", "")
        history = data.get("history", [])

        if not user_message:
            return jsonify({"error": "No message provided"}), 400

        try:
            from google import genai
            from google.genai import types

            # Build tools and lookup
            tool_decls, tool_lookup, device_desc, manual_text = _build_gemini_tools(client)

            # Build system instruction
            info = get_server_info(host, port)
            server_name = info.get("name", "SiLA 2 device")
            system_parts = [
                f"You are a lab automation assistant controlling a {server_name}.",
            ]
            if device_desc:
                system_parts.append(f"Device description: {device_desc}")
            if manual_text:
                system_parts.append(
                    f"The following is the device user manual. Use it to answer "
                    f"questions about operation, maintenance, and troubleshooting:\n\n{manual_text}"
                )
            system_parts.append(
                "Use the available tools to interact with the instrument. "
                "Always confirm before executing destructive operations."
            )
            system_instruction = " ".join(system_parts)

            # Build conversation contents
            contents = []
            for turn in history:
                role = turn.get("role", "user")
                text = turn.get("text", "")
                contents.append(types.Content(
                    role=role,
                    parts=[types.Part.from_text(text=text)],
                ))
            contents.append(types.Content(
                role="user",
                parts=[types.Part.from_text(text=user_message)],
            ))

            gemini_client = genai.Client(api_key=api_key)

            config = types.GenerateContentConfig(
                system_instruction=system_instruction,
                tools=[types.Tool(function_declarations=tool_decls)] if tool_decls else [],
            )

            response = gemini_client.models.generate_content(
                model="gemini-2.0-flash",
                contents=contents,
                config=config,
            )

            # Tool call loop
            tool_calls_log = []
            max_rounds = 10
            for _ in range(max_rounds):
                # Check if response has function calls
                fn_calls = []
                if response.candidates and response.candidates[0].content.parts:
                    for part in response.candidates[0].content.parts:
                        if part.function_call:
                            fn_calls.append(part)

                if not fn_calls:
                    break

                # Add the model's response (with function calls) to contents
                contents.append(response.candidates[0].content)

                # Execute each function call and build response parts
                fn_response_parts = []
                for part in fn_calls:
                    fc = part.function_call
                    fn_name = fc.name
                    fn_args = dict(fc.args) if fc.args else {}

                    log.info(f"Gemini tool call: {fn_name}({fn_args})")
                    result_str = _execute_tool_call(client, tool_lookup, fn_name, fn_args)
                    tool_calls_log.append({
                        "name": fn_name,
                        "args": fn_args,
                        "result": result_str,
                    })

                    fn_response_parts.append(types.Part.from_function_response(
                        name=fn_name,
                        response={"result": result_str},
                    ))

                # Send function results back
                contents.append(types.Content(
                    role="user",
                    parts=fn_response_parts,
                ))

                response = gemini_client.models.generate_content(
                    model="gemini-2.0-flash",
                    contents=contents,
                    config=config,
                )

            reply_text = response.text if response.text else "(No response text)"
            return jsonify({"reply": reply_text, "tool_calls": tool_calls_log})

        except Exception as e:
            log.exception("Chat error")
            return jsonify({"error": str(e)}), 500

    # ── Test runner routes ────────────────────────────────────────
    _TEST_SUITES_DIR = os.path.join(os.path.dirname(__file__), "test_suites")

    @app.route("/tests")
    def tests_index():
        """List available test suites."""
        suites = []
        if os.path.isdir(_TEST_SUITES_DIR):
            for fname in sorted(os.listdir(_TEST_SUITES_DIR)):
                if fname.endswith(".json"):
                    suite_name = fname[:-5]
                    try:
                        with open(os.path.join(_TEST_SUITES_DIR, fname)) as f:
                            data = json.load(f)
                        suites.append({
                            "name": suite_name,
                            "title": data.get("name", suite_name),
                            "description": data.get("description", ""),
                        })
                    except Exception:
                        suites.append({"name": suite_name, "title": suite_name, "description": ""})
        return render_template("test_suites.html", suites=suites)

    @app.route("/tests/<server_name>")
    def test_runner_page(server_name: str):
        """Serve the test runner UI for a specific server."""
        suite_path = os.path.join(_TEST_SUITES_DIR, f"{server_name}.json")
        if not os.path.isfile(suite_path):
            return f"Test suite '{server_name}' not found", 404
        return render_template("test_runner.html",
                               server_name=server_name,
                               api_base=f"/api/tests/{server_name}")

    @app.route("/api/tests/<server_name>/list")
    def api_test_suite_list(server_name: str):
        """Return the test suite JSON for a server."""
        suite_path = os.path.join(_TEST_SUITES_DIR, f"{server_name}.json")
        if not os.path.isfile(suite_path):
            return jsonify({"error": f"Test suite '{server_name}' not found"}), 404
        with open(suite_path) as f:
            data = json.load(f)
        return jsonify(data)

    # ── Message server routes ──────────────────────────────────────
    from . import message_server

    @app.route("/messages")
    def messages_page():
        return render_template("messages.html",
                               ws_port=message_server.get_ws_port())

    @app.route("/api/messages", methods=["GET"])
    def api_messages_list():
        return jsonify(message_server.store.all_messages())

    @app.route("/api/messages", methods=["POST"])
    def api_messages_send():
        data = request.json or {}
        title = data.get("title", "").strip()
        body = data.get("body", "").strip()
        instrument_id = data.get("instrument_id", "").strip()
        if not title or not instrument_id:
            return jsonify({"error": "title and instrument_id are required"}), 400
        msg = message_server.send_message(title, body, instrument_id)
        return jsonify({"id": msg.id, "status": msg.status})

    @app.route("/api/messages/<msg_id>/confirm", methods=["POST"])
    def api_messages_confirm(msg_id: str):
        msg = message_server.confirm_message(msg_id)
        if msg is None:
            return jsonify({"error": "Message not found or already confirmed"}), 404
        return jsonify({"id": msg.id, "status": msg.status})

    @app.route("/api/messages/status")
    def api_messages_status():
        return jsonify({
            "ws_clients": len(message_server._ws_clients),
            "pending": len(message_server.store.pending()),
            "total": len(message_server.store.all_messages()),
        })

    # ── Scripting engine routes ─────────────────────────────────────
    from .script_engine import ScriptEngine

    engine = ScriptEngine(servers_config_func=get_all_servers)

    @app.route("/scripts")
    def scripts_page():
        return render_template("scripts.html")

    @app.route("/api/scripts/run", methods=["POST"])
    def api_scripts_run():
        data = request.json or {}
        code = data.get("code", "")
        name = data.get("name", "untitled")
        if not code.strip():
            return jsonify({"error": "No code provided"}), 400
        session_id = engine.run_script(code, script_name=name)
        return jsonify({"session_id": session_id})

    @app.route("/api/scripts/stop/<session_id>", methods=["POST"])
    def api_scripts_stop(session_id: str):
        ok = engine.stop_script(session_id)
        if not ok:
            return jsonify({"error": "Session not found or not running"}), 404
        return jsonify({"status": "stopped"})

    @app.route("/api/scripts/sessions")
    def api_scripts_sessions():
        return jsonify(engine.list_sessions())

    @app.route("/api/scripts/sessions/<session_id>")
    def api_scripts_session_detail(session_id: str):
        session = engine.get_session(session_id)
        if not session:
            return jsonify({"error": "Session not found"}), 404
        result = session.to_dict()
        result["output_lines"] = session.output_lines
        return jsonify(result)

    @app.route("/api/scripts/output/<session_id>")
    def api_scripts_output(session_id: str):
        """SSE stream of script output lines."""
        def generate():
            session = engine.get_session(session_id)
            if not session:
                yield f"data: {json.dumps({'status': 'not_found'})}\n\n"
                return
            cursor = 0
            while session.status == "running":
                if cursor < len(session.output_lines):
                    for line in session.output_lines[cursor:]:
                        yield f"data: {json.dumps({'line': line})}\n\n"
                    cursor = len(session.output_lines)
                time.sleep(0.1)
            # Flush remaining lines
            if cursor < len(session.output_lines):
                for line in session.output_lines[cursor:]:
                    yield f"data: {json.dumps({'line': line})}\n\n"
            yield f"data: {json.dumps({'status': session.status})}\n\n"

        return Response(
            generate(),
            mimetype="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )

    # Script persistence
    @app.route("/api/scripts/saved")
    def api_scripts_saved_list():
        return jsonify(ScriptEngine.load_saved_scripts())

    @app.route("/api/scripts/save", methods=["POST"])
    def api_scripts_save():
        data = request.json or {}
        name = data.get("name", "").strip()
        code = data.get("code", "")
        if not name:
            return jsonify({"error": "Script name is required"}), 400
        ScriptEngine.save_script(name, code)
        return jsonify({"status": "saved", "name": name})

    @app.route("/api/scripts/saved/<name>")
    def api_scripts_saved_get(name: str):
        scripts = ScriptEngine.load_saved_scripts()
        if name not in scripts:
            return jsonify({"error": "Script not found"}), 404
        return jsonify({"name": name, "code": scripts[name]})

    @app.route("/api/scripts/saved/<name>", methods=["DELETE"])
    def api_scripts_saved_delete(name: str):
        ok = ScriptEngine.delete_saved_script(name)
        if not ok:
            return jsonify({"error": "Script not found"}), 404
        return jsonify({"status": "deleted"})

    # LLM script generation
    @app.route("/api/scripts/generate", methods=["POST"])
    def api_scripts_generate():
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            return jsonify({"error": "GEMINI_API_KEY not set"}), 500

        data = request.json or {}
        prompt = data.get("prompt", "").strip()
        if not prompt:
            return jsonify({"error": "No prompt provided"}), 400

        try:
            from google import genai
            from google.genai import types

            # Build context about available servers and the lab helper API
            servers = get_all_servers()
            server_summaries = []
            for s in servers:
                host, port = s.get("host", "127.0.0.1"), s.get("port", 0)
                client = get_client(host, port)
                if client:
                    try:
                        svc = client.SiLAService
                        features = svc.ImplementedFeatures.get()
                        feat_ids = []
                        for fqi in features:
                            parts = str(fqi).split("/")
                            fid = parts[-2] if len(parts) >= 3 else parts[-1]
                            if fid not in _SKIP_FEATURES:
                                feat_ids.append(fid)
                        # Get commands with full parameter details for each feature
                        feat_details = []
                        for fid in feat_ids:
                            feat = getattr(client, fid, None)
                            if not feat:
                                continue
                            all_cmds = {
                                **getattr(feat, "_unobservable_commands", {}),
                                **getattr(feat, "_observable_commands", {}),
                            }
                            cmd_descs = []
                            for cmd_id, cmd in all_cmds.items():
                                param_parts = []
                                for p in cmd.parameters:
                                    ptype = _type_name(p)
                                    desc = getattr(p, '_description', '')
                                    param_str = f"{p._identifier}: {ptype}"
                                    if desc:
                                        param_str += f" — {desc}"
                                    param_parts.append(param_str)
                                resp_parts = []
                                if hasattr(cmd, 'responses') and cmd.responses:
                                    for r in cmd.responses:
                                        resp_parts.append(f"{r._identifier}: {_type_name(r)}")
                                sig = ", ".join(param_parts) if param_parts else "no parameters"
                                ret = " -> " + ", ".join(resp_parts) if resp_parts else ""
                                cmd_desc = getattr(cmd, '_description', '')
                                cmd_line = f"    {cmd_id}({sig}){ret}"
                                if cmd_desc:
                                    cmd_line += f"  # {cmd_desc}"
                                cmd_descs.append(cmd_line)
                            all_props = {
                                **getattr(feat, "_unobservable_properties", {}),
                                **getattr(feat, "_observable_properties", {}),
                            }
                            prop_descs = [f"    {pid}: {_type_name(p)}" for pid, p in all_props.items()]
                            lines = [f"  Feature: {fid}"]
                            if cmd_descs:
                                lines.append("    Commands:")
                                lines.extend(cmd_descs)
                            if prop_descs:
                                lines.append("    Properties:")
                                lines.extend(prop_descs)
                            feat_details.append("\n".join(lines))
                        server_summaries.append(
                            f"- {s.get('name', 'Unknown')} ({host}:{port}) CONNECTED\n"
                            + "\n".join(feat_details)
                        )
                    except Exception:
                        server_summaries.append(f"- {s.get('name', 'Unknown')} ({host}:{port}) CONNECTED (introspection failed)")
                else:
                    server_summaries.append(f"- {s.get('name', 'Unknown')} ({host}:{port}) OFFLINE")

            system_prompt = f"""You are a lab automation script generator. Generate Python scripts using the `lab` helper library.

Available API:
- lab.connect("name") or lab.connect("host", port) -> DeviceProxy
- device.command("FeatureName", "CommandName", ParamName=value, ...) -> dict with response identifiers as keys
  Example: result = device.command("MultidropCombiController", "SetPlateType", PlateType="Standard 96 well")
  Parameters are passed as keyword arguments using the exact parameter identifiers listed below.
  Commands with no parameters: device.command("Feature", "Command")
  The return dict keys are the response identifiers listed in the command signatures below.
- device.property("FeatureName", "PropertyName") -> value
- device.lock(token="script") / device.unlock(token="script")
- device.features -> list of feature names
- device.commands("FeatureName") -> list of command names
- device.properties("FeatureName") -> list of property names
- lab.servers() -> list of server info dicts
- lab.sleep(seconds)
- lab.print("message") or just print("message")

Parameter types: String values must be passed as Python str, Integer as int, Real as float, Boolean as bool.
Commands with no parameters must be called without extra keyword arguments.

Available servers:
{chr(10).join(server_summaries)}

Rules:
- Output ONLY Python code, no markdown fences
- Do NOT write `import lab` — the `lab` object is already available as a global variable (pre-injected by the runtime)
- Do NOT import time — it is already available
- Use lab.connect() to connect to devices
- Use device.command() for SiLA commands
- Use print() for output
- Handle errors with try/except
- The script will be shown in an editor for the user to review before running
"""

            gemini_client = genai.Client(api_key=api_key)
            response = gemini_client.models.generate_content(
                model="gemini-2.0-flash",
                contents=[types.Content(
                    role="user",
                    parts=[types.Part.from_text(text=prompt)],
                )],
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                ),
            )

            code = response.text or ""
            # Strip markdown code fences if present
            if code.startswith("```"):
                lines = code.split("\n")
                lines = lines[1:]  # Remove opening fence
                if lines and lines[-1].strip() == "```":
                    lines = lines[:-1]
                code = "\n".join(lines)

            return jsonify({"code": code, "explanation": "Script generated. Review and click Run to execute."})

        except Exception as e:
            log.exception("Script generation error")
            return jsonify({"error": str(e)}), 500

    return app


# ── Gemini tool-building helpers ─────────────────────────────────────

def _build_gemini_tools(
    client: SilaClient,
) -> Tuple[list, Dict[str, Tuple[str, str, str]], Optional[str], Optional[str]]:
    """Build Gemini FunctionDeclarations from a SiLA client's features.

    Returns (declarations_list, lookup_dict, device_description, manual_text).
    lookup_dict maps tool_name -> (feature_id, item_id, kind) where kind is 'command' or 'property'.
    """
    from google.genai import types

    declarations = []
    lookup: Dict[str, Tuple[str, str, str]] = {}
    device_desc = None
    manual_text = None

    svc = client.SiLAService
    features = svc.ImplementedFeatures.get()

    for fqi in features:
        parts = str(fqi).split("/")
        feat_id = parts[-2] if len(parts) >= 3 else parts[-1]

        # Fetch manual text from UserManualProvider before skipping
        if feat_id == "UserManualProvider":
            feature = getattr(client, feat_id, None)
            if feature and manual_text is None:
                try:
                    manual_text = str(feature.ManualText.get())
                except Exception:
                    pass
            continue

        if feat_id in _SKIP_FEATURES:
            continue

        feature = getattr(client, feat_id, None)
        if feature is None:
            continue

        # Try to get DeviceDescription property
        if device_desc is None and "DeviceDescription" in getattr(feature, "_unobservable_properties", {}):
            try:
                device_desc = str(feature.DeviceDescription.get())
            except Exception:
                pass

        # Commands as tools
        all_commands = {
            **getattr(feature, "_unobservable_commands", {}),
            **getattr(feature, "_observable_commands", {}),
        }
        for cmd_id, cmd in all_commands.items():
            tool_name = f"{feat_id}_{cmd_id}"
            description = getattr(cmd, "_description", "") or f"Execute {cmd_id}"
            schema = _build_json_schema(cmd.parameters)

            declarations.append(types.FunctionDeclaration(
                name=tool_name,
                description=description[:512],
                parameters=schema if schema.get("properties") else None,
            ))
            lookup[tool_name] = (feat_id, cmd_id, "command")

        # Properties as tools (read-only)
        all_props = {
            **getattr(feature, "_unobservable_properties", {}),
            **getattr(feature, "_observable_properties", {}),
        }
        for prop_id, prop in all_props.items():
            if prop_id == "DisplayIcon":
                continue  # Skip binary icon data
            tool_name = f"{feat_id}_Get{prop_id}"
            description = getattr(prop, "_description", "") or f"Read property {prop_id}"
            description = f"Read the current value of {prop_id}. {description}"

            declarations.append(types.FunctionDeclaration(
                name=tool_name,
                description=description[:512],
                parameters={"type": "object", "properties": {}},
            ))
            lookup[tool_name] = (feat_id, prop_id, "property")

    return declarations, lookup, device_desc, manual_text


def _execute_tool_call(
    client: SilaClient,
    lookup: Dict[str, Tuple[str, str, str]],
    function_name: str,
    args: Dict[str, Any],
) -> str:
    """Execute a SiLA command or property read and return result as string."""
    if function_name not in lookup:
        return json.dumps({"error": f"Unknown tool: {function_name}"})

    feat_id, item_id, kind = lookup[function_name]

    try:
        feature = getattr(client, feat_id)

        if kind == "property":
            prop = getattr(feature, item_id)
            value = prop.get()
            return json.dumps({"value": _serialize(value)})

        # Command execution
        command = getattr(feature, item_id)
        cmd_meta = {
            **getattr(feature, "_unobservable_commands", {}),
            **getattr(feature, "_observable_commands", {}),
        }.get(item_id)

        # Build args list in parameter order
        arg_list = []
        if cmd_meta and cmd_meta.parameters:
            for p in cmd_meta.parameters:
                pid = p._identifier
                if pid in args:
                    val = args[pid]
                    # Coerce types based on SiLA data type
                    dt = getattr(p, "data_type", None) or getattr(p, "_data_type", None)
                    type_name = type(dt).__name__ if dt else ""
                    if isinstance(dt, Constrained):
                        type_name = type(dt.base_type).__name__
                    if type_name == "Integer":
                        val = int(val)
                    elif type_name == "Real":
                        val = float(val)
                    elif type_name == "Boolean":
                        val = bool(val) if isinstance(val, bool) else str(val).lower() in ("true", "1", "yes")
                    arg_list.append(val)

        result = command(*arg_list)

        # Handle observable commands
        if hasattr(result, "done"):
            timeout = 60
            start = time.time()
            while not result.done and (time.time() - start) < timeout:
                time.sleep(0.3)
            if result.done:
                responses = result.get_responses()
                if hasattr(responses, "_asdict"):
                    return json.dumps({k: _serialize(v) for k, v in responses._asdict().items()})
                return json.dumps({"result": _serialize(responses)})
            return json.dumps({"status": "timeout", "message": "Command did not complete within 60s"})

        # Unobservable command
        if hasattr(result, "_asdict"):
            return json.dumps({k: _serialize(v) for k, v in result._asdict().items()})
        return json.dumps({"status": "completed"})

    except DefinedExecutionError as e:
        return json.dumps({"error": f"{e.identifier}: {e.message}"})
    except ValidationError as e:
        return json.dumps({"error": f"ValidationError: {e}"})
    except Exception as e:
        return json.dumps({"error": str(e)})


def _serialize(value: Any) -> Any:
    """Make a value JSON-serializable."""
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    if isinstance(value, (int, float, bool, str, type(None))):
        return value
    if isinstance(value, (list, tuple)):
        return [_serialize(v) for v in value]
    if isinstance(value, dict):
        return {k: _serialize(v) for k, v in value.items()}
    if isinstance(value, bytes):
        if value[:4] == b'\x89PNG':
            return "data:image/png;base64," + base64.b64encode(value).decode()
        if value[:2] == b'\xff\xd8':
            return "data:image/jpeg;base64," + base64.b64encode(value).decode()
        return f"<{len(value)} bytes>"
    if isinstance(value, timedelta):
        return str(value)
    return str(value)

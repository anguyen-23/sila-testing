"""Helper library injected into global scripts as `lab`.

Wraps the Flask app's SiLA client management so scripts can call
SiLA commands without knowing gRPC/SiLA internals.
"""
from __future__ import annotations

import json
import math
import sys
import time
from datetime import timedelta
from typing import Any, Dict, List, Optional

import builtins

from sila2.client import SilaClient
from sila2.framework.data_types.constrained import Constrained
from sila2.framework.errors.defined_execution_error import DefinedExecutionError
from sila2.framework.errors.validation_error import ValidationError

_property = builtins.property


def _serialize(value: Any) -> Any:
    """Make a value JSON-serializable (mirrors app.py _serialize)."""
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    if isinstance(value, (int, float, bool, str, type(None))):
        return value
    if isinstance(value, (list, tuple)):
        return [_serialize(v) for v in value]
    if isinstance(value, dict):
        return {k: _serialize(v) for k, v in value.items()}
    if isinstance(value, bytes):
        return f"<{len(value)} bytes>"
    if isinstance(value, timedelta):
        return str(value)
    return str(value)


class DeviceProxy:
    """Wraps a SilaClient for script-friendly access."""

    def __init__(self, client: SilaClient, name: str):
        self._client = client
        self._name = name

    def __repr__(self):
        return f"DeviceProxy({self._name!r})"

    def command(self, feature: str, command: str, **params) -> dict:
        """Execute a SiLA command. Returns response dict."""
        feat = getattr(self._client, feature)
        cmd_callable = getattr(feat, command)

        # Look up command metadata for parameter ordering
        cmd_meta = {
            **getattr(feat, "_unobservable_commands", {}),
            **getattr(feat, "_observable_commands", {}),
        }.get(command)

        args = []
        if cmd_meta and cmd_meta.parameters:
            for p in cmd_meta.parameters:
                pid = p._identifier
                if pid in params:
                    val = params[pid]
                    # Type coercion based on SiLA data type
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
                    args.append(val)
        else:
            for val in params.values():
                args.append(val)

        result = cmd_callable(*args)

        # Handle observable commands
        if hasattr(result, "done"):
            timeout = 120
            start = time.time()
            while not result.done and (time.time() - start) < timeout:
                time.sleep(0.3)
            if result.done:
                responses = result.get_responses()
                if hasattr(responses, "_asdict"):
                    return {k: _serialize(v) for k, v in responses._asdict().items()}
                return {"result": _serialize(responses)}
            return {"status": "timeout", "message": "Command did not complete within 120s"}

        # Unobservable command
        if hasattr(result, "_asdict"):
            return {k: _serialize(v) for k, v in result._asdict().items()}
        return {}

    def property(self, feature: str, property_name: str) -> Any:
        """Read a property value."""
        feat = getattr(self._client, feature)
        prop = getattr(feat, property_name)
        value = prop.get()
        return _serialize(value)

    def lock(self, token: str = "script", timeout: int = 300):
        """Lock the device via LockController."""
        self._client.LockController.LockServer(token, timeout)
        print(f"[{self._name}] Locked (token={token})")

    def unlock(self, token: str = "script"):
        """Unlock the device via LockController."""
        self._client.LockController.UnlockServer(token)
        print(f"[{self._name}] Unlocked")

    @_property
    def features(self) -> list:
        """List feature identifiers."""
        try:
            fqis = self._client.SiLAService.ImplementedFeatures.get()
            result = []
            for fqi in fqis:
                parts = str(fqi).split("/")
                result.append(parts[-2] if len(parts) >= 3 else parts[-1])
            return result
        except Exception:
            return []

    @_property
    def status(self) -> dict:
        """Connection status and server info."""
        try:
            svc = self._client.SiLAService
            return {
                "connected": True,
                "name": svc.ServerName.get(),
                "type": svc.ServerType.get(),
            }
        except Exception as e:
            return {"connected": False, "error": str(e)}

    def commands(self, feature: str) -> list:
        """List command identifiers for a feature."""
        feat = getattr(self._client, feature, None)
        if feat is None:
            return []
        return list({
            **getattr(feat, "_unobservable_commands", {}),
            **getattr(feat, "_observable_commands", {}),
        }.keys())

    def properties(self, feature: str) -> list:
        """List property identifiers for a feature."""
        feat = getattr(self._client, feature, None)
        if feat is None:
            return []
        return list({
            **getattr(feat, "_unobservable_properties", {}),
            **getattr(feat, "_observable_properties", {}),
        }.keys())


class LabHelper:
    """Injected as `lab` in global scripts."""

    def __init__(self, servers_config: Optional[List[Dict]] = None):
        self._servers_config = servers_config or []
        self._proxies: Dict[str, DeviceProxy] = {}

    def servers(self) -> list:
        """List all configured servers with connection status."""
        results = []
        for s in self._servers_config:
            name = s.get("name", "")
            host = s.get("host", "127.0.0.1")
            port = s.get("port", 0)
            try:
                client = SilaClient(host, port, insecure=True)
                svc = client.SiLAService
                results.append({
                    "name": name,
                    "host": host,
                    "port": port,
                    "connected": True,
                    "server_name": svc.ServerName.get(),
                })
            except Exception:
                results.append({
                    "name": name,
                    "host": host,
                    "port": port,
                    "connected": False,
                })
        return results

    def connect(self, name_or_host: str, port: int = None) -> DeviceProxy:
        """Get a DeviceProxy for a server by name substring or host:port."""
        # Check cache
        cache_key = f"{name_or_host}:{port}" if port else name_or_host
        if cache_key in self._proxies:
            return self._proxies[cache_key]

        # Try matching by name substring first
        if port is None:
            for s in self._servers_config:
                if name_or_host.lower() in s.get("name", "").lower():
                    host = s.get("host", "127.0.0.1")
                    port = s.get("port")
                    name = s.get("name", f"{host}:{port}")
                    client = SilaClient(host, port, insecure=True)
                    proxy = DeviceProxy(client, name)
                    self._proxies[cache_key] = proxy
                    print(f"Connected to {name} ({host}:{port})")
                    return proxy
            raise ValueError(f"No server matching '{name_or_host}' found in configuration")

        # Direct host:port connection
        client = SilaClient(name_or_host, port, insecure=True)
        name = f"{name_or_host}:{port}"
        for s in self._servers_config:
            if s.get("host") == name_or_host and s.get("port") == port:
                name = s.get("name", name)
                break
        proxy = DeviceProxy(client, name)
        self._proxies[cache_key] = proxy
        print(f"Connected to {name}")
        return proxy

    def sleep(self, seconds: float):
        """Sleep with output to script console."""
        print(f"Sleeping {seconds}s...")
        time.sleep(seconds)

    def print(self, *args, **kwargs):
        """Print to script output stream."""
        print(*args, **kwargs)

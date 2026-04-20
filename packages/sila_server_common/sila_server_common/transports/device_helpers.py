"""Helper library injected into per-server scripts as `device`.

This is a reusable transport module. Provides a `device` object for per-server
scripts that connects to the local server via gRPC loopback.

Canonical location: packages/sila_server_common/sila_server_common/transports/device_helpers.py
Do not create per-server copies.
"""
from __future__ import annotations

import builtins
import json
import math
import time
from datetime import timedelta
from typing import Any

_property = builtins.property


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
        return f"<{len(value)} bytes>"
    if isinstance(value, timedelta):
        return str(value)
    return str(value)


class DeviceHelper:
    """Injected as `device` in per-server scripts.

    Connects to the local server via gRPC loopback for command execution.
    """

    def __init__(self, host: str, port: int, server_name: str):
        self._host = host
        self._port = port
        self._server_name = server_name
        self._client = None

    def _get_client(self):
        if self._client is None:
            from sila2.client import SilaClient
            self._client = SilaClient(self._host, self._port, insecure=True)
        return self._client

    def command(self, feature: str, command: str, **params) -> dict:
        """Execute a command on THIS server via gRPC loopback."""
        client = self._get_client()
        feat = getattr(client, feature)
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
                    args.append(params[pid])
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
            return {"status": "timeout"}

        if hasattr(result, "_asdict"):
            return {k: _serialize(v) for k, v in result._asdict().items()}
        return {}

    def property(self, feature: str, property_name: str) -> Any:
        """Read a property from THIS server."""
        client = self._get_client()
        feat = getattr(client, feature)
        prop = getattr(feat, property_name)
        return _serialize(prop.get())

    def status(self) -> dict:
        """Current device status (from DeviceStatus observable property).

        Searches all features for a DeviceStatus property. Returns its parsed
        JSON value if found, or an error dict if not available.
        """
        client = self._get_client()
        for feature_name in self.features:
            try:
                feat = getattr(client, feature_name, None)
                if feat is None:
                    continue
                props = {
                    **getattr(feat, "_unobservable_properties", {}),
                    **getattr(feat, "_observable_properties", {}),
                }
                if "DeviceStatus" in props:
                    val = _serialize(getattr(feat, "DeviceStatus").get())
                    if isinstance(val, str):
                        return json.loads(val)
                    return val
            except Exception:
                continue
        return {"error": "DeviceStatus not available"}

    def print(self, *args):
        """Print to script output (captured by ScriptRunner)."""
        print(*args)

    def sleep(self, seconds: float):
        """Sleep with status output."""
        print(f"Sleeping {seconds}s...")
        time.sleep(seconds)

    @_property
    def features(self) -> list:
        """List feature identifiers."""
        client = self._get_client()
        try:
            fqis = client.SiLAService.ImplementedFeatures.get()
            result = []
            for fqi in fqis:
                parts = str(fqi).split("/")
                result.append(parts[-2] if len(parts) >= 3 else parts[-1])
            return result
        except Exception:
            return []

    def commands(self, feature: str) -> list:
        """List command identifiers for a feature."""
        client = self._get_client()
        feat = getattr(client, feature, None)
        if feat is None:
            return []
        return list({
            **getattr(feat, "_unobservable_commands", {}),
            **getattr(feat, "_observable_commands", {}),
        }.keys())

    def properties(self, feature: str) -> list:
        """List property identifiers for a feature."""
        client = self._get_client()
        feat = getattr(client, feature, None)
        if feat is None:
            return []
        return list({
            **getattr(feat, "_unobservable_properties", {}),
            **getattr(feat, "_observable_properties", {}),
        }.keys())

    def __repr__(self):
        return f"DeviceHelper({self._server_name!r}, {self._host}:{self._port})"

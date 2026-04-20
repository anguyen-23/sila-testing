"""Generic per-server device configuration persistence.

Stores device-specific settings (e.g. COM port, IP address) in a
`device_config.json` file in the server's root directory.

This is for device-specific settings that don't belong in the shared
feature configs (camera.json, screen_capture.json).
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

log = logging.getLogger(__name__)


def _config_path(server_package_or_dir: str | Path) -> Path | None:
    """Resolve the path to device_config.json for a server."""
    if isinstance(server_package_or_dir, Path):
        return server_package_or_dir / "device_config.json"
    import importlib
    try:
        pkg = importlib.import_module(server_package_or_dir)
        return Path(pkg.__file__).parent.parent / "device_config.json"
    except (ImportError, AttributeError):
        return None


def load_device_config(server_package_or_dir: str | Path) -> dict | None:
    """Load device_config.json from a server's root directory."""
    config_path = _config_path(server_package_or_dir)
    if config_path is None or not config_path.exists():
        return None
    try:
        return json.loads(config_path.read_text(encoding="utf-8"))
    except Exception as e:
        log.warning("Failed to load device config from %s: %s", config_path, e)
        return None


def save_device_config(server_package_or_dir: str | Path, config: dict) -> None:
    """Save device_config.json to a server's root directory (merges with existing)."""
    config_path = _config_path(server_package_or_dir)
    if config_path is None:
        log.warning("Cannot determine config path for device config")
        return
    try:
        existing = {}
        if config_path.exists():
            existing = json.loads(config_path.read_text(encoding="utf-8"))
        existing.update(config)
        config_path.write_text(json.dumps(existing, indent=4) + "\n", encoding="utf-8")
        log.info("Saved device config to %s", config_path)
    except Exception as e:
        log.warning("Failed to save device config to %s: %s", config_path, e)

"""Parse the Ansible inventory to extract host/group information."""
from __future__ import annotations

import os
from typing import Any, Dict, List

import yaml

# Path to inventory relative to this file
_INVENTORY_DIR = os.path.join(os.path.dirname(__file__), "..", "inventory")
_HOSTS_FILE = os.path.join(_INVENTORY_DIR, "hosts.yml")
_ALL_VARS_DIR = os.path.join(_INVENTORY_DIR, "group_vars", "all")
_ALL_VARS_FILE_LEGACY = os.path.join(_INVENTORY_DIR, "group_vars", "all.yml")


def _load_yaml(path: str) -> dict:
    with open(path) as f:
        return yaml.safe_load(f) or {}


def load_all_vars() -> Dict[str, Any]:
    """Load shared variables from group_vars/all/all.yml (or legacy all.yml)."""
    all_yml = os.path.join(_ALL_VARS_DIR, "all.yml")
    for path in [all_yml, _ALL_VARS_FILE_LEGACY]:
        try:
            return _load_yaml(path)
        except FileNotFoundError:
            continue
    return {}


def load_inventory() -> List[Dict[str, Any]]:
    """Parse hosts.yml and return a flat list of host records.

    Each host defines a `sila_servers` list. This function returns one record
    per server entry:
    {
        hostname, group, sila_package, sila_port, sila_extra_args,
        platform ('windows'|'linux')
    }
    """
    inv = _load_yaml(_HOSTS_FILE)
    all_section = inv.get("all", {})
    children = all_section.get("children", {})

    # Collect hosts with sila_servers from platform groups
    hosts = []

    for platform_group, platform_name in [("windows", "windows"), ("linux", "linux")]:
        pg = children.get(platform_group, {})
        pg_hosts = pg.get("hosts", {}) or {}

        for hostname, host_vars in pg_hosts.items():
            if host_vars is None:
                host_vars = {}
            servers = host_vars.get("sila_servers", [])
            ansible_host = host_vars.get("ansible_host", hostname)

            for server in servers:
                hosts.append({
                    "hostname": hostname,
                    "ansible_host": ansible_host,
                    "group": server["package"],
                    "sila_package": server["package"],
                    "sila_port": server.get("port", ""),
                    "sila_extra_args": server.get("extra_args", ""),
                    "platform": platform_name,
                })

    return hosts


def get_groups() -> List[str]:
    """Return the list of server group names (excluding platform/meta groups)."""
    inv = _load_yaml(_HOSTS_FILE)
    children = inv.get("all", {}).get("children", {})
    skip = {"windows", "linux", "headscale"}
    return [g for g in children if g not in skip]

"""Server compliance validator — checks a server directory for standard architecture completeness.

Usage:
    python -m sila_server_common.validate servers/my_server

Or programmatically:
    from sila_server_common.validate import validate_server
    issues = validate_server(Path("servers/my_server"))
"""
from __future__ import annotations

import argparse
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from sila_server_common.fdl import STANDARD_FEATURES


def validate_server(server_dir: Path) -> list[str]:
    """Validate a server directory for standard architecture compliance.

    Returns a list of issue strings. Empty list means fully compliant.
    """
    issues: list[str] = []

    if not server_dir.is_dir():
        return [f"Server directory does not exist: {server_dir}"]

    # Determine package name (the subdirectory that matches the server dir name)
    server_name = server_dir.name
    pkg_dir = server_dir / server_name
    if not pkg_dir.is_dir():
        # Try to find the package directory
        candidates = [d for d in server_dir.iterdir() if d.is_dir() and (d / "__init__.py").exists()]
        candidates = [d for d in candidates if d.name not in {"__pycache__"} and not d.name.endswith(".egg-info")]
        if len(candidates) == 1:
            pkg_dir = candidates[0]
            server_name = pkg_dir.name
        else:
            issues.append(f"Cannot find Python package directory in {server_dir}")
            return issues

    # ── FDL Files ──
    for feature in STANDARD_FEATURES:
        fdl_path = server_dir / f"{feature}.sila.xml"
        if not fdl_path.exists():
            issues.append(f"Missing FDL: {feature}.sila.xml")

    # Check for at least one device-specific FDL
    # .sila.xml is a double extension — f.stem gives "FeatureName.sila", so strip ".sila" too
    def _fdl_feature_name(p: Path) -> str:
        return p.stem.removesuffix(".sila")

    device_fdls = [
        f for f in server_dir.glob("*.sila.xml")
        if _fdl_feature_name(f) not in STANDARD_FEATURES
    ]
    if not device_fdls:
        issues.append("No device-specific FDL file found (only standard features)")

    # ── DeviceStatus observable property (only check device-specific FDLs) ──
    for fdl_path in device_fdls:
        _check_device_status(fdl_path, issues)

    # ── Package structure ──
    impl_dir = pkg_dir / "feature_implementations"
    if not impl_dir.is_dir():
        issues.append(f"Missing directory: {pkg_dir.name}/feature_implementations/")

    for filename in ["__init__.py", "__main__.py", "server.py"]:
        if not (pkg_dir / filename).exists():
            issues.append(f"Missing file: {pkg_dir.name}/{filename}")

    if not (pkg_dir / "custom_ui.html").exists():
        issues.append(f"Missing file: {pkg_dir.name}/custom_ui.html (WebUI)")

    # ── pyproject.toml ──
    pyproject = server_dir / "pyproject.toml"
    if pyproject.exists():
        content = pyproject.read_text(encoding="utf-8")
        if "sila_server_common" not in content:
            issues.append("pyproject.toml does not depend on sila_server_common")
    else:
        issues.append("Missing pyproject.toml")

    # ── Check server.py uses BaseInstrumentServer ──
    server_py = pkg_dir / "server.py"
    if server_py.exists():
        content = server_py.read_text(encoding="utf-8")
        if "BaseInstrumentServer" not in content:
            issues.append("server.py does not use BaseInstrumentServer from sila_server_common")
        if "on_simulation_mode_changed" not in content:
            issues.append("server.py does not implement on_simulation_mode_changed()")

    # ── Check __main__.py uses shared server_main ──
    main_py = pkg_dir / "__main__.py"
    if main_py.exists():
        content = main_py.read_text(encoding="utf-8")
        if "sila_server_common.server_main" not in content and "create_main" not in content:
            issues.append("__main__.py does not use create_main from sila_server_common.server_main")

    # ── Check for duplicate transport files (should be using shared library) ──
    transport_files = ["win32_capture.py", "messaging_transport.py", "structured_logging.py", "device_helpers.py"]
    for tf in transport_files:
        if (pkg_dir / tf).exists():
            issues.append(f"Local transport file found: {pkg_dir.name}/{tf} — should import from sila_server_common instead")

    # ── Check for duplicate boilerplate implementations ──
    boilerplate_impls = [
        "lockcontroller_impl.py", "screenstreamer_impl.py", "messagingclient_impl.py",
        "webuiprovider_impl.py", "usermanualprovider_impl.py", "serverlogprovider_impl.py",
        "scriptrunner_impl.py",
    ]
    for impl_file in boilerplate_impls:
        path = impl_dir / impl_file
        if path.exists():
            content = path.read_text(encoding="utf-8")
            if "sila_server_common" not in content:
                issues.append(
                    f"Local boilerplate impl: {impl_file} — should import from sila_server_common "
                    f"or be removed (BaseInstrumentServer handles standard features)"
                )

    # ── deploy.bat and start_server.bat ──
    if not (server_dir / "deploy.bat").exists():
        issues.append("Missing deploy.bat")
    if not (server_dir / "start_server.bat").exists():
        issues.append("Missing start_server.bat")

    return issues


def _check_device_status(fdl_path: Path, issues: list[str]) -> None:
    """Check if a device FDL has a DeviceStatus observable property."""
    try:
        tree = ET.parse(fdl_path)
        root = tree.getroot()
        ns = {"sila": "http://www.sila-standard.org"}

        has_device_status = False
        for prop in root.findall("sila:Property", ns):
            ident = prop.find("sila:Identifier", ns)
            observable = prop.find("sila:Observable", ns)
            if ident is not None and ident.text == "DeviceStatus":
                has_device_status = True
                if observable is None or observable.text != "Yes":
                    issues.append(f"{fdl_path.name}: DeviceStatus property must be Observable")
                break

        if not has_device_status:
            issues.append(f"{fdl_path.name}: Missing required DeviceStatus observable property")

    except ET.ParseError as e:
        issues.append(f"{fdl_path.name}: XML parse error: {e}")


def main():
    parser = argparse.ArgumentParser(description="Validate a SiLA 2 server for standard architecture compliance")
    parser.add_argument("server_dir", help="Path to the server directory")
    args = parser.parse_args()

    server_dir = Path(args.server_dir)
    issues = validate_server(server_dir)

    if not issues:
        print(f"PASS: {server_dir.name} is compliant")
        sys.exit(0)
    else:
        print(f"FAIL: {server_dir.name} has {len(issues)} issue(s):")
        for i, issue in enumerate(issues, 1):
            print(f"  {i}. {issue}")
        sys.exit(1)


if __name__ == "__main__":
    main()

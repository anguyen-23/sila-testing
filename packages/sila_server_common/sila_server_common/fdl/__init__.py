"""Shared FDL files for standard SiLA 2 server features.

Use `get_fdl_path(feature_name)` to get the absolute path to a shared FDL file.
Use `get_all_fdl_paths()` to get paths to all shared FDL files for codegen.
"""
from pathlib import Path

_FDL_DIR = Path(__file__).parent

STANDARD_FEATURES = [
    "SimulationController",
    "ScreenStreamer",
    "MessagingClient",
    "WebUIProvider",
    "UserManualProvider",
    "ServerLogProvider",
    "ScriptRunner",
]

OPTIONAL_FEATURES = [
    "CameraStreamProvider",
]


def get_fdl_path(feature_name: str) -> Path:
    """Get the path to a shared FDL file by feature name."""
    path = _FDL_DIR / f"{feature_name}.sila.xml"
    if not path.exists():
        raise FileNotFoundError(f"No FDL file found for feature '{feature_name}' in {_FDL_DIR}")
    return path


def get_all_fdl_paths() -> list[Path]:
    """Get paths to all shared FDL files (for use in codegen commands)."""
    return [get_fdl_path(f) for f in STANDARD_FEATURES]

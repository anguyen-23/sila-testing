"""ServerLogProvider implementation factory — canonical, shared across all servers.

Usage in server.py:
    from sila_server_common.feature_implementations.serverlogprovider_impl import create_serverlogprovider_impl
    from .generated import serverlogprovider as slp_gen

    ServerLogProviderImpl = create_serverlogprovider_impl(slp_gen)
    self.serverlogprovider = ServerLogProviderImpl(self)
    self.set_feature_implementation(slp_gen.ServerLogProviderFeature, self.serverlogprovider)
"""
from __future__ import annotations

import json
from pathlib import Path
from types import ModuleType

from sila_server_common.transports.structured_logging import get_distinct_features, get_log_stats, query_logs


def create_serverlogprovider_impl(generated_module: ModuleType, db_path: Path | None = None) -> type:
    """Create a ServerLogProviderImpl class bound to the server's generated module."""

    Base = generated_module.ServerLogProviderBase
    GetLogFeatures_Responses = generated_module.GetLogFeatures_Responses
    GetLogs_Responses = generated_module.GetLogs_Responses

    class ServerLogProviderImpl(Base):
        def __init__(self, parent_server) -> None:
            super().__init__(parent_server=parent_server)
            if db_path is not None:
                self._db_path = db_path
            else:
                self._db_path = Path(__file__).parent.parent / "logs" / "structured.db"

        def get_LogStats(self, *, metadata) -> str:
            return json.dumps(get_log_stats(self._db_path))

        # SiLA 2 string limit is 2^21 chars; keep well under to avoid serialization errors
        _MAX_JSON_SIZE = (1 << 21) - 4096

        def GetLogs(
            self, StartTime: str, EndTime: str, MinSeverity: str, Feature: str, MaxEntries: int, *, metadata
        ) -> GetLogs_Responses:
            max_entries = MaxEntries if MaxEntries > 0 else 500
            max_entries = min(max(max_entries, 1), 2000)
            entries = query_logs(self._db_path, StartTime, EndTime, MinSeverity, Feature, max_entries)
            result = json.dumps(entries)
            while len(result) > self._MAX_JSON_SIZE and len(entries) > 1:
                entries = entries[:len(entries) // 2]
                result = json.dumps(entries)
            return GetLogs_Responses(LogEntries=result)

        def GetLogFeatures(self, *, metadata) -> GetLogFeatures_Responses:
            return GetLogFeatures_Responses(Features=get_distinct_features(self._db_path))

    return ServerLogProviderImpl

"""Structured logging to SQLite for SiLA 2 servers.

Canonical location: packages/sila_server_common/sila_server_common/transports/structured_logging.py
Do not create per-server copies.

Provides:
- StructuredLogHandler: a logging.Handler that writes to SQLite
- query_logs(): query log entries with filters
- get_distinct_features(): list feature names in the DB
- get_log_stats(): summary statistics
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Feature-name mapping: maps Python logger/module names to human-readable feature names.
# Standard features are always included. Servers add device-specific mappings
# by passing a feature_map to StructuredLogHandler (merged with these defaults).
DEFAULT_FEATURE_MAP: dict[str, str] = {
    # Standard feature implementations
    "simulationcontroller_impl": "SimulationController",
    "screenstreamer_impl": "ScreenStreamer",
    "messagingclient_impl": "MessagingClient",
    "webuiprovider_impl": "WebUIProvider",
    "usermanualprovider_impl": "UserManualProvider",
    "lockcontroller_impl": "LockController",
    "serverlogprovider_impl": "ServerLogProvider",
    "scriptrunner_impl": "ScriptRunner",
    # Transport modules
    "serial_transport": "SerialTransport",
    "messaging_transport": "MessagingTransport",
    "win32_capture": "ScreenCapture",
    "structured_logging": "StructuredLogging",
    "device_helpers": "DeviceHelpers",
    # Server infrastructure
    "__main__": "Server",
    "server": "Server",
}

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    level TEXT NOT NULL,
    level_num INTEGER NOT NULL,
    feature TEXT NOT NULL,
    logger TEXT NOT NULL,
    message TEXT NOT NULL,
    module TEXT,
    func_name TEXT,
    category TEXT,
    direction TEXT,
    extra_json TEXT
);
"""

_CREATE_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_timestamp ON logs(timestamp);",
    "CREATE INDEX IF NOT EXISTS idx_level_num ON logs(level_num);",
    "CREATE INDEX IF NOT EXISTS idx_feature ON logs(feature);",
]

# Extra fields that get stored in extra_json if present on the log record
_KNOWN_EXTRA_KEYS = {"category", "direction", "command_name", "serial_cmd"}


class StructuredLogHandler(logging.Handler):
    """Logging handler that writes structured log entries to a SQLite database."""

    def __init__(
        self,
        db_path: Path | str,
        max_rows: int = 50_000,
        feature_map: dict[str, str] | None = None,
        server_package: str = "",
    ) -> None:
        super().__init__()
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._max_rows = max_rows
        self._feature_map = feature_map or DEFAULT_FEATURE_MAP
        self._server_package = server_package
        self._insert_count = 0
        self._local = threading.local()

        # Create table and indexes on the initial connection
        conn = self._get_conn()
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute(_CREATE_TABLE)
        for idx_sql in _CREATE_INDEXES:
            conn.execute(idx_sql)
        conn.commit()

    def _get_conn(self) -> sqlite3.Connection:
        """Return a thread-local SQLite connection."""
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(str(self._db_path), timeout=5)
            conn.execute("PRAGMA journal_mode=WAL;")
            self._local.conn = conn
        return conn

    def _extract_feature(self, record: logging.LogRecord) -> str:
        """Map a log record to a human-readable feature name."""
        # Try module name first (e.g. "multidropcombi_impl")
        module = record.module or ""
        if module in self._feature_map:
            return self._feature_map[module]

        # Try last part of logger name (e.g. "multidrop_combi.feature_implementations.multidropcombi_impl")
        logger_name = record.name or ""
        last_part = logger_name.rsplit(".", 1)[-1] if logger_name else ""
        if last_part in self._feature_map:
            return self._feature_map[last_part]

        # Fallback: use the last part of the logger name as-is
        return last_part or "Unknown"

    def emit(self, record: logging.LogRecord) -> None:
        try:
            # Only capture logs from the server's own package and known modules.
            # Skip noisy framework loggers (grpc, sila2, asyncio, etc.)
            logger_name = record.name or ""
            module = record.module or ""
            if self._server_package:
                is_own = (
                    logger_name.startswith(self._server_package)
                    or module in self._feature_map
                )
                if not is_own:
                    return

            # Extract structured extra fields
            category = getattr(record, "category", None)
            direction = getattr(record, "direction", None)

            # Collect any extra structured data
            extra_data: dict[str, Any] = {}
            for key in _KNOWN_EXTRA_KEYS - {"category", "direction"}:
                val = getattr(record, key, None)
                if val is not None:
                    extra_data[key] = val
            extra_json = json.dumps(extra_data) if extra_data else None

            timestamp = datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat()

            conn = self._get_conn()
            conn.execute(
                """INSERT INTO logs (timestamp, level, level_num, feature, logger,
                   message, module, func_name, category, direction, extra_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    timestamp,
                    record.levelname,
                    record.levelno,
                    self._extract_feature(record),
                    record.name,
                    record.getMessage(),
                    record.module,
                    record.funcName,
                    category,
                    direction,
                    extra_json,
                ),
            )
            conn.commit()

            self._insert_count += 1
            if self._insert_count % 1000 == 0:
                self._prune(conn)

        except Exception:
            self.handleError(record)

    def _prune(self, conn: sqlite3.Connection) -> None:
        """Delete oldest rows beyond max_rows."""
        try:
            conn.execute(
                "DELETE FROM logs WHERE id NOT IN (SELECT id FROM logs ORDER BY id DESC LIMIT ?)",
                (self._max_rows,),
            )
            conn.commit()
        except Exception:
            pass


# ── Query functions ──────────────────────────────────────────────────

LEVEL_NUMS = {
    "DEBUG": 10,
    "INFO": 20,
    "WARNING": 30,
    "ERROR": 40,
    "CRITICAL": 50,
}


def query_logs(
    db_path: Path | str,
    start_time: str = "",
    end_time: str = "",
    min_severity: str = "",
    feature: str = "",
    max_entries: int = 500,
) -> list[dict[str, Any]]:
    """Query log entries with optional filters. Returns newest-first."""
    max_entries = min(max(max_entries, 1), 2000)

    conditions: list[str] = []
    params: list[Any] = []

    if start_time:
        conditions.append("timestamp >= ?")
        params.append(start_time)
    if end_time:
        conditions.append("timestamp <= ?")
        params.append(end_time)
    if min_severity and min_severity.upper() in LEVEL_NUMS:
        conditions.append("level_num >= ?")
        params.append(LEVEL_NUMS[min_severity.upper()])
    if feature:
        conditions.append("feature = ?")
        params.append(feature)

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    sql = f"SELECT timestamp, level, feature, message, module, func_name, category, direction, extra_json FROM logs {where} ORDER BY timestamp DESC LIMIT ?"
    params.append(max_entries)

    conn = sqlite3.connect(str(db_path), timeout=5)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(sql, params).fetchall()
        results = []
        for row in rows:
            entry: dict[str, Any] = {
                "timestamp": row["timestamp"],
                "level": row["level"],
                "feature": row["feature"],
                "message": row["message"],
                "module": row["module"],
                "func_name": row["func_name"],
                "category": row["category"],
                "direction": row["direction"],
            }
            if row["extra_json"]:
                try:
                    entry["extra"] = json.loads(row["extra_json"])
                except json.JSONDecodeError:
                    entry["extra"] = None
            else:
                entry["extra"] = None
            results.append(entry)
        return results
    finally:
        conn.close()


def get_distinct_features(db_path: Path | str) -> list[str]:
    """Return distinct feature names from the log database."""
    conn = sqlite3.connect(str(db_path), timeout=5)
    try:
        rows = conn.execute("SELECT DISTINCT feature FROM logs ORDER BY feature").fetchall()
        return [row[0] for row in rows]
    finally:
        conn.close()


def get_log_stats(db_path: Path | str) -> dict[str, Any]:
    """Return summary statistics about the log database."""
    db_path = Path(db_path)
    if not db_path.exists():
        return {
            "total_entries": 0,
            "counts_by_level": {},
            "oldest_timestamp": None,
            "newest_timestamp": None,
            "db_size_bytes": 0,
        }

    conn = sqlite3.connect(str(db_path), timeout=5)
    try:
        total = conn.execute("SELECT COUNT(*) FROM logs").fetchone()[0]

        counts_by_level: dict[str, int] = {}
        for row in conn.execute("SELECT level, COUNT(*) FROM logs GROUP BY level"):
            counts_by_level[row[0]] = row[1]

        oldest = conn.execute("SELECT MIN(timestamp) FROM logs").fetchone()[0]
        newest = conn.execute("SELECT MAX(timestamp) FROM logs").fetchone()[0]

        db_size = db_path.stat().st_size if db_path.exists() else 0

        return {
            "total_entries": total,
            "counts_by_level": counts_by_level,
            "oldest_timestamp": oldest,
            "newest_timestamp": newest,
            "db_size_bytes": db_size,
        }
    finally:
        conn.close()

"""Script execution engine for the global scripting environment.

Manages script execution in subprocesses with output streaming.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class ScriptSession:
    """Manages a running script."""
    id: str
    script_name: str
    status: str  # "running", "completed", "error", "stopped"
    started_at: float
    output_lines: List[str] = field(default_factory=list)
    exit_code: Optional[int] = None
    _process: Optional[subprocess.Popen] = field(default=None, repr=False)
    _thread: Optional[threading.Thread] = field(default=None, repr=False)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "script_name": self.script_name,
            "status": self.status,
            "started_at": self.started_at,
            "exit_code": self.exit_code,
            "output_line_count": len(self.output_lines),
        }


# Directory for saved scripts
_SAVED_SCRIPTS_FILE = os.path.join(os.path.dirname(__file__), "saved_scripts.json")


class ScriptEngine:
    def __init__(self, servers_config_func=None):
        self.sessions: Dict[str, ScriptSession] = {}
        self._servers_config_func = servers_config_func

    def run_script(self, code: str, script_name: str = "untitled") -> str:
        """Execute Python code in a subprocess, return session_id."""
        session_id = str(uuid.uuid4())[:8]

        # Build the preamble that sets up the lab helper
        servers_json = json.dumps(self._servers_config_func() if self._servers_config_func else [])
        preamble = f'''\
import sys, os, time
sys.path.insert(0, {os.path.dirname(os.path.dirname(__file__))!r})
from client_web_ui.lab_helpers import LabHelper
import json

_servers_config = json.loads({servers_json!r})
lab = LabHelper(_servers_config)
'''

        # Strip `import lab` / `import time` lines — they're already in the preamble
        import re
        cleaned = re.sub(r'^import\s+lab\s*$', '# (lab is pre-injected)', code, flags=re.MULTILINE)
        cleaned = re.sub(r'^import\s+time\s*$', '# (time is pre-injected)', cleaned, flags=re.MULTILINE)

        full_code = preamble + "\n" + cleaned

        # Write to temp file
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", prefix=f"script_{session_id}_",
            delete=False, dir=tempfile.gettempdir(),
        )
        tmp.write(full_code)
        tmp.close()

        # Determine python executable (use same venv)
        python_exe = sys.executable

        # Launch subprocess
        process = subprocess.Popen(
            [python_exe, "-u", tmp.name],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            cwd=os.path.dirname(os.path.dirname(__file__)),
        )

        session = ScriptSession(
            id=session_id,
            script_name=script_name,
            status="running",
            started_at=time.time(),
            _process=process,
        )
        self.sessions[session_id] = session

        # Background thread to read output
        thread = threading.Thread(
            target=self._read_output, args=(session, tmp.name), daemon=True
        )
        session._thread = thread
        thread.start()

        return session_id

    def _read_output(self, session: ScriptSession, tmp_path: str):
        """Read stdout/stderr line-by-line from the subprocess."""
        try:
            process = session._process
            for line in process.stdout:
                session.output_lines.append(line.rstrip("\n"))
            process.wait()
            session.exit_code = process.returncode
            session.status = "completed" if process.returncode == 0 else "error"
        except Exception as e:
            session.output_lines.append(f"[Engine Error] {e}")
            session.status = "error"
        finally:
            # Clean up temp file
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    def stop_script(self, session_id: str) -> bool:
        """Kill a running script subprocess."""
        session = self.sessions.get(session_id)
        if not session or session.status != "running":
            return False
        try:
            session._process.terminate()
            session._process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            session._process.kill()
        except Exception:
            pass
        session.status = "stopped"
        session.output_lines.append("[Script stopped by user]")
        return True

    def get_session(self, session_id: str) -> Optional[ScriptSession]:
        return self.sessions.get(session_id)

    def list_sessions(self) -> List[dict]:
        return [s.to_dict() for s in self.sessions.values()]

    # ── Saved scripts persistence ────────────────────────────────

    @staticmethod
    def load_saved_scripts() -> Dict[str, str]:
        """Load saved scripts from JSON file. Returns {name: code}."""
        try:
            with open(_SAVED_SCRIPTS_FILE, "r") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    @staticmethod
    def save_script(name: str, code: str):
        """Save a script to the JSON file."""
        scripts = ScriptEngine.load_saved_scripts()
        scripts[name] = code
        with open(_SAVED_SCRIPTS_FILE, "w") as f:
            json.dump(scripts, f, indent=2)

    @staticmethod
    def delete_saved_script(name: str) -> bool:
        """Delete a saved script. Returns True if found and deleted."""
        scripts = ScriptEngine.load_saved_scripts()
        if name not in scripts:
            return False
        del scripts[name]
        with open(_SAVED_SCRIPTS_FILE, "w") as f:
            json.dump(scripts, f, indent=2)
        return True

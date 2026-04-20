"""ScriptRunner implementation factory — canonical, shared across all servers.

Usage in server.py:
    from sila_server_common.feature_implementations.scriptrunner_impl import create_scriptrunner_impl
    from .generated import scriptrunner as sr_gen

    ScriptRunnerImpl = create_scriptrunner_impl(sr_gen, server_package="my_server")
    self.scriptrunner = ScriptRunnerImpl(self)
    self.set_feature_implementation(sr_gen.ScriptRunnerFeature, self.scriptrunner)
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
import tempfile
import threading
from datetime import timedelta
from pathlib import Path
from types import ModuleType

from sila2.server import ObservableCommandInstanceWithIntermediateResponses

log = logging.getLogger(__name__)


def create_scriptrunner_impl(generated_module: ModuleType, server_package: str = "") -> type:
    """Create a ScriptRunnerImpl class bound to the server's generated module.

    Args:
        generated_module: The server's generated scriptrunner module.
        server_package: The server's Python package name (e.g., "multidrop_combi").
                        Used to construct the import path for device_helpers in script preamble.
    """

    Base = generated_module.ScriptRunnerBase
    DeleteScript_Responses = generated_module.DeleteScript_Responses
    ListScripts_Responses = generated_module.ListScripts_Responses
    LoadScript_Responses = generated_module.LoadScript_Responses
    RunScript_IntermediateResponses = generated_module.RunScript_IntermediateResponses
    RunScript_Responses = generated_module.RunScript_Responses
    SaveScript_Responses = generated_module.SaveScript_Responses
    StopScript_Responses = generated_module.StopScript_Responses
    AlreadyRunning = generated_module.scriptrunner_errors.AlreadyRunning
    ScriptError = generated_module.scriptrunner_errors.ScriptError
    ScriptNotFound = generated_module.scriptrunner_errors.ScriptNotFound

    class ScriptRunnerImpl(Base):
        def __init__(self, parent_server) -> None:
            super().__init__(parent_server=parent_server)
            self._process: subprocess.Popen | None = None
            self._lock = threading.Lock()
            self.RunScript_default_lifetime_of_execution = timedelta(minutes=30)
            # Scripts directory inside the server package
            self._scripts_dir = Path(__file__).parent.parent / "scripts"
            self._scripts_dir.mkdir(exist_ok=True)

        def get_IsRunning(self, *, metadata) -> bool:
            return self._process is not None and self._process.poll() is None

        def RunScript(
            self,
            ScriptName: str,
            ScriptCode: str,
            *,
            metadata,
            instance: ObservableCommandInstanceWithIntermediateResponses,
        ) -> RunScript_Responses:
            with self._lock:
                if self._process is not None and self._process.poll() is None:
                    raise AlreadyRunning()

            instance.begin_execution()
            log.info("RunScript: %s", ScriptName)

            # Determine server bind address for gRPC loopback
            server = self.parent_server
            host = "127.0.0.1"
            port = getattr(server, "_port", 50052)
            server_name = getattr(server, "_name", "SiLAServer")

            # Build preamble that creates the device helper
            preamble = f"""\
import sys, os
from sila_server_common.transports.device_helpers import DeviceHelper

device = DeviceHelper({host!r}, {port}, {server_name!r})
"""
            full_code = preamble + "\n" + ScriptCode

            # Write to temp file
            tmp = tempfile.NamedTemporaryFile(
                mode="w", suffix=".py", prefix=f"script_{ScriptName}_",
                delete=False, dir=tempfile.gettempdir(),
            )
            tmp.write(full_code)
            tmp.close()

            output_lines = []
            exit_code = -1

            try:
                # Auto-lock via LockController
                lock_token = f"script-{ScriptName}"
                locked = False
                try:
                    lock_impl = getattr(server, "_lock_controller_impl", None)
                    if lock_impl:
                        lock_impl.LockServer(lock_token, 600, metadata={})
                        locked = True
                        self._send_line(instance, output_lines, f"[ScriptRunner] Device locked (token={lock_token})")
                except Exception as e:
                    self._send_line(instance, output_lines, f"[ScriptRunner] Lock skipped: {e}")

                # Launch subprocess
                process = subprocess.Popen(
                    [sys.executable, "-u", tmp.name],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                )
                with self._lock:
                    self._process = process

                self._send_line(instance, output_lines, f"[ScriptRunner] Started: {ScriptName}")

                for line in process.stdout:
                    line = line.rstrip("\n")
                    self._send_line(instance, output_lines, line)

                process.wait()
                exit_code = process.returncode

                self._send_line(instance, output_lines, f"[ScriptRunner] Finished: exit_code={exit_code}")

            except Exception as e:
                self._send_line(instance, output_lines, f"[ScriptRunner] Error: {e}")
                log.exception("RunScript error")
            finally:
                with self._lock:
                    self._process = None

                if locked:
                    try:
                        lock_impl.UnlockServer(lock_token, metadata={})
                        self._send_line(instance, output_lines, "[ScriptRunner] Device unlocked")
                    except Exception:
                        pass

                try:
                    os.unlink(tmp.name)
                except OSError:
                    pass

            full_output = "\n".join(output_lines)
            return RunScript_Responses(ExitCode=exit_code, FullOutput=full_output)

        @staticmethod
        def _send_line(instance, output_lines, line):
            output_lines.append(line)
            try:
                instance.send_intermediate_response(
                    RunScript_IntermediateResponses(OutputLine=line)
                )
            except Exception:
                pass  # Client may have disconnected

        def StopScript(self, *, metadata) -> StopScript_Responses:
            with self._lock:
                if self._process is None or self._process.poll() is not None:
                    raise ScriptError("No script is currently running")
                try:
                    self._process.terminate()
                    self._process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self._process.kill()
                log.info("StopScript: terminated")
            return StopScript_Responses()

        def ListScripts(self, *, metadata) -> ListScripts_Responses:
            scripts = []
            if self._scripts_dir.is_dir():
                for f in sorted(self._scripts_dir.iterdir()):
                    if f.suffix == ".py":
                        scripts.append(f.stem)
            return ListScripts_Responses(Scripts=scripts)

        def SaveScript(self, ScriptName: str, ScriptCode: str, *, metadata) -> SaveScript_Responses:
            path = self._scripts_dir / f"{ScriptName}.py"
            path.write_text(ScriptCode, encoding="utf-8")
            log.info("SaveScript: %s", ScriptName)
            return SaveScript_Responses()

        def LoadScript(self, ScriptName: str, *, metadata) -> LoadScript_Responses:
            path = self._scripts_dir / f"{ScriptName}.py"
            if not path.is_file():
                raise ScriptNotFound(f"Script '{ScriptName}' not found")
            code = path.read_text(encoding="utf-8")
            return LoadScript_Responses(ScriptCode=code)

        def DeleteScript(self, ScriptName: str, *, metadata) -> DeleteScript_Responses:
            path = self._scripts_dir / f"{ScriptName}.py"
            if not path.is_file():
                raise ScriptNotFound(f"Script '{ScriptName}' not found")
            path.unlink()
            log.info("DeleteScript: %s", ScriptName)
            return DeleteScript_Responses()

    return ScriptRunnerImpl

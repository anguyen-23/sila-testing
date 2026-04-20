"""Run Ansible playbooks and stream output back to the web UI."""
from __future__ import annotations

import os
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional

# Path to the deployment directory (parent of admin_console)
DEPLOYMENT_DIR = os.path.join(os.path.dirname(__file__), "..")
PLAYBOOKS_DIR = os.path.join(DEPLOYMENT_DIR, "playbooks")


@dataclass
class Job:
    id: str
    playbook: str
    limit: str
    status: str = "pending"  # pending, running, completed, failed
    output_lines: List[str] = field(default_factory=list)
    return_code: Optional[int] = None
    started_at: Optional[float] = None
    finished_at: Optional[float] = None

    def elapsed(self) -> Optional[float]:
        if self.started_at is None:
            return None
        end = self.finished_at or time.time()
        return round(end - self.started_at, 1)


# In-memory job store
_jobs: Dict[str, Job] = {}
_jobs_lock = threading.Lock()


def get_job(job_id: str) -> Optional[Job]:
    with _jobs_lock:
        return _jobs.get(job_id)


def list_jobs() -> List[Job]:
    with _jobs_lock:
        return list(reversed(_jobs.values()))


def run_playbook(playbook: str, limit: str = "", extra_vars: Optional[Dict] = None) -> Job:
    """Start an ansible-playbook run in a background thread. Returns the Job."""
    job = Job(
        id=str(uuid.uuid4())[:8],
        playbook=playbook,
        limit=limit,
    )
    with _jobs_lock:
        _jobs[job.id] = job

    thread = threading.Thread(
        target=_run_playbook_thread,
        args=(job, extra_vars),
        daemon=True,
    )
    thread.start()
    return job


def _run_playbook_thread(job: Job, extra_vars: Optional[Dict] = None) -> None:
    playbook_path = os.path.join(PLAYBOOKS_DIR, job.playbook)
    if not os.path.isfile(playbook_path):
        job.status = "failed"
        job.output_lines.append(f"Playbook not found: {playbook_path}")
        job.return_code = 1
        return

    cmd = ["ansible-playbook", playbook_path]
    if job.limit:
        cmd.extend(["-l", job.limit])
    if extra_vars:
        for k, v in extra_vars.items():
            cmd.extend(["-e", f"{k}={v}"])

    job.status = "running"
    job.started_at = time.time()
    job.output_lines.append(f"$ {' '.join(cmd)}\n")

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            cwd=DEPLOYMENT_DIR,
            env={**os.environ, "ANSIBLE_FORCE_COLOR": "0"},
        )
        for line in proc.stdout:
            job.output_lines.append(line)
        proc.wait()
        job.return_code = proc.returncode
        job.status = "completed" if proc.returncode == 0 else "failed"
    except FileNotFoundError:
        job.output_lines.append(
            "ERROR: ansible-playbook not found. "
            "The admin console must run on a machine with Ansible installed "
            "(e.g., WSL2 with the ansible venv activated).\n"
        )
        job.status = "failed"
        job.return_code = 127
    except Exception as e:
        job.output_lines.append(f"ERROR: {e}\n")
        job.status = "failed"
        job.return_code = 1
    finally:
        job.finished_at = time.time()

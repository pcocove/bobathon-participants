"""Background jobs: analysis runs in its own thread; the UI only polls the state."""
from __future__ import annotations

import threading
import traceback
import uuid
from datetime import datetime, timezone

from .config import SETTINGS
from .pipeline import STAGES, Progress, run_pipeline
from .store import read_json, write_json

JOB_FILE = SETTINGS.state_dir / "jobs" / "last_job.json"


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Job(Progress):
    def __init__(self, stages: list[str], force: bool):
        super().__init__()
        self.id = uuid.uuid4().hex[:8]
        self.stages = stages
        self.force = force
        self.status = "running"
        self.stage_key = None
        self.stage_label = None
        self.done = 0
        self.total = 0
        self.log_lines: list[dict] = []
        self.started_at = now()
        self.finished_at = None
        self.error = None
        self.completed_stages: list[str] = []

    def stage(self, key, label, total):
        if self.stage_key and self.stage_key not in self.completed_stages:
            self.completed_stages.append(self.stage_key)
        self.stage_key, self.stage_label, self.total, self.done = key, label, total, 0
        self.log(f"Stage: {label}")

    def step(self, n=1, msg=None):
        self.done += n
        if msg:
            self.log(msg)
        self.save()

    def log(self, msg):
        self.log_lines.append({"t": now(), "msg": msg})
        del self.log_lines[:-200]
        self.save()

    def to_dict(self) -> dict:
        return {"id": self.id, "stages": self.stages, "force": self.force, "status": self.status, "stage": self.stage_key,
                "stage_label": self.stage_label, "done": self.done, "total": self.total, "log": self.log_lines[-60:],
                "started_at": self.started_at, "finished_at": self.finished_at, "error": self.error,
                "completed_stages": self.completed_stages, "all_stages": [k for k, _ in STAGES]}

    def save(self):
        write_json(JOB_FILE, self.to_dict())


class Runner:
    def __init__(self):
        self.current: Job | None = None
        self.lock = threading.Lock()

    def start(self, stages: list[str] | None, force: bool = False) -> Job:
        with self.lock:
            if self.current and self.current.status == "running":
                raise RuntimeError("An analysis is already running.")
            valid = [k for k, _ in STAGES]
            stages = [s for s in (stages or valid) if s in valid]
            job = Job(stages, force)
            self.current = job
        threading.Thread(target=self._run, args=(job,), daemon=True).start()
        return job

    def _run(self, job: Job):
        try:
            run_pipeline(job, job.stages, force=job.force)
            if job.stage_key and job.stage_key not in job.completed_stages:
                job.completed_stages.append(job.stage_key)
            job.status = "cancelled" if job.cancelled else "done"
        except Exception as e:  # noqa: BLE001
            job.status = "error"
            job.error = f"{type(e).__name__}: {e}"
            job.log(traceback.format_exc()[-1500:])
        finally:
            job.finished_at = now()
            job.save()

    def cancel(self):
        if self.current and self.current.status == "running":
            self.current.cancelled = True
            self.current.log("Cancel requested – Bob requests in progress will still finish.")

    def state(self) -> dict | None:
        if self.current:
            return self.current.to_dict()
        return read_json(JOB_FILE)


RUNNER = Runner()

from __future__ import annotations

import shutil
import time
import uuid
from dataclasses import dataclass, asdict
from pathlib import Path
from threading import Lock

from .settings import DOWNLOAD_DIR


@dataclass
class Job:
    id: str
    status: str = "queued"
    progress: int = 0
    message: str = "Queued"
    title: str | None = None
    filename: str | None = None
    file_path: str | None = None
    error: str | None = None
    speed: float | None = None
    eta: int | None = None
    downloaded_bytes: int | None = None
    total_bytes: int | None = None
    created_at: float = 0.0
    updated_at: float = 0.0

    def public(self) -> dict:
        data = asdict(self)
        data.pop("file_path", None)
        return data


class JobStore:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = Lock()

    def create(self) -> Job:
        now = time.time()
        job = Job(id=uuid.uuid4().hex, created_at=now, updated_at=now)
        with self._lock:
            self._jobs[job.id] = job
        (DOWNLOAD_DIR / job.id).mkdir(parents=True, exist_ok=True)
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def update(self, job_id: str, **changes) -> Job | None:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return None
            for key, value in changes.items():
                if hasattr(job, key):
                    setattr(job, key, value)
            job.updated_at = time.time()
            return job

    def remove(self, job_id: str) -> None:
        with self._lock:
            self._jobs.pop(job_id, None)
        shutil.rmtree(DOWNLOAD_DIR / job_id, ignore_errors=True)

    def purge_orphans(self) -> None:
        """Delete download folders left by a previous run; jobs only live in memory."""
        with self._lock:
            active = set(self._jobs)
        for path in DOWNLOAD_DIR.iterdir():
            if path.is_dir() and path.name not in active:
                shutil.rmtree(path, ignore_errors=True)

    def cleanup_older_than(self, seconds: int) -> int:
        cutoff = time.time() - seconds
        stale: list[str] = []
        with self._lock:
            for job_id, job in self._jobs.items():
                if job.updated_at < cutoff:
                    stale.append(job_id)
        for job_id in stale:
            self.remove(job_id)
        return len(stale)


jobs = JobStore()

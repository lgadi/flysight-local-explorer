from __future__ import annotations

import os
import shutil
import tempfile
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from . import mtools

_lock = threading.Lock()
_jobs: dict[str, "Job"] = {}
_order: deque[str] = deque()


@dataclass
class Job:
    id: str
    kind: str                       # "copy" | "upload"
    label: str                      # short description for UI
    status: str = "pending"         # "pending" | "running" | "done" | "error"
    progress_done: int = 0          # files completed
    progress_total: int = 0         # files expected (0 if unknown)
    error: str | None = None
    started_at: float = 0.0
    finished_at: float | None = None
    log: list[str] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def append_log(self, line: str) -> None:
        with self._lock:
            self.log.append(line)
            # cap at 500 lines to keep memory bounded
            if len(self.log) > 500:
                del self.log[: len(self.log) - 500]

    def as_dict(self) -> dict[str, Any]:
        with self._lock:
            return {
                "id": self.id,
                "kind": self.kind,
                "label": self.label,
                "status": self.status,
                "progress_done": self.progress_done,
                "progress_total": self.progress_total,
                "error": self.error,
                "started_at": self.started_at,
                "finished_at": self.finished_at,
                "log_tail": self.log[-30:],
            }


def _register(job: Job) -> None:
    with _lock:
        _jobs[job.id] = job
        _order.appendleft(job.id)
        # keep at most 50 historical jobs
        while len(_order) > 50:
            old = _order.pop()
            _jobs.pop(old, None)


def get(job_id: str) -> Job | None:
    with _lock:
        return _jobs.get(job_id)


def all() -> list[Job]:
    with _lock:
        return [_jobs[i] for i in _order if i in _jobs]


def recent(n: int = 5) -> list[Job]:
    return all()[:n]


def start_copy(raw_node: str, fat_path: str, local_dest: str) -> str:
    job = Job(
        id=uuid.uuid4().hex[:12],
        kind="copy",
        label=f"Copy {fat_path}  →  {local_dest}",
        started_at=time.time(),
    )
    _register(job)

    def run() -> None:
        job.status = "running"
        try:
            total = mtools.count_entries(raw_node, fat_path)
            job.progress_total = total
            for line in mtools.stream_copy_to_local(raw_node, fat_path, local_dest):
                job.append_log(line)
                if line.lower().startswith("copying ") or line.lower().startswith("copy "):
                    job.progress_done += 1
            job.status = "done"
        except Exception as exc:
            job.status = "error"
            job.error = str(exc)
            job.append_log(f"ERROR: {exc}")
        finally:
            job.finished_at = time.time()

    threading.Thread(target=run, daemon=True, name=f"copy-{job.id}").start()
    return job.id


def start_upload(raw_node: str, fat_dest: str, files: list) -> str:
    # Materialize uploads to a temp dir first so the mcopy call is just local→card.
    staging = tempfile.mkdtemp(prefix="flysight-upload-")
    local_paths: list[str] = []
    for f in files:
        if not f.filename:
            continue
        # strip any path components from filename to prevent traversal
        safe_name = os.path.basename(f.filename)
        if not safe_name:
            continue
        target = os.path.join(staging, safe_name)
        f.save(target)
        local_paths.append(target)

    label = f"Upload {len(local_paths)} file(s)  →  {fat_dest}"
    job = Job(
        id=uuid.uuid4().hex[:12],
        kind="upload",
        label=label,
        started_at=time.time(),
        progress_total=len(local_paths),
    )
    _register(job)

    def run() -> None:
        job.status = "running"
        try:
            if not local_paths:
                raise mtools.MToolsError("no files received")
            for line in mtools.stream_upload(raw_node, local_paths, fat_dest):
                job.append_log(line)
                if line.lower().startswith("copying ") or line.lower().startswith("copy "):
                    job.progress_done += 1
            job.status = "done"
        except Exception as exc:
            job.status = "error"
            job.error = str(exc)
            job.append_log(f"ERROR: {exc}")
        finally:
            job.finished_at = time.time()
            shutil.rmtree(staging, ignore_errors=True)

    threading.Thread(target=run, daemon=True, name=f"upload-{job.id}").start()
    return job.id


__all__ = [
    "Job",
    "all",
    "get",
    "recent",
    "start_copy",
    "start_upload",
]

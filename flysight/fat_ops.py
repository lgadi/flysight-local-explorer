"""Direct FAT operations beyond what mtools exposes (currently: mtime touch)."""
from __future__ import annotations

import subprocess
import sys
from datetime import date
from pathlib import Path

from . import sudo_auth
from .mtools import MToolsError, _op_lock

_WORKER = Path(__file__).parent / "_touch_worker.py"


def touch(raw_node: str, fat_path: str, new_date: date) -> None:
    """Set mtime of `fat_path` on the FAT volume at `raw_node` to
    `new_date` at 00:00:00 UTC. Holds the global mtools op-lock to avoid
    interleaving with mtools writes on the same device.

    Note: pyfatfs scans FAT metadata when opening the device. Over the
    FlySight's USB 2.0 full-speed MSC link (~150 kB/s) this can take
    several minutes on a 30 GB FAT32 partition, so the timeout is set
    generously."""
    pw = sudo_auth.get()
    argv = [
        "sudo", "-S", "-p", "",
        sys.executable, str(_WORKER),
        raw_node, fat_path, new_date.isoformat(),
    ]
    with _op_lock:
        result = subprocess.run(
            argv,
            input=(pw + "\n").encode(),
            capture_output=True,
            timeout=600,
        )
    # Surface the worker's stderr (timing instrumentation, pyfatfs
    # warnings) to the Flask process's stderr regardless of exit
    # status, so the user can see what's happening.
    if result.stderr:
        sys.stderr.write(result.stderr.decode(errors="replace"))
        sys.stderr.flush()
    if result.returncode != 0:
        err = result.stderr.decode(errors="replace").strip() or f"touch exited {result.returncode}"
        raise MToolsError(f"touch {fat_path}: {err}")

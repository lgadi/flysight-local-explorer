from __future__ import annotations

import os
import re
import shlex
import subprocess
import threading
from dataclasses import dataclass
from typing import Iterator

from flask import Response

from . import sudo_auth

# Single global lock — mtools talks to the raw block device, and concurrent
# SCSI traffic against the same USB-MSC endpoint would corrupt the FAT.
_op_lock = threading.Lock()


class MToolsError(RuntimeError):
    pass


@dataclass(frozen=True)
class Entry:
    name: str          # human-facing name (long filename if present, else 8.3 with dot)
    is_dir: bool
    size: int | None   # None for directories
    date: str          # raw "YYYY-MM-DD" from mdir; may be "1980-00-00" if RTC was unset
    time: str          # raw "H:MM" from mdir


_LINE_RE = re.compile(
    r"^"
    r"(?P<sname>.+?)\s+"
    r"(?P<size><DIR>|\d+)\s+"
    r"(?P<date>\d{4}-\d{2}-\d{2})\s+"
    r"(?P<time>\d{1,2}:\d{2})"
    r"(?:\s+(?P<lfn>\S.*?))?\s*$"
)


def _sudo_argv(args: list[str]) -> list[str]:
    return ["sudo", "-S", "-p", ""] + args


def _run(args: list[str], timeout: int = 60) -> subprocess.CompletedProcess[bytes]:
    """Run a sudo'd command, returning the completed process. Holds the global op lock."""
    pw = sudo_auth.get()
    with _op_lock:
        return subprocess.run(
            _sudo_argv(args),
            input=(pw + "\n").encode(),
            capture_output=True,
            timeout=timeout,
        )


def _check(args: list[str], timeout: int = 60) -> str:
    result = _run(args, timeout=timeout)
    if result.returncode != 0:
        raise MToolsError(
            f"{' '.join(shlex.quote(a) for a in args)} failed: "
            + (result.stderr.decode(errors="replace").strip() or f"exit {result.returncode}")
        )
    return result.stdout.decode(errors="replace")


def list_dir(raw_node: str, path: str) -> list[Entry]:
    fat_path = _fat_dir_path(path)
    out = _check(["mdir", "-a", "-i", raw_node, fat_path], timeout=30)
    return _parse_mdir(out)


def _fat_dir_path(path: str) -> str:
    path = path.strip()
    if not path or path == "/":
        return "::/"
    if not path.startswith("/"):
        path = "/" + path
    if not path.endswith("/"):
        path = path + "/"
    return "::" + path


def _fat_file_path(path: str) -> str:
    if not path.startswith("/"):
        path = "/" + path
    return "::" + path


def _parse_mdir(output: str) -> list[Entry]:
    entries: list[Entry] = []
    in_listing = False
    for raw_line in output.splitlines():
        if raw_line.startswith("Directory for"):
            in_listing = True
            continue
        if not in_listing:
            continue
        line = raw_line.rstrip()
        if not line.strip():
            continue
        if line.startswith(" Volume"):
            continue
        # Footer: " 698 files  900000 bytes" / "  900000 bytes free"
        if re.match(r"\s*\d+\s+files?\s+", line) or re.search(r"\bbytes free\b", line):
            continue

        m = _LINE_RE.match(line)
        if not m:
            continue

        size_field = m.group("size")
        is_dir = size_field == "<DIR>"
        size = None if is_dir else int(size_field)

        lfn = (m.group("lfn") or "").strip()
        sname = m.group("sname").strip()
        display = lfn or _short_to_dotted(sname)

        # Skip "." and ".." entries
        if display in {".", ".."}:
            continue

        entries.append(Entry(
            name=display,
            is_dir=is_dir,
            size=size,
            date=m.group("date"),
            time=m.group("time"),
        ))
    entries.sort(key=lambda e: (not e.is_dir, e.name.lower()))
    return entries


SORT_KEYS = ("name", "size", "date")


def sort_entries(entries: list[Entry], sort: str, direction: str, dirs_first: bool = True) -> list[Entry]:
    """Sort entries by the chosen key + direction. Directories are grouped at the top by default."""
    sort = sort if sort in SORT_KEYS else "name"
    reverse = direction == "desc"

    def name_key(e: Entry) -> tuple:
        return (e.name.lower(),)

    def size_key(e: Entry) -> tuple:
        # Dirs (size=None) sort as 0 alongside zero-byte files; usually the
        # dirs_first grouping above means they don't visually overlap files
        # at the same size.
        return (e.size if e.size is not None else 0,)

    def date_key(e: Entry) -> tuple:
        # Parse YYYY-MM-DD and H:MM into a tuple; tolerate the "1980-00-00"
        # bogus-RTC marker by leaving its components at 0, which sorts before
        # any real date.
        try:
            y, mo, d = (int(x) for x in e.date.split("-"))
        except ValueError:
            y, mo, d = 0, 0, 0
        try:
            h, mi = (int(x) for x in e.time.split(":"))
        except ValueError:
            h, mi = 0, 0
        return (y, mo, d, h, mi, e.name.lower())

    key_fn = {"name": name_key, "size": size_key, "date": date_key}[sort]

    if dirs_first:
        dirs = sorted([e for e in entries if e.is_dir], key=key_fn, reverse=reverse)
        files = sorted([e for e in entries if not e.is_dir], key=key_fn, reverse=reverse)
        return dirs + files
    return sorted(entries, key=key_fn, reverse=reverse)


def _short_to_dotted(sname: str) -> str:
    # "AUDIO" -> "AUDIO"; "FLYSIGHT TXT" -> "FLYSIGHT.TXT"
    parts = sname.split()
    if len(parts) == 1:
        return parts[0]
    if len(parts) == 2:
        return f"{parts[0]}.{parts[1]}"
    return sname


def read_file_bytes(raw_node: str, path: str, max_bytes: int) -> bytes:
    """Read up to `max_bytes` bytes of a file off the card via mcopy stdout.
    Used for the preview endpoint; caller closes the read side as soon as
    enough bytes arrive so mcopy is killed via SIGPIPE on its next write."""
    fat_path = _fat_file_path(path)
    pw = sudo_auth.get()
    argv = _sudo_argv(["mcopy", "-i", raw_node, "-n", fat_path, "-"])
    with _op_lock:
        proc = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        assert proc.stdin and proc.stdout
        try:
            proc.stdin.write((pw + "\n").encode())
            proc.stdin.close()
            buf = bytearray()
            while len(buf) < max_bytes:
                chunk = proc.stdout.read(min(8192, max_bytes - len(buf)))
                if not chunk:
                    break
                buf.extend(chunk)
        finally:
            try:
                proc.stdout.close()
            except OSError:
                pass
            proc.wait()
    return bytes(buf)


def stream_file(raw_node: str, path: str):
    """Stream a single file off the card to the browser via mcopy stdout."""
    fat_path = _fat_file_path(path)
    name = os.path.basename(path) or "download.bin"
    pw = sudo_auth.get()
    argv = _sudo_argv(["mcopy", "-i", raw_node, "-n", "-m", fat_path, "-"])

    def gen():
        with _op_lock:
            proc = subprocess.Popen(
                argv,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            assert proc.stdin and proc.stdout
            try:
                proc.stdin.write((pw + "\n").encode())
                proc.stdin.close()
                while True:
                    chunk = proc.stdout.read(64 * 1024)
                    if not chunk:
                        break
                    yield chunk
            finally:
                proc.wait()

    return Response(
        gen(),
        mimetype="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


def delete(raw_node: str, path: str, recursive: bool) -> None:
    if recursive:
        # mdeltree wants no trailing slash
        fat_path = _fat_file_path(path).rstrip("/")
        _check(["mdeltree", "-i", raw_node, fat_path], timeout=120)
    else:
        fat_path = _fat_file_path(path)
        _check(["mdel", "-i", raw_node, fat_path], timeout=60)


def count_entries(raw_node: str, path: str) -> int:
    """Recursively count files+dirs under path. Used as a denominator for copy progress."""
    fat_path = _fat_dir_path(path) if path != "/" else "::/"
    try:
        out = _check(["mdir", "-/", "-b", "-a", "-i", raw_node, fat_path], timeout=60)
    except MToolsError:
        return 0
    return sum(1 for line in out.splitlines() if line.strip())


def tree_size(raw_node: str, path: str) -> int:
    """Total bytes of all files under path (recursive). Returns 0 on failure."""
    fat_path = _fat_dir_path(path) if path != "/" else "::/"
    try:
        out = _check(["mdir", "-/", "-a", "-i", raw_node, fat_path], timeout=180)
    except MToolsError:
        # Maybe path is a single file, not a dir — try that.
        try:
            out = _check(["mdir", "-a", "-i", raw_node, _fat_file_path(path)], timeout=30)
        except MToolsError:
            return 0
    total = 0
    for raw_line in out.splitlines():
        m = _LINE_RE.match(raw_line.rstrip())
        if m and m.group("size") != "<DIR>":
            try:
                total += int(m.group("size"))
            except ValueError:
                pass
    return total


def stream_copy_to_local(
    raw_node: str,
    fat_path: str,
    local_dest: str,
) -> Iterator[str]:
    """Yield lines of mcopy -v output for one fat_path copied into local_dest. Holds the op lock for the duration."""
    pw = sudo_auth.get()
    os.makedirs(local_dest, exist_ok=True)
    argv = _sudo_argv(["mcopy", "-i", raw_node, "-s", "-p", "-m", "-o", "-v", _fat_file_path(fat_path), local_dest + "/"])
    with _op_lock:
        proc = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=1,
            text=True,
        )
        assert proc.stdin and proc.stdout
        proc.stdin.write(pw + "\n")
        proc.stdin.close()
        try:
            for line in proc.stdout:
                yield line.rstrip()
        finally:
            rc = proc.wait()
            if rc != 0:
                raise MToolsError(f"mcopy exited with status {rc}")


def stream_upload(
    raw_node: str,
    local_paths: list[str],
    fat_dest: str,
) -> Iterator[str]:
    """Yield lines of mcopy -v output for local files into fat_dest (a directory on the card)."""
    pw = sudo_auth.get()
    fat_dir = _fat_dir_path(fat_dest)
    argv = _sudo_argv(["mcopy", "-i", raw_node, "-s", "-p", "-m", "-o", "-v"] + local_paths + [fat_dir])
    with _op_lock:
        proc = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=1,
            text=True,
        )
        assert proc.stdin and proc.stdout
        proc.stdin.write(pw + "\n")
        proc.stdin.close()
        try:
            for line in proc.stdout:
                yield line.rstrip()
        finally:
            rc = proc.wait()
            if rc != 0:
                raise MToolsError(f"mcopy exited with status {rc}")

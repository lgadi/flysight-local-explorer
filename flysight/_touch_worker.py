"""Set the mtime of a path on a FAT volume.

Invoked as a sudo'd subprocess from the main app so root privileges
are scoped to just this single write rather than the whole Flask
process.

Usage: _touch_worker.py <device-or-image> <fat-path> <YYYY-MM-DD>

Sets mtime to 00:00:00 UTC on the given date. Exits 0 on success,
1 with a single-line error on stderr otherwise.
"""
from __future__ import annotations

import sys
from datetime import date as _date, datetime, time as _time, timezone


def main(argv: list[str]) -> int:
    if len(argv) != 4:
        print("usage: _touch_worker.py <device> <fat-path> <YYYY-MM-DD>", file=sys.stderr)
        return 2

    device, fat_path, date_str = argv[1], argv[2], argv[3]
    try:
        d = _date.fromisoformat(date_str)
    except ValueError as exc:
        print(f"invalid date {date_str!r}: {exc}", file=sys.stderr)
        return 2

    target = datetime.combine(d, _time(0, 0, 0), tzinfo=timezone.utc)

    # Imported here (post arg-check) so a missing dep yields a clearer
    # error. Suppress PyFilesystem2's pkg_resources deprecation warning
    # which spams stderr on every invocation.
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=UserWarning)
        from pyfatfs.PyFatFS import PyFatFS

    pfs = PyFatFS(device, read_only=False)
    try:
        pfs.setinfo(fat_path, {"details": {"modified": target.timestamp()}})
    finally:
        pfs.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

from __future__ import annotations

import subprocess
import threading

_lock = threading.Lock()
_password: str | None = None


class NotAuthenticated(RuntimeError):
    pass


def is_set() -> bool:
    with _lock:
        return _password is not None


def try_set(password: str) -> tuple[bool, str | None]:
    if not password:
        return False, "Password is empty."
    # -k forces sudo to ignore any cached credentials, so a successful
    # exit code means *this* password actually authenticated.
    result = subprocess.run(
        ["sudo", "-S", "-k", "-p", "", "true"],
        input=(password + "\n").encode(),
        capture_output=True,
        timeout=10,
    )
    if result.returncode == 0:
        global _password
        with _lock:
            _password = password
        return True, None
    stderr = result.stderr.decode(errors="replace").strip()
    return False, stderr or "sudo authentication failed."


def get() -> str:
    with _lock:
        if _password is None:
            raise NotAuthenticated("sudo password not set")
        return _password


def clear() -> None:
    global _password
    with _lock:
        _password = None

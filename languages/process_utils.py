"""Shared, safe subprocess settings for all language executors.

Why this exists:
  * ``subprocess.TimeoutExpired.stdout/stderr`` are *bytes* even when the call
    used ``text=True``; concatenating them with a ``str`` crashed the executors
    whenever a program produced output before timing out.
  * Decoding with the locale codec raised ``UnicodeDecodeError`` for programs
    that emit non-UTF-8 bytes, which is common for buggy programs.
  * Inheriting the parent's stdin let ``input()`` block on the user's terminal.
"""
import subprocess
from typing import Optional, Union

RUN_KWARGS = {
    "capture_output": True,
    "text": True,
    "encoding": "utf-8",
    "errors": "replace",
    "stdin": subprocess.DEVNULL,
    "check": False,
}


def decode_output(value: Optional[Union[str, bytes]]) -> str:
    """Return ``value`` as text regardless of whether it is None, bytes or str."""
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def timeout_result(exc: subprocess.TimeoutExpired, message: str) -> dict:
    """Build the executor result dict for a timed-out process."""
    stderr = decode_output(exc.stderr)
    return {
        "stdout": decode_output(exc.stdout),
        "stderr": f"{stderr}\n{message}" if stderr else message,
        "returncode": 124,
        "timed_out": True,
    }


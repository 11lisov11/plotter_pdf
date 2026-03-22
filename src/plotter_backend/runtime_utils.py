from __future__ import annotations

import time
from pathlib import Path


def format_duration_hms(seconds: float) -> str:
    value = max(0.0, float(seconds))
    total = int(round(value))
    hours = total // 3600
    minutes = (total % 3600) // 60
    secs = total % 60
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def format_internal_exception(prefix: str, exc: Exception) -> str:
    return f"{prefix} ({type(exc).__name__}): {exc}"


def ensure_local_tmp_root(local_tmp_root: Path) -> Path:
    local_tmp_root.mkdir(parents=True, exist_ok=True)
    return local_tmp_root


def wait_until_path_unlocked(path: Path, timeout_s: float = 8.0, poll_s: float = 0.20) -> bool:
    deadline = time.time() + max(0.2, float(timeout_s))
    poll = max(0.05, float(poll_s))
    while time.time() < deadline:
        try:
            if not path.exists():
                return True
            with path.open("rb"):
                pass
            return True
        except Exception:
            time.sleep(poll)
    return False

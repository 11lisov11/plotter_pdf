from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Iterable


@dataclass(frozen=True)
class SenderProcess:
    pid: int
    command_line: str


def _normalize_path(value: str | Path | None) -> str:
    if value is None:
        return ""
    try:
        return str(Path(value).resolve()).casefold()
    except Exception:
        return str(value).casefold()


def _path_match_tokens(value: str | Path | None) -> list[str]:
    if value is None:
        return []
    raw = str(value)
    tokens: list[str] = []
    for item in (raw, str(Path(raw)), _normalize_path(raw), Path(raw).name):
        item_norm = str(item or "").strip().casefold()
        if item_norm and item_norm not in tokens:
            tokens.append(item_norm)
    return tokens


def _query_python_process_rows(*, run: Callable[..., Any] = subprocess.run) -> list[dict[str, Any]]:
    if os.name != "nt":
        return []
    ps = (
        "Get-CimInstance Win32_Process -Filter \"name = 'python.exe' or name = 'py.exe'\" | "
        "Select-Object ProcessId,CommandLine | ConvertTo-Json -Compress"
    )
    try:
        proc = run(
            ["powershell", "-NoProfile", "-Command", ps],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
            check=False,
        )
    except Exception:
        return []
    if getattr(proc, "returncode", 1) != 0 or not str(getattr(proc, "stdout", "")).strip():
        return []
    try:
        payload = json.loads(proc.stdout)
    except Exception:
        return []
    rows = payload if isinstance(payload, list) else [payload]
    return [row for row in rows if isinstance(row, dict)]


def find_sender_processes(
    *,
    port: str | None = None,
    file_path: str | Path | None = None,
    process_rows: Iterable[dict[str, Any]] | None = None,
    current_pid: int | None = None,
) -> list[SenderProcess]:
    target_port = str(port or "").casefold()
    target_file_tokens = _path_match_tokens(file_path)
    rows = list(process_rows) if process_rows is not None else _query_python_process_rows()
    own_pid = os.getpid() if current_pid is None else int(current_pid)
    matches: list[SenderProcess] = []
    for row in rows:
        try:
            pid = int(row.get("ProcessId") or row.get("pid") or 0)
        except Exception:
            continue
        if pid <= 0 or pid == own_pid:
            continue
        cmd = str(row.get("CommandLine") or row.get("command_line") or "")
        cmd_norm = cmd.casefold()
        if "send_grbl_file.py" not in cmd_norm:
            continue
        if target_port and target_port not in cmd_norm:
            continue
        if target_file_tokens and not any(token in cmd_norm for token in target_file_tokens):
            continue
        matches.append(SenderProcess(pid=pid, command_line=cmd))
    return matches


def stop_sender_processes(
    processes: Iterable[SenderProcess],
    *,
    run: Callable[..., Any] = subprocess.run,
) -> tuple[bool, str]:
    pids = [str(proc.pid) for proc in processes]
    if not pids:
        return True, "No matching sender processes."
    ps = "Stop-Process -Id " + ",".join(pids) + " -Force"
    try:
        proc = run(
            ["powershell", "-NoProfile", "-Command", ps],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            check=False,
        )
    except Exception as exc:
        return False, f"Failed to stop sender process(es): {type(exc).__name__}: {exc}"
    if getattr(proc, "returncode", 1) != 0:
        detail = str(getattr(proc, "stderr", "") or getattr(proc, "stdout", "") or "").strip()
        return False, f"Failed to stop sender process(es): {detail}"
    return True, "Stopped sender process(es): " + ", ".join(pids)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Diagnose or stop stuck send_grbl_file.py processes.")
    parser.add_argument("--port", default=None, help="Filter by COM/TCP endpoint, e.g. COM6 or tcp://192.168.4.1:23.")
    parser.add_argument("--file", default=None, help="Filter by G-code file path.")
    parser.add_argument("--stop", action="store_true", help="Stop matching sender process(es).")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    args = parser.parse_args(argv)

    processes = find_sender_processes(port=args.port, file_path=args.file)
    if args.json:
        print(json.dumps([asdict(proc) for proc in processes], ensure_ascii=False, indent=2))
    elif not processes:
        print("No running send_grbl_file.py processes match.")
    else:
        print("Matching send_grbl_file.py process(es):")
        for proc in processes:
            print(f"  PID {proc.pid}: {proc.command_line}")

    if args.stop:
        ok, msg = stop_sender_processes(processes)
        print(msg)
        return 0 if ok else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

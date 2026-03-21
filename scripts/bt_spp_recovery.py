from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.plotter_backend.machine.windows_bt_spp import (  # noqa: E402
    BTWRITER_ADDRESS,
    BTWRITER_NAME,
    attempt_soft_repair,
    collect_windows_bt_spp_diagnostics,
)


def _print_report(report: dict) -> None:
    print(f"Platform: {report.get('platform', '')}")
    print(f"Preferred port: {report.get('preferred_port', '') or '-'}")
    print(f"Device: {report.get('device_name', '')} [{report.get('device_address', '')}]")
    print(f"Summary: {report.get('summary', '')}")

    live_ports = list(report.get("live_serial_devices") or [])
    print(f"Live serial ports: {', '.join(live_ports) if live_ports else 'none'}")

    live_bt = list(report.get("live_bt_ports") or [])
    print(f"Live Bluetooth SPP ports: {', '.join(live_bt) if live_bt else 'none'}")

    live_usb = list(report.get("live_usb_ports") or [])
    print(f"Live USB ports: {', '.join(live_usb) if live_usb else 'none'}")

    ghost_ports = list(report.get("ghost_spp_ports") or [])
    print(f"Ghost SPP ports: {', '.join(ghost_ports) if ghost_ports else 'none'}")

    code = report.get("rfcomm_problem_code")
    status = report.get("rfcomm_problem_status", "")
    if code not in (None, "") or status:
        suffix = f", status={status}" if status else ""
        print(f"RFCOMM problem: code={code}{suffix}")

    if report.get("collection_error"):
        print(f"Diagnostic collection error: {report['collection_error']}")

    steps = list(report.get("recovery_steps") or [])
    if steps:
        print("")
        print("Recovery steps:")
        for idx, step in enumerate(steps, start=1):
            print(f"{idx}. {step}")


def _print_actions(repair: dict) -> None:
    print("")
    print(f"Soft repair admin mode: {'yes' if repair.get('admin') else 'no'}")
    for idx, action in enumerate(list(repair.get("actions") or []), start=1):
        cmd = " ".join(str(part) for part in list(action.get("command") or []))
        print(f"[{idx}] {'OK' if action.get('ok') else 'FAIL'} {cmd}")
        stdout = str(action.get("stdout") or "").strip()
        stderr = str(action.get("stderr") or "").strip()
        if stdout:
            print(f"    stdout: {stdout}")
        if stderr:
            print(f"    stderr: {stderr}")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Diagnose and recover the BtWriter Bluetooth SPP / RFCOMM mapping."
    )
    parser.add_argument("--preferred-port", default="", help="Port that failed, e.g. COM11.")
    parser.add_argument("--device-name", default=BTWRITER_NAME, help="Paired Bluetooth device name.")
    parser.add_argument("--device-address", default=BTWRITER_ADDRESS, help="Bluetooth device address without separators.")
    parser.add_argument("--json", action="store_true", help="Print JSON only.")
    parser.add_argument(
        "--attempt-soft-repair",
        action="store_true",
        help="Run non-destructive recovery steps. Ghost-port removal and service restart require admin.",
    )
    args = parser.parse_args(argv[1:])

    if args.attempt_soft_repair:
        payload = attempt_soft_repair(
            preferred_port=(args.preferred_port or "").strip(),
            device_name=str(args.device_name or BTWRITER_NAME).strip() or BTWRITER_NAME,
            device_address=str(args.device_address or BTWRITER_ADDRESS).strip() or BTWRITER_ADDRESS,
        )
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 0
        print("Before:")
        _print_report(dict(payload.get("before") or {}))
        _print_actions(payload)
        print("")
        print("After:")
        _print_report(dict(payload.get("after") or {}))
        return 0

    report = collect_windows_bt_spp_diagnostics(
        preferred_port=(args.preferred_port or "").strip(),
        device_name=str(args.device_name or BTWRITER_NAME).strip() or BTWRITER_NAME,
        device_address=str(args.device_address or BTWRITER_ADDRESS).strip() or BTWRITER_ADDRESS,
    )
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    _print_report(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

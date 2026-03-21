from __future__ import annotations

import ctypes
import re
import subprocess
import sys
from typing import Any, Optional


BTWRITER_NAME = "BtWriter"
BTWRITER_ADDRESS = "A4F00F75C50E"
SPP_SERVICE_GUID = "{00001101-0000-1000-8000-00805F9B34FB}"
RECOVERY_SCRIPT = r"python scripts\bt_spp_recovery.py"
RECOVERY_DOC = r"config\BLUETOOTH_SPP_RECOVERY.md"


def _safe_text(value: Any) -> str:
    return str(value or "").strip()


def _safe_upper(value: Any) -> str:
    return _safe_text(value).upper()


def _safe_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = _safe_text(value).lower()
    if text in {"true", "1", "yes"}:
        return True
    if text in {"false", "0", "no"}:
        return False
    return bool(value)


def _safe_int(value: Any) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except Exception:
        return None


def _extract_com_name(*values: Any) -> str:
    for value in values:
        text = _safe_text(value)
        if not text:
            continue
        match = re.search(r"\b(COM\d+)\b", text, flags=re.IGNORECASE)
        if match:
            return match.group(1).upper()
    return ""


def list_live_serial_ports() -> list[dict[str, str]]:
    try:
        from serial.tools import list_ports  # type: ignore
    except Exception:
        return []

    ports: list[dict[str, str]] = []
    for port in list_ports.comports():
        device = _safe_text(getattr(port, "device", ""))
        if not device:
            continue
        ports.append(
            {
                "device": device,
                "description": _safe_text(getattr(port, "description", "")),
                "manufacturer": _safe_text(getattr(port, "manufacturer", "")),
                "hwid": _safe_text(getattr(port, "hwid", "")),
            }
        )
    ports.sort(key=lambda row: _extract_com_name(row.get("device")) or "ZZZ")
    return ports


def _is_bluetooth_live_port(port: dict[str, str]) -> bool:
    text = " ".join(
        [
            _safe_text(port.get("device")),
            _safe_text(port.get("description")),
            _safe_text(port.get("manufacturer")),
            _safe_text(port.get("hwid")),
        ]
    ).lower()
    return any(token in text for token in ("bluetooth", "rfcomm", "bthenum", "esp32spp"))


def _is_usb_live_port(port: dict[str, str]) -> bool:
    text = " ".join(
        [
            _safe_text(port.get("device")),
            _safe_text(port.get("description")),
            _safe_text(port.get("manufacturer")),
            _safe_text(port.get("hwid")),
        ]
    ).lower()
    return any(token in text for token in ("usb", "vid:pid", "ch340", "wch.cn", "1a86"))


def _normalize_pnp_entry(entry: dict[str, Any]) -> dict[str, Any]:
    friendly_name = _safe_text(entry.get("FriendlyName"))
    instance_id = _safe_text(entry.get("InstanceId"))
    return {
        "friendly_name": friendly_name,
        "instance_id": instance_id,
        "status": _safe_text(entry.get("Status")),
        "problem": _safe_int(entry.get("Problem")),
        "is_present": _safe_bool(entry.get("IsPresent")),
        "last_removal_date": _safe_text(entry.get("LastRemovalDate")),
        "bus_reported_device_desc": _safe_text(entry.get("BusReportedDeviceDesc")),
        "service_guid": _safe_text(entry.get("ServiceGuid")),
        "bluetooth_device_address": _safe_upper(entry.get("BluetoothDeviceAddress")),
        "last_connected_time": _safe_text(entry.get("LastConnectedTime")),
        "port_name": _extract_com_name(friendly_name, instance_id),
    }


def _parse_pnputil_devices(text: str) -> list[dict[str, Any]]:
    devices: list[dict[str, Any]] = []
    current: dict[str, Any] = {}
    for raw_line in str(text or "").splitlines():
        line = raw_line.rstrip()
        if not line.strip():
            if current:
                devices.append(current)
                current = {}
            continue
        if line.startswith("Microsoft PnP Utility"):
            continue
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key_norm = key.strip().lower()
        value = value.strip()
        if key_norm == "instance id":
            if current:
                devices.append(current)
                current = {}
            current["instance_id"] = value
        elif key_norm == "device description":
            current["friendly_name"] = value
        elif key_norm == "class name":
            current["class_name"] = value
        elif key_norm == "manufacturer name":
            current["manufacturer_name"] = value
        elif key_norm == "status":
            current["status"] = value
        elif key_norm == "problem code":
            match = re.search(r"(-?\d+)", value)
            current["problem"] = int(match.group(1)) if match else None
            current["problem_text"] = value
        elif key_norm == "problem status":
            current["problem_status"] = value
        elif key_norm == "driver name":
            current["driver_name"] = value
    if current:
        devices.append(current)
    return devices


def _query_windows_bt_pnp(device_name: str, device_address: str) -> dict[str, Any]:
    bluetooth = _run_command(["pnputil", "/enum-devices", "/class", "Bluetooth"], timeout_s=5.0)
    ports = _run_command(["pnputil", "/enum-devices", "/class", "Ports"], timeout_s=5.0)
    problems = _run_command(["pnputil", "/enum-devices", "/problem"], timeout_s=5.0)
    if not bluetooth.get("ok"):
        raise RuntimeError(str(bluetooth.get("stderr") or bluetooth.get("stdout") or "pnputil Bluetooth query failed"))
    if not ports.get("ok"):
        raise RuntimeError(str(ports.get("stderr") or ports.get("stdout") or "pnputil Ports query failed"))
    problem_rows = _parse_pnputil_devices(str(problems.get("stdout") or "")) if problems.get("ok") else []
    problem_map = {str(row.get("instance_id") or "").upper(): row for row in problem_rows}
    bluetooth_rows = _parse_pnputil_devices(str(bluetooth.get("stdout") or ""))
    port_rows = _parse_pnputil_devices(str(ports.get("stdout") or ""))

    def _decorate(row: dict[str, Any]) -> dict[str, Any]:
        out = _normalize_pnp_entry(
            {
                "FriendlyName": row.get("friendly_name"),
                "InstanceId": row.get("instance_id"),
                "Status": row.get("status"),
                "Problem": row.get("problem"),
                "IsPresent": str(row.get("status", "")).strip().lower() == "started",
                "LastRemovalDate": "",
                "BusReportedDeviceDesc": row.get("friendly_name"),
                "ServiceGuid": SPP_SERVICE_GUID if str(row.get("instance_id", "")).upper().startswith("BTHENUM\\{00001101-0000-1000-8000-00805F9B34FB}") else "",
                "BluetoothDeviceAddress": row.get("instance_id"),
                "LastConnectedTime": "",
            }
        )
        problem_row = problem_map.get(out["instance_id"].upper())
        if problem_row:
            out["problem"] = _safe_int(problem_row.get("problem"))
            out["status"] = _safe_text(problem_row.get("status")) or out["status"]
            out["problem_status"] = _safe_text(problem_row.get("problem_status"))
        else:
            out["problem_status"] = _safe_text(row.get("problem_status"))
        out["class_name"] = _safe_text(row.get("class_name"))
        out["manufacturer_name"] = _safe_text(row.get("manufacturer_name"))
        out["driver_name"] = _safe_text(row.get("driver_name"))
        return out

    rfcomm_devices = [_decorate(row) for row in bluetooth_rows if _safe_text(row.get("instance_id")).upper().startswith("BTH\\MS_RFCOMM\\")]
    bt_devices = [
        _decorate(row)
        for row in bluetooth_rows
        if _safe_text(row.get("friendly_name")) == device_name
        or f"DEV_{device_address}" in _safe_text(row.get("instance_id")).upper()
    ]
    spp_ports = [
        _decorate(row)
        for row in port_rows
        if _safe_text(row.get("instance_id")).upper().startswith(f"BTHENUM\\{SPP_SERVICE_GUID.upper()}")
        or "BLUETOOTH" in _safe_text(row.get("friendly_name")).upper()
    ]
    return {
        "rfcomm": rfcomm_devices,
        "bt_devices": bt_devices,
        "spp_ports": spp_ports,
    }


def collect_windows_bt_spp_diagnostics(
    preferred_port: Optional[str] = None,
    *,
    device_name: str = BTWRITER_NAME,
    device_address: str = BTWRITER_ADDRESS,
) -> dict[str, Any]:
    preferred = _safe_upper(preferred_port)
    live_ports = list_live_serial_ports()
    live_bt_ports = [row["device"] for row in live_ports if _is_bluetooth_live_port(row)]
    live_usb_ports = [row["device"] for row in live_ports if _is_usb_live_port(row)]

    state: dict[str, Any] = {
        "platform": sys.platform,
        "preferred_port": preferred,
        "device_name": device_name,
        "device_address": _safe_upper(device_address),
        "live_serial_ports": live_ports,
        "live_serial_devices": [row["device"] for row in live_ports],
        "live_bt_ports": live_bt_ports,
        "live_usb_ports": live_usb_ports,
        "recommended_port": live_bt_ports[0] if live_bt_ports else (live_usb_ports[0] if live_usb_ports else (live_ports[0]["device"] if live_ports else "")),
        "rfcomm_devices": [],
        "bt_devices": [],
        "spp_ports": [],
        "ghost_spp_ports": [],
        "preferred_port_live": preferred in {row["device"].upper() for row in live_ports},
        "preferred_port_is_ghost": False,
        "preferred_port_is_bt_spp": False,
        "btwriter_paired": False,
        "rfcomm_failed_start": False,
        "rfcomm_problem_code": None,
        "rfcomm_problem_status": "",
        "summary": "",
        "recovery_steps": [],
        "collection_error": "",
    }

    if not sys.platform.startswith("win"):
        state["summary"] = "Windows Bluetooth SPP diagnostics are only available on Windows."
        return state

    try:
        raw = _query_windows_bt_pnp(device_name=device_name, device_address=device_address)
        rfcomm_devices = list(raw.get("rfcomm") or [])
        bt_devices = list(raw.get("bt_devices") or [])
        spp_ports = list(raw.get("spp_ports") or [])
        state["rfcomm_devices"] = rfcomm_devices
        state["bt_devices"] = bt_devices
        state["spp_ports"] = spp_ports
        state["ghost_spp_ports"] = [row["port_name"] for row in spp_ports if row["port_name"] and not row["is_present"]]
        state["btwriter_paired"] = bool(bt_devices)

        for row in rfcomm_devices:
            problem = row.get("problem")
            if problem not in (None, 0):
                state["rfcomm_failed_start"] = True
                state["rfcomm_problem_code"] = problem
                state["rfcomm_problem_status"] = row.get("problem_status", "") or row.get("status", "")
                break

        if not state["rfcomm_failed_start"]:
            for row in rfcomm_devices:
                status = _safe_text(row.get("status")).lower()
                if status and status not in {"ok", "started"}:
                    state["rfcomm_failed_start"] = True
                    state["rfcomm_problem_code"] = row.get("problem")
                    state["rfcomm_problem_status"] = row.get("status", "")
                    break

        if preferred:
            state["preferred_port_is_ghost"] = preferred in {row["port_name"].upper() for row in spp_ports if row["port_name"] and not row["is_present"]}
            state["preferred_port_is_bt_spp"] = preferred in {row["port_name"].upper() for row in spp_ports if row["port_name"]}
    except Exception as exc:
        state["collection_error"] = f"{type(exc).__name__}: {exc}"

    state["summary"] = summarize_windows_bt_spp_issue(state)
    state["recovery_steps"] = build_recovery_steps(state)
    return state


def summarize_windows_bt_spp_issue(state: dict[str, Any]) -> str:
    preferred = _safe_upper(state.get("preferred_port"))
    recommended = _safe_text(state.get("recommended_port"))
    ghost_ports = [port for port in list(state.get("ghost_spp_ports") or []) if port]
    code = state.get("rfcomm_problem_code")

    if state.get("preferred_port_live"):
        return f"Preferred port {preferred} is live."
    if state.get("live_bt_ports"):
        ports = ", ".join(list(state.get("live_bt_ports") or []))
        return f"Bluetooth SPP is live on {ports}."
    if state.get("rfcomm_failed_start"):
        parts = ["Windows Bluetooth RFCOMM failed to start"]
        if code not in (None, ""):
            parts[-1] += f" (Code {code})"
        if state.get("btwriter_paired"):
            parts.append("paired device BtWriter is still present")
        if ghost_ports:
            parts.append(f"ghost SPP port(s): {', '.join(ghost_ports)}")
        if recommended:
            parts.append(f"working fallback port: {recommended}")
        return "; ".join(parts) + "."
    if state.get("btwriter_paired") and ghost_ports:
        parts = ["BtWriter is paired, but its SPP COM mapping is stale"]
        parts.append(f"ghost SPP port(s): {', '.join(ghost_ports)}")
        if recommended:
            parts.append(f"working fallback port: {recommended}")
        return "; ".join(parts) + "."
    if state.get("btwriter_paired"):
        return "BtWriter is paired, but no live Bluetooth SPP COM port is present."
    if state.get("collection_error"):
        return f"Bluetooth SPP diagnostics failed: {_safe_text(state.get('collection_error'))}"
    if recommended:
        return f"No live Bluetooth SPP COM ports detected. Working fallback port: {recommended}."
    return "No live Bluetooth SPP COM ports detected."


def build_recovery_steps(state: dict[str, Any]) -> list[str]:
    steps: list[str] = []
    recommended = _safe_text(state.get("recommended_port"))
    preferred = _safe_upper(state.get("preferred_port"))
    report_cmd = RECOVERY_SCRIPT if not preferred else f"{RECOVERY_SCRIPT} --preferred-port {preferred}"
    if recommended:
        steps.append(f"If you need to draw right now, use {recommended}.")
    steps.append(f"Run {report_cmd} for a detailed report.")
    if state.get("rfcomm_failed_start"):
        steps.append("If the report still shows RFCOMM Code 10, run the same script from an elevated terminal with --attempt-soft-repair.")
    steps.append("If ghost COM ports remain, delete the stale Bluetooth Serial Port entries and recreate the outgoing SPP port for BtWriter / ESP32SPP.")
    steps.append(f"Detailed manual recovery steps are in {RECOVERY_DOC}.")
    return steps


def build_serial_open_hint(port: str, diagnostics: Optional[dict[str, Any]] = None) -> str:
    state = diagnostics or collect_windows_bt_spp_diagnostics(preferred_port=port)
    if not sys.platform.startswith("win"):
        return ""
    preferred = _safe_upper(port or state.get("preferred_port"))
    report_cmd = RECOVERY_SCRIPT if not preferred else f"{RECOVERY_SCRIPT} --preferred-port {preferred}"
    if state.get("preferred_port_live"):
        return ""

    summary = _safe_text(state.get("summary"))
    if not summary:
        return ""

    if not preferred:
        preferred = "selected COM port"
    hint = f"Bluetooth SPP hint: {preferred} is not a live serial port. {summary}"
    recommended = _safe_text(state.get("recommended_port"))
    if recommended:
        hint += f" Use {recommended} now or run {report_cmd}."
    else:
        hint += f" Run {report_cmd}."
    hint += f" See {RECOVERY_DOC}."
    return hint


def is_windows_admin() -> bool:
    if not sys.platform.startswith("win"):
        return False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _run_command(args: list[str], *, timeout_s: float = 20.0) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            args,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=max(1.0, float(timeout_s)),
            check=False,
        )
        return {
            "command": args,
            "ok": completed.returncode == 0,
            "returncode": int(completed.returncode),
            "stdout": _safe_text(completed.stdout),
            "stderr": _safe_text(completed.stderr),
        }
    except Exception as exc:
        return {
            "command": args,
            "ok": False,
            "returncode": -1,
            "stdout": "",
            "stderr": f"{type(exc).__name__}: {exc}",
        }


def attempt_soft_repair(
    preferred_port: Optional[str] = None,
    *,
    device_name: str = BTWRITER_NAME,
    device_address: str = BTWRITER_ADDRESS,
) -> dict[str, Any]:
    before = collect_windows_bt_spp_diagnostics(
        preferred_port=preferred_port,
        device_name=device_name,
        device_address=device_address,
    )
    result: dict[str, Any] = {
        "admin": is_windows_admin(),
        "before": before,
        "actions": [],
    }

    result["actions"].append(_run_command(["pnputil", "/scan-devices"]))

    if result["admin"]:
        for row in list(before.get("rfcomm_devices") or []):
            instance_id = _safe_text(row.get("instance_id"))
            if instance_id:
                result["actions"].append(_run_command(["pnputil", "/restart-device", instance_id]))
                if _safe_int(row.get("problem")) not in (None, 0):
                    result["actions"].append(_run_command(["pnputil", "/remove-device", instance_id, "/subtree"]))
        for row in list(before.get("bt_devices") or []):
            instance_id = _safe_text(row.get("instance_id"))
            if instance_id:
                result["actions"].append(_run_command(["pnputil", "/restart-device", instance_id]))
        for port in list(before.get("spp_ports") or []):
            if port.get("is_present"):
                continue
            instance_id = _safe_text(port.get("instance_id"))
            if not instance_id:
                continue
            result["actions"].append(_run_command(["pnputil", "/remove-device", instance_id]))
        ps = (
            "$ErrorActionPreference='Stop'; "
            "Get-Service | Where-Object { $_.Name -eq 'bthserv' -or $_.Name -like 'BluetoothUserService*' } "
            "| Restart-Service -Force"
        )
        result["actions"].append(_run_command(["powershell", "-NoProfile", "-Command", ps]))
        result["actions"].append(_run_command(["pnputil", "/scan-devices"]))
    else:
        result["actions"].append(
            {
                "command": ["admin-required"],
                "ok": False,
                "returncode": -1,
                "stdout": "",
                "stderr": "Soft repair needs an elevated terminal to remove ghost COM ports and restart Bluetooth services.",
            }
        )

    result["after"] = collect_windows_bt_spp_diagnostics(
        preferred_port=preferred_port,
        device_name=device_name,
        device_address=device_address,
    )
    return result

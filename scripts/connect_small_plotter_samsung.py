"""Provision only the small BtWriter for the existing Samsung TV 24 WLAN."""

from __future__ import annotations

import getpass
import ipaddress
import re
import sys
import time
import urllib.error
import urllib.request
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.plotter_backend.machine.grbl_probe import open_serial_no_reset

SSID = "Samsung TV 24"
PORT = "COM6"
NETWORK = ipaddress.IPv4Network("192.168.2.0/24")
CONTROLLER_IDS = ("BtWriter(A4:F0:0F:75:C5:0E)", "MAC=A4-F0-0F-75-C5-0C")


def command(ser, payload: str, *, sensitive: bool = False, timeout: float = 3) -> list[str]:
    label = payload.partition("=")[0]
    ser.write((payload if payload == "?" else payload + "\r").encode("ascii"))
    ser.flush()
    deadline = time.monotonic() + timeout
    rows = []
    while time.monotonic() < deadline:
        row = ser.readline().decode("ascii", errors="replace").strip()
        if row.startswith(("error:", "ALARM:")):
            raise RuntimeError(f"{label} was rejected by the controller.")
        if row and not sensitive:
            rows.append(row)
        if row == "ok" or (payload == "?" and row.startswith("<")):
            return rows
    raise TimeoutError(f"No reply for {label}.")


def address(ser) -> ipaddress.IPv4Address | None:
    for row in command(ser, "$System/IP", timeout=4):
        try:
            ip = ipaddress.IPv4Address(row)
        except ipaddress.AddressValueError:
            continue
        if ip in NETWORK and ip not in (NETWORK.network_address, NETWORK.broadcast_address):
            return ip
    return None


def main() -> int:
    print(f"Target: small BtWriter on {PORT}, existing Wi-Fi {SSID!r}.")
    print("No router, PC Wi-Fi, VPN, drawing settings, or motor changes.")
    with warnings.catch_warnings():
        warnings.simplefilter("error", getpass.GetPassWarning)
        password = getpass.getpass("Existing Wi-Fi password (hidden): ")
    if (
        not re.fullmatch(r"[ -~]{8,63}", password)
        or password.strip() != password
        or any(c in password for c in "!?~")
    ):
        print("This password cannot be sent safely over this serial protocol; no changes made.")
        return 1
    with open_serial_no_reset(PORT, 115200, timeout_s=0.2) as ser:
        identity = command(ser, "$I")
        if not any(marker in line for marker in CONTROLLER_IDS for line in identity):
            raise RuntimeError("COM6 is not the expected BtWriter controller.")
        if not command(ser, "?")[-1].startswith("<Idle|"):
            raise RuntimeError("Plotter is not idle; no changes made.")
        if sorted(command(ser, "$N")) != ["$N0=", "$N1=", "ok"]:
            raise RuntimeError("Unexpected startup commands; reboot not safe.")
        old_mode = command(ser, "$Radio/Mode")[0].split("=", 1)[1]
        command(ser, "$Sta/IPMode=DHCP")
        command(ser, "$Sta/SSID=" + SSID)
        command(ser, "$Sta/Password=" + password, sensitive=True)
        del password
        command(ser, "$Radio/Mode=STA")
        command(ser, "$System/Control=RESTART")

    print("Waiting for the plotter's DHCP address...", flush=True)
    time.sleep(5)
    ip = None
    with open_serial_no_reset(PORT, 115200, timeout_s=0.25) as ser:
        deadline = time.monotonic() + 40
        while time.monotonic() < deadline:
            try:
                ip = address(ser)
            except TimeoutError:
                pass
            if ip:
                break
            time.sleep(1)
        if ip is None:
            print("No IP received in the Samsung network.")
            if old_mode == "BT":
                command(ser, "$Radio/Mode=BT")
                command(ser, "$System/Control=RESTART")
                print("Bluetooth mode restored.")
            return 1
        identity = command(ser, "$I")
        if not any("Mode=STA:" in line and SSID in line and str(ip) in line for line in identity):
            raise RuntimeError("The controller did not confirm the expected Wi-Fi network.")
    url = f"http://{ip}/"
    print(f"Plotter joined {SSID}: {url}")
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(url, timeout=5) as response:
            print(f"Web interface responded: HTTP {response.status}")
    except (urllib.error.URLError, TimeoutError) as exc:
        print(f"Wi-Fi is connected, but the web interface did not respond from this PC: {exc}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (getpass.GetPassWarning, KeyboardInterrupt, RuntimeError, OSError) as exc:
        print(f"Stopped: {exc or 'cancelled'}", file=sys.stderr)
        raise SystemExit(1)

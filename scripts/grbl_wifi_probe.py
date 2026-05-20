from __future__ import annotations

import argparse
import ipaddress
import json
import socket
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.plotter_backend.machine.grbl_transport import parse_tcp_endpoint


COMMON_GRBL_TCP_PORTS = (23, 8080, 2323, 8888)


def _probe_one(host: str, port: int, *, timeout_s: float) -> dict:
    result = {
        "host": host,
        "port": int(port),
        "open": False,
        "grbl_like": False,
        "banner": "",
        "status": "",
        "error": "",
    }
    try:
        with socket.create_connection((host, int(port)), timeout=max(0.05, timeout_s)) as sock:
            sock.settimeout(max(0.05, timeout_s))
            result["open"] = True
            try:
                sock.sendall(b"\r\n")
                time.sleep(0.10)
                try:
                    banner = sock.recv(1024)
                except socket.timeout:
                    banner = b""
                sock.sendall(b"?")
                time.sleep(0.12)
                try:
                    status = sock.recv(1024)
                except socket.timeout:
                    status = b""
                result["banner"] = banner.decode("ascii", errors="replace").strip()
                result["status"] = status.decode("ascii", errors="replace").strip()
                joined = (str(result["banner"]) + "\n" + str(result["status"])).lower()
                result["grbl_like"] = "grbl" in joined or "<idle|" in joined or "<run|" in joined or "<sleep|" in joined
            except Exception as exc:
                result["error"] = f"{type(exc).__name__}: {exc}"
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    return result


def _hosts_from_subnet(subnet: str) -> list[str]:
    net = ipaddress.ip_network(subnet, strict=False)
    return [str(ip) for ip in net.hosts()]


def probe_targets(targets: list[str], ports: list[int], *, timeout_s: float, workers: int) -> list[dict]:
    jobs: list[tuple[str, int]] = []
    for target in targets:
        endpoint = parse_tcp_endpoint(target)
        if endpoint is not None:
            jobs.append((endpoint.host, endpoint.port))
        else:
            for port in ports:
                jobs.append((target, int(port)))
    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=max(1, int(workers))) as pool:
        future_map = {pool.submit(_probe_one, host, port, timeout_s=timeout_s): (host, port) for host, port in jobs}
        for fut in as_completed(future_map):
            results.append(fut.result())
    results.sort(key=lambda row: (not bool(row.get("grbl_like")), not bool(row.get("open")), str(row.get("host")), int(row.get("port"))))
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Probe GRBL-over-Wi-Fi TCP endpoints.")
    parser.add_argument("targets", nargs="*", help="Host/IP, tcp://host:port, or subnet with --subnet.")
    parser.add_argument("--subnet", default="", help="CIDR subnet to scan, e.g. 192.168.1.0/24.")
    parser.add_argument("--ports", default="23,8080,2323,8888", help="Comma-separated TCP ports to probe.")
    parser.add_argument("--timeout", type=float, default=0.35, help="Per-connect timeout in seconds.")
    parser.add_argument("--workers", type=int, default=64, help="Parallel probe workers.")
    parser.add_argument("--json", action="store_true", help="Print full JSON results.")
    parser.add_argument("--all", action="store_true", help="With --json, include closed/blocked endpoints too.")
    args = parser.parse_args(argv)

    ports = [int(p.strip()) for p in str(args.ports).split(",") if p.strip()]
    targets = list(args.targets or [])
    if args.subnet:
        targets.extend(_hosts_from_subnet(args.subnet))
    if not targets:
        parser.error("provide at least one target or --subnet")

    results = probe_targets(targets, ports, timeout_s=float(args.timeout), workers=int(args.workers))
    visible = results if args.all else [row for row in results if row.get("open") or row.get("grbl_like")]
    if args.json:
        print(json.dumps(visible, ensure_ascii=False, indent=2))
    else:
        for row in visible:
            marker = "GRBL" if row["grbl_like"] else "open"
            print(f"{marker}: tcp://{row['host']}:{row['port']}")
            if row["banner"]:
                print(f"  banner: {row['banner']}")
            if row["status"]:
                print(f"  status: {row['status']}")
        if not visible:
            blocked = sum(1 for row in results if "WinError 10013" in str(row.get("error") or ""))
            if blocked:
                print(f"No GRBL TCP endpoint found. Windows blocked {blocked} socket probe(s) with WinError 10013.")
            else:
                print("No GRBL TCP endpoint found.")
    return 0 if any(row.get("grbl_like") for row in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())

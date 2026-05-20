# Wi-Fi GRBL Connection

The project can now stream G-code to GRBL over TCP, so drawing no longer has to depend on USB `COM6` or Bluetooth `COM11` once the controller exposes a Wi-Fi socket.

## Endpoint format

Use one of these forms anywhere the CLI expects `--com`:

```powershell
--com tcp://192.168.1.50:23
--com 192.168.1.50:23
```

Port `23` is the default for many ESP32/ESP8266 serial bridges. Other common ports are `8080`, `2323`, and `8888`.

## Find the plotter on the LAN

Probe a known host:

```powershell
python scripts\grbl_wifi_probe.py tcp://192.168.1.50:23
```

Scan the current home subnet:

```powershell
python scripts\grbl_wifi_probe.py --subnet 192.168.1.0/24 --ports 23,8080,2323,8888
```

A real GRBL endpoint should print `GRBL:` and show either a `Grbl ...` banner or a status line such as `<Idle|...>`.

## Send a prepared drawing by Wi-Fi

```powershell
python src\send_grbl_file.py tcp://192.168.1.50:23 115200 "D:\plotter_pdf\Компьютерная графика\22 вариант\КНГ.01.20.01 - Маховик_pack\page_01.nc"
```

The baud argument is ignored by TCP, but keep `115200` for CLI compatibility.

## Current machine note

On 2026-05-20 the PC was on `192.168.1.145/24`. A quick probe did not find a GRBL-like endpoint on the LAN. `192.168.4.1` accepted TCP connections on common ports but returned no GRBL banner/status, so it is not confirmed as the plotter.

To finish the wireless cutover, the controller must be configured to join the same network or expose its own Wi-Fi AP with a reachable GRBL TCP socket. After that, save the confirmed endpoint in local operator notes and use it as `--com tcp://host:port`.

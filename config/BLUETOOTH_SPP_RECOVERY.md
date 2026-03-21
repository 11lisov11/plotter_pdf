# Bluetooth SPP Recovery (`BtWriter` / `ESP32SPP`)

This project talks to the plotter over either:

- Bluetooth Classic SPP (`ESP32SPP`, usually `COM11`)
- USB serial (`CH340`, usually `COM6`)

The recent failure mode on this machine is not "Bluetooth is gone". The failing layer is Windows `RFCOMM`, so the paired device still exists but the SPP COM port becomes a stale ghost port.

## Typical symptoms

- `COM11` exists in old settings but does not open.
- `python scripts\bt_spp_recovery.py --preferred-port COM11` reports:
  - `Windows Bluetooth RFCOMM failed to start (Code 10)`
  - `ghost SPP port(s): COM11` or `COM12`
- `BtWriter` is still paired.
- USB still works on `COM6`.

## What the project now does

- Serial-open errors append a Bluetooth-specific hint instead of only `Cannot open COM11`.
- The project no longer treats a non-live Bluetooth SPP port as healthy.
- Fast diagnostics are available through:

```powershell
python scripts\bt_spp_recovery.py --preferred-port COM11
```

## Fastest recovery path

If you need to keep drawing right now, switch to USB `COM6`.

To restore Bluetooth SPP correctly:

1. Run the report script first:

```powershell
python scripts\bt_spp_recovery.py --preferred-port COM11
```

2. If the report shows `RFCOMM Code 10`, open an elevated terminal and try the soft repair:

```powershell
python scripts\bt_spp_recovery.py --preferred-port COM11 --attempt-soft-repair
```

3. If ghost ports still remain, remove stale Bluetooth serial mappings in Device Manager:
   - `Bluetooth Device (RFCOMM Protocol TDI)` if it has an error
   - `Standard Serial over Bluetooth link (COM11)`
   - any bogus ghost port such as `COM12`

4. Recreate the outgoing SPP port for `BtWriter` / `ESP32SPP`:
   - `Settings -> Bluetooth & devices -> Devices -> More Bluetooth settings -> COM Ports -> Add`
   - choose `Outgoing`
   - select `BtWriter`

5. Re-run the report script and verify that:
   - `Live Bluetooth SPP ports` includes the recreated COM port
   - `Ghost SPP ports` is empty or only contains old removed mappings

## Why the port "disappeared"

Windows can remove the SPP COM mapping when the `RFCOMM` transport fails to start. In that state:

- the paired Bluetooth device can still be present;
- the old `COM11` entry can remain in settings/logs;
- the actual serial endpoint no longer exists.

That is a Windows Bluetooth stack problem, not a plotter-geometry problem.

## Recommended operating rule

- Use Bluetooth SPP when the report shows a live Bluetooth COM port.
- Use USB `COM6` for long drawing sessions or whenever SPP is unstable.
- If `COM11` stops opening, do not keep retrying blindly; run the report script and follow the steps above.

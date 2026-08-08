# A2 CoreXY operation

## Confirmed coordinate system

- Machine profile: `a2_corexy`.
- Origin: left-lower corner of the confirmed drawable area.
- `X+` moves right.
- `Y+` moves up.
- Confirmed drawable area: `390x580 mm`.
- Physical A2 sheet: `420x594 mm`.

The software preserves drawing scale. It does not stretch the `390x580 mm`
machine area to the full `420x594 mm` paper. The inactive outer paper bands are
shown in preview and clipped from final G-code.

## Full-size layouts

| Layout | Grid | Sheets | Unique calibration points |
|---|---:|---:|---:|
| `a2` | `1x1` | one A2 | 4 |
| `a2_2xa3` | `1x2` | two A3 | 6 |
| `a2_4xa4` | `2x2` | four A4 | 9 |

Shared corners are drawn once and serve both neighbouring sheets. Eight
full-size A4 sheets do not fit on one A2 field.

## Calibration commands

```powershell
python main.py --calibrate-corners --machine-profile a2_corexy --sheet-format a2 --calibration-layout a2
python main.py --calibrate-corners --machine-profile a2_corexy --sheet-format a2 --calibration-layout a2_2xa3
python main.py --calibrate-corners --machine-profile a2_corexy --sheet-format a2 --calibration-layout a2_4xa4
```

Place the carriage at the left-lower work-area corner before establishing
`G92 X0 Y0`. Do not reuse the A4 desktop profile for this machine.

## Production acceptance

Before a new A2 drawing is sent to hardware:

1. Render preview from the final G-code.
2. Confirm orientation and readable text.
3. Confirm bounds are inside `X 0..390`, `Y 0..580`.
4. Confirm scale-sensitive geometry remains `1:1`.
5. Run corner calibration for the selected layout.
6. Keep physical emergency power removal within reach.
7. Release motors after the job.

; STITCH-ONLY: send_small_sheet_tiles.py; keep this session open between passes
; No XY zero reset, no reflection, no automatic continuation
G21
G90
G94
G17
G0 Z0.0000 F2500.0
G4 P0.06
G0 Z0.0000 F2500.0
G0 X12.000 Y-7.500 F15000.0
G4 P0.05
; STOP: pen up, motors remain held; do not re-zero or move the carriage by hand

$X
$1=255
G21
G90
G17
G91.1

; Safety: pen up before any XY move
G0 Z0.0000 F800
G4 P0.03
G92 Z0.0000

; Go home (origin is bottom-left of the work area)
G0 X0.0000 Y0.0000 F15000

; Circle center in 180x280 work area: (90, -140), radius=50 => d=100
G0 X140.0000 Y-140.0000 F15000
G0 Z11.9000
G4 P0.03

; Draw full circle as two 180deg CCW arcs (GRBL-safe)
G3 X40.0000 Y-140.0000 I-50.0000 J0.0000 F12000
G3 X140.0000 Y-140.0000 I50.0000 J0.0000

; End: pen up + release motors
G0 Z0.0000 F800
G4 P0.03
M5
G4 P0.10
$1=0

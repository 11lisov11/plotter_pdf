# Troubleshooting

- No COM port: reconnect USB/Bluetooth SPP and close other serial programs.
- Missing PySide6: `pip install -e .[gui]`.
- Missing OpenCV/photo tools: `pip install -e .[photo]`.
- Word/KOMPAS conversion needs Windows plus installed applications; core PDF/SVG preview still works without them.
- If draw fails, use safe release/emergency stop and inspect the generated report JSON.

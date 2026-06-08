$ErrorActionPreference = "Stop"
python -m pip install --upgrade pip
pip install -r requirements-build.txt
python scripts/build_windows_release.py

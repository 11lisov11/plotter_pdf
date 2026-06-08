# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_submodules

block_cipher = None
hiddenimports = collect_submodules('src') + collect_submodules('plotter_app') + collect_submodules('plotter_studio')

a = Analysis(['plotter_app/app_entry.py'], pathex=['.'], binaries=[], datas=[('config/axis_profile.json', 'config'), ('config/gui_settings.default.json', 'config')], hiddenimports=hiddenimports, hookspath=[], hooksconfig={}, runtime_hooks=[], excludes=[], noarchive=False)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
exe = EXE(pyz, a.scripts, a.binaries, a.zipfiles, a.datas, [], name='PlotterPDF_GUI', debug=False, bootloader_ignore_signals=False, strip=False, upx=True, upx_exclude=[], runtime_tmpdir=None, console=False)

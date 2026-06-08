# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_submodules

block_cipher = None
hiddenimports = collect_submodules('src') + collect_submodules('plotter_studio')

a = Analysis(['src/cli_main.py'], pathex=['.'], binaries=[], datas=[('config/axis_profile.json', 'config')], hiddenimports=hiddenimports, hookspath=[], hooksconfig={}, runtime_hooks=[], excludes=[], noarchive=False)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='plotter-pdf', debug=False, bootloader_ignore_signals=False, strip=False, upx=True, console=True)
selfcheck = EXE(pyz, [('self_check_cli', 'src/plotter_backend/jobs/self_check_cli.py', 'PYSOURCE')], [], exclude_binaries=True, name='plotter-pdf-self-check', debug=False, bootloader_ignore_signals=False, strip=False, upx=True, console=True)
coll = COLLECT(exe, selfcheck, a.binaries, a.zipfiles, a.datas, strip=False, upx=True, upx_exclude=[], name='PlotterPDF')

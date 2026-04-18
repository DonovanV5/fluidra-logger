# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['Fluidra_Manufacturing_Solutionv7.4.py'],
    pathex=[],
    binaries=[],
    datas=[('pumpline-logger.json', '.'), ('config', 'config')],
    hiddenimports=['openpyxl', 'gspread', 'oauth2client', 'win32print', 'win32ui', 'terioka_client', 'PIL._tkinter_finder'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='Fluidra_Manufacturing_Solution',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='NONE',
)

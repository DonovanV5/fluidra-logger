# -*- mode: python ; coding: utf-8 -*-

import os
import sys
from pathlib import Path

block_cipher = None

# Get the absolute path to the script
script_path = os.path.abspath('Fluidra_Manufacturing_Solutionv7.1.py')

# Collect data files
datas = []

# Add zpl_presets directory
zpl_presets_path = os.path.join(os.path.dirname(script_path), 'zpl_presets')
if os.path.exists(zpl_presets_path):
    for root, dirs, files in os.walk(zpl_presets_path):
        for file in files:
            src_path = os.path.join(root, file)
            rel_path = os.path.relpath(root, os.path.dirname(script_path))
            dest_path = os.path.join('zpl_presets', os.path.relpath(root, zpl_presets_path))
            datas.append((src_path, dest_path))

# Add config directory
config_path = os.path.join(os.path.dirname(script_path), 'config')
if os.path.exists(config_path):
    for root, dirs, files in os.walk(config_path):
        for file in files:
            src_path = os.path.join(root, file)
            rel_path = os.path.relpath(root, os.path.dirname(script_path))
            dest_path = os.path.join('config', os.path.relpath(root, config_path))
            datas.append((src_path, dest_path))

# Add any additional data files
additional_files = [
    'barcode_log.xlsx',
    'pumpline-logger.json',
    'config.json',
    'logo.png',
    'screenshot.png'
]

for file in additional_files:
    file_path = os.path.join(os.path.dirname(script_path), file)
    if os.path.exists(file_path):
        datas.append((file_path, '.'))

a = Analysis(
    [script_path],
    pathex=[os.path.dirname(script_path)],
    binaries=[],
    datas=datas,
    hiddenimports=[
        'pandas', 'numpy', 'openpyxl', 'requests', 'zeep', 'PIL', 'PIL._tkinter_finder',
        'tkinter', 'tkinter.filedialog', 'tkinter.messagebox', 'tkinter.ttk', 'tkinter.scrolledtext'
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='Fluidra_Manufacturing_Solution_v7.1',
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
)

# -*- mode: python ; coding: utf-8 -*-
import glob
import os

DPF_DLLS = glob.glob(os.path.join('sdk', 'vendor', 'dpf', '*.dll'))

# El updater interno se empaqueta como data (si ya fue compilado) para que la
# app pueda auto-actualizarse. Build: primero el updater, luego la app.
DATAS = [('assets', 'assets'), ('.env.example', '.'), ('version.txt', '.')]
if os.path.exists(os.path.join('dist', 'WTSControlUpdater.exe')):
    DATAS.append((os.path.join('dist', 'WTSControlUpdater.exe'), 'updater'))

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[(d, '.') for d in DPF_DLLS],
    datas=DATAS,
    hiddenimports=[],
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
    [],
    exclude_binaries=True,
    name='WTSControl',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['assets/logo.ico'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='WTSControl',
)

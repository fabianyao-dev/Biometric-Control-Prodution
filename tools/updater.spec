# -*- mode: python ; coding: utf-8 -*-
# Build del updater interno de WTSControl: ONE-file (un solo .exe, solo
# stdlib) que se empaqueta como data de la app (WTSControl.spec) y se copia
# a la carpeta de datos al aplicar una actualizacion.
# Se ejecuta desde la RAIZ del proyecto (igual que WTSControl.spec).

a = Analysis(
    ['updater.py'],
    pathex=['.'],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['PySide6', 'pymodbus', 'dotenv'],
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
    name='WTSControlUpdater',
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
)
# -*- mode: python ; coding: utf-8 -*-
import glob
import os

DPF_DLLS = glob.glob(os.path.join('sdk', 'vendor', 'dpf', '*.dll'))

# El updater interno se empaqueta como data (si ya fue compilado) para que la
# app pueda auto-actualizarse. Build: primero el updater, luego la app.
DATAS = [('assets', 'assets'), ('.env.example', '.'), ('version.txt', '.')]
if os.path.exists(os.path.join('dist', 'WTSControlUpdater.exe')):
    DATAS.append((os.path.join('dist', 'WTSControlUpdater.exe'), 'updater'))

# Los modulos se descubren en caliente con importlib (sin __init__.py), asi
# que PyInstaller no puede verlos por analisis estatico. Se agregan como
# hiddenimports y se copia el archivo de vista como data para que
# `os.listdir` lo encuentre en tiempo de ejecucion.
MODULOS_DIR = os.path.join('src', 'gui', 'modulos')
HIDDENIMPORTS = []
if os.path.isdir(MODULOS_DIR):
    for _nombre in sorted(os.listdir(MODULOS_DIR)):
        _ruta = os.path.join(MODULOS_DIR, _nombre)
        if _nombre.startswith('_') or not os.path.isdir(_ruta):
            continue
        for _candidato in ('inicio_view', 'view'):
            _vista = os.path.join(_ruta, _candidato + '.py')
            if os.path.isfile(_vista):
                HIDDENIMPORTS.append(
                    'src.gui.modulos.%s.%s' % (_nombre, _candidato)
                )
                DATAS.append((
                    _vista,
                    os.path.join('src', 'gui', 'modulos', _nombre),
                ))
                break

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[(d, '.') for d in DPF_DLLS],
    datas=DATAS,
    hiddenimports=HIDDENIMPORTS,
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

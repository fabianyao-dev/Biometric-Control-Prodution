#!/usr/bin/env python
"""
hacer_manifest.py - Genera manifest.json + WTSControl-<version>.zip tras el
build onedir de PyInstaller.

El manifest es lo que las PCs consultan (via servidor HTTP) para saber si
hay una version nueva y verificar la integridad del paquete (sha256).

Uso (orden de build completo):
    venv\\Scripts\\pyinstaller --noconfirm tools\\updater.spec
    venv\\Scripts\\pyinstaller --noconfirm WTSControl.spec
    venv\\Scripts\\python tools\\hacer_manifest.py 1.1.0 [--build dist\\WTSControl] [--salida dist]

Luego copia `manifest.json` y `WTSControl-<version>.zip` a la carpeta que
sirve `tools\\servidor_actualizaciones.py` (carpeta `release/` por defecto).
"""

import argparse
import hashlib
import json
import os
import sys
import zipfile
from datetime import datetime
from zoneinfo import ZoneInfo

ZONA = ZoneInfo("America/Monterrey")


def sha256_de_archivo(ruta):
    h = hashlib.sha256()
    with open(ruta, "rb") as f:
        while True:
            bloque = f.read(1024 * 1024)
            if not bloque:
                break
            h.update(bloque)
    return h.hexdigest()


def main():
    parser = argparse.ArgumentParser(description="Genera manifest + zip de release.")
    parser.add_argument("version", help="Version nueva (ej. 1.1.0)")
    parser.add_argument(
        "--build", default=os.path.join("dist", "WTSControl"),
        help="Carpeta del build onedir (default: dist/WTSControl)",
    )
    parser.add_argument(
        "--salida", default="dist",
        help="Carpeta de salida (default: dist)",
    )
    args = parser.parse_args()

    build = os.path.abspath(args.build)
    salida = os.path.abspath(args.salida)
    version = args.version.strip()

    if not os.path.isdir(build):
        print(f"ERROR: no existe el build '{build}'")
        sys.exit(1)
    if not os.path.exists(os.path.join(build, "WTSControl.exe")):
        print(f"ERROR: '{build}' no parece un build onedir (falta WTSControl.exe)")
        sys.exit(1)

    archivos = {}
    for raiz, dirs, nombres in os.walk(build):
        dirs.sort()
        for nombre in sorted(nombres):
            ruta = os.path.join(raiz, nombre)
            rel = os.path.relpath(ruta, build).replace("\\", "/")
            archivos[rel] = {
                "sha256": sha256_de_archivo(ruta),
                "size": os.path.getsize(ruta),
            }

    zip_nombre = f"WTSControl-{version}.zip"
    zip_ruta = os.path.join(salida, zip_nombre)
    with zipfile.ZipFile(zip_ruta, "w", zipfile.ZIP_DEFLATED) as z:
        for rel in archivos:
            z.write(os.path.join(build, rel), rel)

    manifest = {
        "version": version,
        "published_at": datetime.now(ZONA).strftime("%Y-%m-%d %H:%M:%S"),
        "zip": {
            "archivo": zip_nombre,
            "sha256": sha256_de_archivo(zip_ruta),
        },
        "files": archivos,
    }
    man_ruta = os.path.join(salida, "manifest.json")
    with open(man_ruta, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    print(f"manifest.json  -> {man_ruta}")
    print(f"{zip_nombre} -> {zip_ruta}")
    print(f"({len(archivos)} archivos)")
    print()
    print("Copia ambos a la carpeta servida por servidor_actualizaciones.py "
          "(carpeta 'release/' por defecto).")


if __name__ == "__main__":
    main()
#!/usr/bin/env python
"""
hacer_manifest.py - Genera manifest.json + WTSControl-<version>.zip y
actualiza el catalogo releases.json tras el build onedir de PyInstaller.

El manifest describe UNA version (version, fecha, notas, sha256 del zip y de
cada archivo). El catalogo (`releases.json`) acumula todas las versiones
publicadas para que el tab Sistema las liste y permita instalar cualquiera.

Uso (orden de build completo):
    venv\\Scripts\\pyinstaller --noconfirm tools\\updater.spec
    venv\\Scripts\\pyinstaller --noconfirm WTSControl.spec
    venv\\Scripts\\python tools\\hacer_manifest.py 1.1.0 --notas "Corrige la torre de luces"
    [--build dist\\WTSControl] [--salida dist] [--catalogo release\\releases.json]

`--notas-archivo ruta.txt` lee las notas de un archivo (UTF-8) en vez de la
linea de comandos. En `--notas`, las secuencias `\\n` y `\\t` se interpretan
como salto de linea y tabulacion. `--catalogo` decide donde se acumula el
catalogo; por defecto `<salida>/releases.json`.

Luego copia `manifest.json`, `WTSControl-<version>.zip` y `releases.json` a la
carpeta que sirve `tools\\servidor_actualizaciones.py` (carpeta `release/` por
defecto).
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


def interpretar_escapes(texto):
    """Convierte secuencias escritas en la linea de comandos en texto real.

    En Windows/PowerShell es facil escribir `\\n` literal (PowerShell usa
    backtick, no backslash). Aqui `\\n` se vuelve un salto de linea y `\\t` una
    tabulacion, para poder publicar notas de varias lineas sin archivo aparte.
    """
    return (
        str(texto)
        .replace("\\r\\n", "\n")
        .replace("\\n", "\n")
        .replace("\\t", "\t")
    )


def sha256_de_archivo(ruta):
    h = hashlib.sha256()
    with open(ruta, "rb") as f:
        while True:
            bloque = f.read(1024 * 1024)
            if not bloque:
                break
            h.update(bloque)
    return h.hexdigest()


def _clave_version(version):
    """Clave ordenable de una version 'X.Y.Z' (tolera partes no numericas)."""
    partes = []
    for parte in str(version).split("."):
        try:
            partes.append(int(parte))
        except ValueError:
            partes.append(0)
    return tuple(partes) or (0,)


def _leer_catalogo(ruta):
    """Entradas validas del catalogo existente (lista vacia si no existe)."""
    if not os.path.exists(ruta):
        return []
    try:
        with open(ruta, "r", encoding="utf-8") as f:
            datos = json.load(f)
    except (OSError, ValueError):
        return []
    if isinstance(datos, dict):
        entradas = datos.get("actualizaciones")
        if entradas is None:
            entradas = datos.get("releases")
    elif isinstance(datos, list):
        entradas = datos
    else:
        entradas = []
    return [
        entrada
        for entrada in (entradas or [])
        if isinstance(entrada, dict) and entrada.get("version")
    ]


def actualizar_catalogo(ruta_catalogo, manifest):
    """Agrega/reemplaza la entrada de `manifest` y ordena de nueva a vieja."""
    version = str(manifest["version"])
    entradas = [
        entrada
        for entrada in _leer_catalogo(ruta_catalogo)
        if str(entrada.get("version")) != version
    ]
    entradas.append({
        "version": version,
        "published_at": manifest["published_at"],
        "notas": manifest.get("notas", ""),
        "zip": manifest["zip"],
    })
    entradas.sort(
        key=lambda entrada: _clave_version(entrada.get("version", "")),
        reverse=True,
    )
    datos = {
        "generado": manifest["published_at"],
        "actualizaciones": entradas,
    }
    carpeta = os.path.dirname(os.path.abspath(ruta_catalogo))
    os.makedirs(carpeta, exist_ok=True)
    with open(ruta_catalogo, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=2)
    return ruta_catalogo


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
    parser.add_argument(
        "--notas", default="",
        help="Comentario de los cambios/features (acepta \\n para saltos de linea)",
    )
    parser.add_argument(
        "--notas-archivo", default="",
        help="Lee las notas de este archivo de texto UTF-8 (ignora --notas)",
    )
    parser.add_argument(
        "--catalogo", default="",
        help="Ruta del releases.json a actualizar (default: <salida>/releases.json)",
    )
    args = parser.parse_args()

    build = os.path.abspath(args.build)
    salida = os.path.abspath(args.salida)
    version = args.version.strip()

    notas = interpretar_escapes(args.notas)
    if args.notas_archivo:
        try:
            with open(args.notas_archivo, "r", encoding="utf-8-sig") as f:
                notas = f.read()
        except OSError as e:
            print(f"ERROR: no se pudo leer --notas-archivo: {e}")
            sys.exit(1)
    notas = notas.strip()

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
    os.makedirs(salida, exist_ok=True)
    with zipfile.ZipFile(zip_ruta, "w", zipfile.ZIP_DEFLATED) as z:
        for rel in archivos:
            z.write(os.path.join(build, rel), rel)

    manifest = {
        "version": version,
        "published_at": datetime.now(ZONA).strftime("%Y-%m-%d %H:%M:%S"),
        "notas": notas,
        "zip": {
            "archivo": zip_nombre,
            "sha256": sha256_de_archivo(zip_ruta),
            "size": os.path.getsize(zip_ruta),
        },
        "files": archivos,
    }
    man_ruta = os.path.join(salida, "manifest.json")
    with open(man_ruta, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    catalogo = args.catalogo or os.path.join(salida, "releases.json")
    actualizar_catalogo(catalogo, manifest)

    print(f"manifest.json  -> {man_ruta}")
    print(f"{zip_nombre} -> {zip_ruta}")
    print(f"catalogo       -> {os.path.abspath(catalogo)}")
    print(f"({len(archivos)} archivos)")
    if notas:
        print(f"notas: {notas.splitlines()[0]}")
    print()
    print("Copia manifest.json, el zip y releases.json a la carpeta servida por "
          "servidor_actualizaciones.py (carpeta 'release/' por defecto).")


if __name__ == "__main__":
    main()

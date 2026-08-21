#!/usr/bin/env python
"""
hacer_version.py - Pipeline completo de release de WTSControl en un comando.

Automatiza el proceso manual documentado en README (seccion Empaquetado y
Actualizaciones). Uso desde la raiz del proyecto:

    venv\\Scripts\\python tools\\hacer_version.py 1.1.3

Pasos que ejecuta:
    1. Valida la version y hace bump de version.txt.
    2. Compila el updater interno (tools/updater.spec) SIEMPRE primero: la
       app lo empaqueta como data en _internal/updater/.
    3. Compila la app onedir (WTSControl.spec -> dist/WTSControl).
    4. Verifica el build: exe presente, version embebida correcta, updater
       embebido y DLLs del SDK de DigitalPersona en _internal.
    5. Genera manifest.json + WTSControl-<version>.zip (reutiliza
       tools/hacer_manifest.py).
    6. Copia ambos a release/.

El servidor de actualizaciones NO se enciende automaticamente: es el
interruptor del rollout (encender SOLO al publicar) y se deja a decision
humana. Si algo falla, el proceso aborta con codigo distinto de cero y los
pasos ya completados quedan intactos (es seguro re-ejecutar).
"""

import argparse
import os
import re
import shutil
import subprocess
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VERSION_TXT = os.path.join(RAIZ, "version.txt")
PYINSTALLER = os.path.join(RAIZ, "venv", "Scripts", "pyinstaller.exe")
HACER_MANIFEST = os.path.join(RAIZ, "tools", "hacer_manifest.py")
DIST = os.path.join(RAIZ, "dist")
BUILD_APP = os.path.join(DIST, "WTSControl")
INTERNAL = os.path.join(BUILD_APP, "_internal")
RELEASE = os.path.join(RAIZ, "release")

# DLLs minimos que _ruta_dll() necesita encontrar en _internal (la cadena
# completa vive en sdk/vendor/dpf del repo; aqui solo se comprueba la base).
DLLS_SDK_MINIMOS = ("dpfpdd.dll", "dpfj.dll", "nex_sdk.dll")


def paso(numero, descripcion):
    print()
    print(f"=== [{numero}/6] {descripcion} ===")


def morir(motivo):
    print(f"\nERROR: {motivo}")
    print("Release ABORTADO; lo ya construido queda intacto.")
    sys.exit(1)


def ejecutar(cmd, descripcion):
    print(f"$ {' '.join(cmd)}")
    resultado = subprocess.run(cmd, cwd=RAIZ)
    if resultado.returncode != 0:
        morir(f"{descripcion}: el comando termino con codigo "
              f"{resultado.returncode}")


def validar_version(version):
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        morir(f"Version invalida '{version}'. Formato esperado: X.Y.Z "
              "(ej. 1.1.3)")


def bump_version(version):
    actual = ""
    if os.path.exists(VERSION_TXT):
        with open(VERSION_TXT, "r", encoding="utf-8") as f:
            actual = f.read().strip()
    if actual == version:
        print(f"version.txt ya esta en {version}; se reescribe igual.")
    elif actual:
        print(f"Bump: {actual} -> {version}")
    else:
        print(f"Creando version.txt con {version}")
    with open(VERSION_TXT, "w", encoding="utf-8") as f:
        f.write(version + "\n")


def verificar_build(version):
    exe = os.path.join(BUILD_APP, "WTSControl.exe")
    if not os.path.isfile(exe):
        morir(f"Falta {exe}")
    ver_embebido = os.path.join(INTERNAL, "version.txt")
    if not os.path.isfile(ver_embebido):
        morir("El build no tiene version.txt embebido en _internal/")
    with open(ver_embebido, "r", encoding="utf-8") as f:
        if f.read().strip() != version:
            morir(f"{ver_embebido} no dice {version}")
    updater = os.path.join(INTERNAL, "updater", "WTSControlUpdater.exe")
    if not os.path.isfile(updater):
        morir("Falta el updater embebido (_internal/updater/"
              "WTSControlUpdater.exe): ¿se compilo tools/updater.spec antes?")
    for dll in DLLS_SDK_MINIMOS:
        if not os.path.isfile(os.path.join(INTERNAL, dll)):
            morir(f"Falta {dll} en _internal/ (SDK DigitalPersona)")
    print("[OK] WTSControl.exe, version embebida, updater y DLLs SDK "
          "presentes.")


def copiar_a_release(nombre):
    origen = os.path.join(DIST, nombre)
    if not os.path.isfile(origen):
        morir(f"No se genero {origen}")
    os.makedirs(RELEASE, exist_ok=True)
    destino = os.path.join(RELEASE, nombre)
    shutil.copy2(origen, destino)
    mb = os.path.getsize(destino) / (1024 * 1024)
    print(f"[OK] release/{nombre} ({mb:.1f} MB)")


def main():
    parser = argparse.ArgumentParser(
        description="Pipeline completo de release de WTSControl."
    )
    parser.add_argument("version", help="Version nueva (ej. 1.1.3)")
    args = parser.parse_args()
    version = args.version.strip()

    validar_version(version)
    if not os.path.isfile(PYINSTALLER):
        morir(f"No existe {PYINSTALLER}. Usa el venv del proyecto.")
    if not os.path.isfile(HACER_MANIFEST):
        morir(f"No existe {HACER_MANIFEST}")

    paso(1, "Bump de version.txt")
    bump_version(version)

    paso(2, "Compilando updater interno (siempre primero)")
    ejecutar([PYINSTALLER, "--noconfirm",
              os.path.join("tools", "updater.spec")], "build del updater")

    paso(3, "Compilando app (WTSControl.spec)")
    ejecutar([PYINSTALLER, "--noconfirm", "WTSControl.spec"], "build de la app")

    paso(4, "Verificando build")
    verificar_build(version)

    paso(5, "Generando manifest.json + zip")
    ejecutar([sys.executable, HACER_MANIFEST, version], "manifest")

    paso(6, "Copiando a release/")
    copiar_a_release("manifest.json")
    copiar_a_release(f"WTSControl-{version}.zip")

    print()
    print("=" * 60)
    print(f"RELEASE {version} LISTO en release/")
    print("=" * 60)
    print("Siguiente paso MANUAL (interruptor del rollout): encender el")
    print("servidor SOLO al publicar:")
    print("    venv\\Scripts\\python tools\\servidor_actualizaciones.py")
    print("(recuerda apagarlo al terminar la ventana de actualizacion).")


if __name__ == "__main__":
    main()

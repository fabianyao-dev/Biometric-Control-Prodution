#!/usr/bin/env python
"""
updater.py - Updater interno de WTSControl (sub-proceso, solo stdlib).

La GUI no puede reemplazarse a si misma: Windows bloquea el .exe y sus
modulos mientras corren. Por eso la app:
    1) descarga y verifica (sha256) el zip de la nueva version,
    2) lanza ESTE proceso (WTSControlUpdater.exe, vive en la carpeta de
       datos fuera de la instalacion) y se cierra,
    3) el updater espera a que la app termine, extrae el zip y reemplaza
       la instalacion con respaldo (`<instalar>_backup`) y relanza la app.

El respaldo permite rollback manual: si la nueva version falla, borrar la
instalacion nueva y renombrar `<instalar>_backup` a `<instalar>`.

Solo usa stdlib (no PySide6) para arrancar rapido y ser tiny. Se compila
como ONE-file (tools/updater.spec) y se empaqueta como data de la app.

Nota operativa: el updater renombra la carpeta de instalacion, asi que la
PC debe tener permisos de escritura sobre el directorio PADRE de la
instalacion (recomendado: instalar en una carpeta con permisos del usuario
kiosco, ej. %LOCALAPPDATA%\\WTSControl).
"""

import argparse
import ctypes
import os
import shutil
import subprocess
import sys
import time
import zipfile

NOMBRE_APP = "WTSControl.exe"
TIMEOUT_ESPERA_APP_S = 90
INTENTOS_SWAP = 30


def log(msg, rutas):
    """Escribe `msg` en cada ruta de `rutas` (una ruta o una lista de rutas).

    El updater es un proceso aparte (stdlib), asi que no puede usar el logging
    de la app; escribe en su propio `updater.log` y, si se le pasa, tambien en
    el `produccion.log` de la app para tener todo en un solo lugar.
    """
    if isinstance(rutas, str):
        rutas = [rutas]
    linea = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}\n"
    for ruta in rutas:
        if not ruta:
            continue
        try:
            with open(ruta, "a", encoding="utf-8") as f:
                f.write(linea)
        except OSError:
            pass


def proceso_vivo(pid):
    if pid <= 0:
        return False
    try:
        h = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if not h:
            return False
        ctypes.windll.kernel32.CloseHandle(h)
        return True
    except Exception:  # noqa: BLE001
        return False


def leer_version(carpeta):
    """Lee version.txt de la instalacion (vive en `_internal/` en onedir).

    utf-8-sig: tolera BOM por si el archivo se edito con Notepad/PowerShell;
    de lo contrario "\\ufeff1.1.0" != "1.1.0" y la actualizacion se rechaza.
    """
    for nombre in ("_internal/version.txt", "version.txt"):
        ruta = os.path.join(carpeta, *nombre.split("/"))
        if os.path.exists(ruta):
            with open(ruta, "r", encoding="utf-8-sig") as f:
                v = f.read().strip()
            if v:
                return v
    return None


def extraer_zip(zip_path, destino):
    if os.path.exists(destino):
        shutil.rmtree(destino, ignore_errors=True)
    os.makedirs(destino, exist_ok=True)
    base = os.path.normpath(destino) + os.sep
    with zipfile.ZipFile(zip_path, "r") as z:
        for miembro in z.infolist():
            objetivo = os.path.normpath(os.path.join(destino, miembro.filename))
            if not objetivo.startswith(base):
                raise RuntimeError("zip inseguro (path traversal)")
            z.extract(miembro, destino)


def renombrar_con_reintentos(origen, destino):
    for _ in range(INTENTOS_SWAP):
        try:
            os.rename(origen, destino)
            return True
        except OSError:
            time.sleep(1)
    return False


def aplicar(zip_path, version, instalar, relanzar, log_path):
    log("updater iniciado", log_path)
    if not os.path.exists(os.path.join(instalar, NOMBRE_APP)):
        log(f"ERROR: no hay app en {instalar}", log_path)
        return 1

    pendiente = instalar + "_pending"
    respaldo = instalar + "_backup"

    # 1. Extraer la nueva version a una carpeta pendiente.
    extraer_zip(zip_path, pendiente)
    if not os.path.exists(os.path.join(pendiente, NOMBRE_APP)):
        log("ERROR: el zip no contiene WTSControl.exe", log_path)
        shutil.rmtree(pendiente, ignore_errors=True)
        return 2
    nueva = leer_version(pendiente)
    if nueva is None:
        log("AVISO: la nueva version no trae version.txt", log_path)
    elif nueva != version:
        log(f"ERROR: version esperada {version}, el paquete dice {nueva}", log_path)
        shutil.rmtree(pendiente, ignore_errors=True)
        return 3

    # 2. Intercambio de carpetas con respaldo (rollback manual posible).
    log("reemplazando instalacion...", log_path)
    if os.path.exists(respaldo):
        shutil.rmtree(respaldo, ignore_errors=True)
    if not renombrar_con_reintentos(instalar, respaldo):
        log("ERROR: no se pudo mover la instalacion actual a _backup", log_path)
        shutil.rmtree(pendiente, ignore_errors=True)
        return 4
    if not renombrar_con_reintentos(pendiente, instalar):
        log("ERROR: no se pudo instalar la version nueva; restaurando backup", log_path)
        renombrar_con_reintentos(respaldo, instalar)
        shutil.rmtree(pendiente, ignore_errors=True)
        return 5
    log(f"actualizacion aplicada: {nueva or version}", log_path)

    # Limpieza: el zip ya no se necesita tras aplicar con exito. Solo se
    # borra aqui (no en errores) para que un reintento manual lo pueda usar.
    try:
        os.remove(zip_path)
    except OSError:
        pass

    # 3. Relanzar la app (si se pidio).
    if relanzar:
        exe = os.path.join(instalar, NOMBRE_APP)
        try:
            subprocess.Popen([exe], cwd=instalar)
            log("app relanzada", log_path)
        except Exception as e:  # noqa: BLE001
            log(f"ERROR al relanzar la app: {e}", log_path)
    return 0


def main():
    # Windows no permite renombrar una carpeta que sea el cwd de algun proceso.
    # El fix REAL esta en src/update.py: la app lanza este updater con
    # cwd=config.DIR_DATOS (fuera de la instalacion). Este chdir es solo una
    # defensa extra para invocaciones manuales (python tools/updater.py); en el
    # exe ONE-file no basta porque el bootloader padre de PyInstaller conserva
    # el cwd heredado, pero aqui es inofensivo y cubre la ejecucion con
    # interpretador.
    try:
        os.chdir(os.path.dirname(os.path.abspath(sys.executable)))
    except OSError:
        pass

    parser = argparse.ArgumentParser(description="Updater interno de WTSControl")
    parser.add_argument("--zip", required=True, help="Zip verificado de la nueva version")
    parser.add_argument("--version", required=True, help="Version esperada")
    parser.add_argument("--instalar", required=True, help="Carpeta de instalacion actual")
    parser.add_argument("--pid", type=int, default=0, help="PID de la app a esperar")
    parser.add_argument("--log", default="", help="Ruta del log del updater")
    parser.add_argument("--log-app", default="",
                        help="Log adicional (produccion.log de la app)")
    parser.add_argument("--relanzar", action="store_true", help="Relanzar la app al terminar")
    args = parser.parse_args()

    rutas = [p for p in (args.log, args.log_app) if p]
    if not rutas:
        # Sin rutas explicitas (p. ej. invocado a mano): respaldo en el home.
        rutas = [os.path.join(os.path.expanduser("~"), "updater.log")]

    if args.pid > 0:
        log(f"esperando a que la app (pid {args.pid}) salga...", rutas)
        esperado = 0.0
        while proceso_vivo(args.pid) and esperado < TIMEOUT_ESPERA_APP_S:
            time.sleep(0.5)
            esperado += 0.5
        if proceso_vivo(args.pid):
            log("ERROR: timeout esperando a la app; no se aplica nada", rutas)
            sys.exit(6)
        # Pequena pausa para que Windows libere los handles de los archivos.
        time.sleep(1)

    codigo = aplicar(args.zip, args.version, args.instalar, args.relanzar, rutas)
    log(f"updater termino con codigo {codigo}", rutas)
    sys.exit(codigo)


if __name__ == "__main__":
    main()
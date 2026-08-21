"""
update.py - Actualizaciones por red (buscar version + aplicar).

Capa que la GUI usa para:
    - Conocer la version instalada (version.txt empaquetado).
    - Consultar el servidor HTTP (manifest.json) y saber si hay una version
      nueva (sin descargar nada).
    - Descargar y verificar (sha256) el .zip de la nueva version a la carpeta
      de datos persistente (fuera de la instalacion).
    - Preparar el updater interno (WTSControlUpdater.exe) en la carpeta de
      datos y lanzarlo: aplica el intercambio de archivos y relanza la app.

El updater es un sub-proceso independiente (solo stdlib) porque Windows
bloquea los archivos de un .exe en ejecucion: la app no puede reemplazarse
a si misma estando abierta. La app se limita a descargar/verificar y a
lanzar el updater; luego se cierra y el updater hace el swap con respaldo.
"""

import glob
import hashlib
import json
import logging
import os
import shutil
import subprocess
import sys
import urllib.request

from src import config

log = logging.getLogger(__name__)

NOMBRE_MANIFEST = "manifest.json"
NOMBRE_UPDATER = "WTSControlUpdater.exe"


def _dir_instalacion():
    """Carpeta donde vive WTSControl.exe (la que se reemplaza al actualizar)."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return config.RUTA_BASE


def ruta_version_txt():
    """version.txt: empaquetado en `_internal` (frozen) o en la raiz (dev)."""
    if getattr(sys, "frozen", False):
        base = getattr(sys, "_MEIPASS", _dir_instalacion())
        return os.path.join(base, "version.txt")
    return os.path.join(config.RUTA_BASE, "version.txt")


def version_instalada() -> str:
    """Version local (del version.txt empaquetado). '0.0.0' si no existe.

    Se lee con utf-8-sig por si el version.txt se edito con un editor que
    escriba BOM (Notepad/PowerShell): un BOM rompe la comparacion estricta
    del updater (version "\\ufeff1.1.0" != "1.1.0").
    """
    try:
        with open(ruta_version_txt(), "r", encoding="utf-8-sig") as f:
            v = f.read().strip()
        return v or "0.0.0"
    except OSError:
        return "0.0.0"


def url_manifest():
    """URL del manifest remoto o None si no hay UPDATE_SOURCE."""
    fuente = (config.UPDATE_SOURCE or "").strip().rstrip("/")
    if not fuente:
        return None
    return f"{fuente}/{NOMBRE_MANIFEST}"


def consultar_manifest(timeout=None):
    """Descarga y devuelve el manifest del servidor. Lanza excepcion si no
    hay UPDATE_SOURCE o si el servidor no responde."""
    url = url_manifest()
    if not url:
        raise RuntimeError(
            "Actualizaciones por red no configuradas (UPDATE_SOURCE vacio)."
        )
    tmo = config.UPDATE_TIMEOUT_S if timeout is None else timeout
    with urllib.request.urlopen(url, timeout=tmo) as r:
        return json.loads(r.read().decode("utf-8"))


def _cmp_version(a, b):
    """Compara versiones 'X.Y.Z' (devuelve <0, 0 o >0). Tolera partes no
    numericas (las trata como 0)."""

    def parse(v):
        partes = []
        for p in str(v).split("."):
            try:
                partes.append(int(p))
            except ValueError:
                partes.append(0)
        return partes or [0]

    va, vb = parse(a), parse(b)
    for x, y in zip(va, vb):
        if x != y:
            return (x > y) - (x < y)
    return (len(va) > len(vb)) - (len(va) < len(vb))


def hay_version_nueva(manifest) -> bool:
    """True si el manifest anuncia una version posterior a la instalada."""
    remota = str((manifest or {}).get("version", "")).strip()
    if not remota:
        return False
    return _cmp_version(remota, version_instalada()) > 0


def _url_zip(manifest):
    fuente = (config.UPDATE_SOURCE or "").strip().rstrip("/")
    archivo = (manifest.get("zip") or {}).get("archivo")
    if not fuente or not archivo:
        return None
    return f"{fuente}/{archivo}"


def _descargar(url, destino, timeout=None):
    tmo = config.UPDATE_TIMEOUT_S if timeout is None else timeout
    with urllib.request.urlopen(url, timeout=tmo) as r:
        with open(destino, "wb") as f:
            shutil.copyfileobj(r, f)


def descargar_y_verificar(manifest):
    """Descarga el .zip de la nueva version a la carpeta de datos y verifica
    su sha256 contra el manifest. Devuelve la ruta del zip descargado."""
    url = _url_zip(manifest)
    if not url:
        raise RuntimeError("El manifest no define el archivo de descarga.")
    esperado = str((manifest.get("zip") or {}).get("sha256") or "").lower()
    if not esperado:
        raise RuntimeError("El manifest no define el sha256 del paquete.")

    dir_updates = os.path.join(config.DIR_DATOS, "updates")
    os.makedirs(dir_updates, exist_ok=True)
    archivo = os.path.basename(url).split("?")[0] or "WTSControl.zip"
    destino = os.path.join(dir_updates, archivo)

    log.info("Descargando actualizacion: %s", url)
    _descargar(url, destino)
    with open(destino, "rb") as f:
        real = hashlib.sha256(f.read()).hexdigest().lower()
    if real != esperado:
        try:
            os.remove(destino)
        except OSError:
            pass
        raise RuntimeError("El paquete descargado no coincide con su sha256.")
    log.info("Paquete de actualizacion verificado: %s", destino)

    # Limpieza: mantener solo el zip recien descargado (los viejos son
    # ~60 MB muertos). El updater borra este al aplicar con exito.
    try:
        for viejo in glob.glob(os.path.join(dir_updates, "WTSControl-*.zip")):
            if os.path.abspath(viejo) != os.path.abspath(destino):
                os.remove(viejo)
    except OSError:
        pass
    return destino


def ruta_updater_empaquetado():
    """Updater interno empaquetado como data en `_internal/updater/`."""
    if getattr(sys, "frozen", False):
        base = getattr(sys, "_MEIPASS", _dir_instalacion())
        return os.path.join(base, "updater", NOMBRE_UPDATER)
    ruta_dev = os.path.join(config.RUTA_BASE, "tools", NOMBRE_UPDATER)
    if os.path.exists(ruta_dev):
        return ruta_dev
    return None


def preparar_updater():
    """Copia el updater empaquetado a la carpeta de datos (fuera de la
    instalacion, para que no se bloquee al reemplazar archivos) y devuelve
    su ruta."""
    origen = ruta_updater_empaquetado()
    if not origen or not os.path.exists(origen):
        raise RuntimeError(
            "El paquete interno de actualizacion no existe (WTSControlUpdater.exe)."
        )
    destino_dir = os.path.join(config.DIR_DATOS, "updater")
    os.makedirs(destino_dir, exist_ok=True)
    destino = os.path.join(destino_dir, NOMBRE_UPDATER)
    shutil.copy2(origen, destino)
    return destino


def lanzar_updater(ruta_updater, zip_path, version, relanzar=True):
    """Lanza el updater en proceso separado (no bloquea la GUI) y devuelve
    el subprocess. La app debe cerrarse justo despues (controlador.cleanup +
    close): el updater espera a que termine para reemplazar archivos."""
    args = [
        ruta_updater,
        "--zip", zip_path,
        "--version", str(version),
        "--instalar", _dir_instalacion(),
        "--pid", str(os.getpid()),
        "--log-app", os.path.join(config.LOG_DIR, "produccion.log"),
    ]
    if relanzar:
        args.append("--relanzar")
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    log.info("Lanzando updater interno: %s", ruta_updater)
    # cwd fuera de la instalacion: si la app se lanzo desde su carpeta, el
    # updater heredaria ese cwd y Windows no le dejaria renombrar la instalacion
    # a _backup (ERROR_ACCESS_DENIED). El updater vive en la carpeta de datos.
    return subprocess.Popen(args, cwd=config.DIR_DATOS, close_fds=True,
                            creationflags=flags)
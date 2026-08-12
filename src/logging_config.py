"""
logging_config.py - Logs con rotacion diaria para la PC Fanless.

En produccion no hay consola: los logs van a un archivo diario
(produccion.log con rotacion a medianoche) y el handler borra automaticamente
los archivos de mas de 30 dias para no llenar el disco. Se mantiene ademas la
consola para desarrollo. Formato identico al que usaba `main.py`.
"""

import logging
import logging.handlers
import os
import re

from src import config

FORMATO = "%(asctime)s.%(msecs)03d [%(levelname)s] (%(threadName)s) %(message)s"
FECHA = "%H:%M:%S"
BACKUP_DIAS = 30


def configurar_logging(nivel=logging.INFO):
    """Configura el logging raiz (consola + archivo diario). Idempotente."""
    root = logging.getLogger()
    if getattr(root, "_produccion_logging_configurado", False):
        return root
    root.setLevel(nivel)

    formatter = logging.Formatter(FORMATO, datefmt=FECHA)

    consola = logging.StreamHandler()
    consola.setFormatter(formatter)
    root.addHandler(consola)

    log_dir = config.LOG_DIR
    os.makedirs(log_dir, exist_ok=True)
    archivo = os.path.join(log_dir, "produccion.log")
    rotatorio = logging.handlers.TimedRotatingFileHandler(
        archivo, when="midnight", interval=1,
        backupCount=BACKUP_DIAS, encoding="utf-8",
    )
    rotatorio.suffix = "%Y_%m_%d"
    rotatorio.extMatch = re.compile(r"^\d{4}_\d{2}_\d{2}$")
    rotatorio.setFormatter(formatter)
    root.addHandler(rotatorio)

    root._produccion_logging_configurado = True
    logging.getLogger(__name__).info(
        "Logging configurado: consola + archivo diario en %s (retener %s dias).",
        archivo, BACKUP_DIAS,
    )
    return root

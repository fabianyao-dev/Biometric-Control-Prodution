import os

from dotenv import load_dotenv

RUTA_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(RUTA_BASE, ".env"))

# Ruta de la BD configurable (.env) para que sobreviva al empaquetado con
# PyInstaller, donde `__file__` cae dentro del directorio temporal.
DB_PATH = os.environ.get("DB_PATH") or os.path.join(RUTA_BASE, "planta_corte.db")

# Directorio de logs diarios con rotacion (30 dias).
LOG_DIR = os.environ.get("LOG_DIR") or os.path.join(RUTA_BASE, "logs")

# Zona horaria oficial de la planta (America/Monterrey).
ZONA_HORARIA = "America/Monterrey"

CAPTURE_TIMEOUT_MS = 60000
CAPTURE_BUFFER_SIZE = 512 * 1024
IMAGE_FMT_PIXEL_BUFFER = 0
IMAGE_PROC_DEFAULT = 0

FMD_FORMAT = 0x001B0001
CBEFF_ID = 0x00000000
FINGER_POSITION = 0

UMBRAL_DISIMILARIDAD = 0x04000000

# --- Simulacion (fallback cuando no hay Modbus) ---
# SimulacionController usa estos valores de referencia solo en modo
# simulacion (sin hardware real).
SIMULACION_CONFIG = {
    "rele_start": 5,
    "rele_pause": 6,
    "sensor_corte": 27,
    "conteo_bouncetime_ms": 50,
    "pulso_duracion_ms": 300,
}
REFRESCO_CONTADOR_MS = 100


def _env_int(clave, por_defecto):
    valor = os.environ.get(clave)
    try:
        return int(valor) if valor is not None else por_defecto
    except ValueError:
        return por_defecto


def _env_bool(clave, por_defecto=False):
    valor = os.environ.get(clave)
    if valor is None:
        return por_defecto
    return valor.strip().lower() in ("1", "true", "si", "yes", "on")


# --- Modbus TCP (PC Fanless Windows) ---
# Contador interno de alta velocidad del modulo Advantech: el PC solo hace
# polling por red; NUNCA cuenta flancos localmente (Windows no es RTOS y un
# micro-congelamiento perderia cortes). Sin `MODBUS_HOST` o con
# `MODBUS_SIMULACION=1` se cae a modo simulacion.
MODBUS_CONFIG = {
    "host": os.environ.get("MODBUS_HOST", "").strip(),
    "port": _env_int("MODBUS_PORT", 502),
    "unit_id": _env_int("MODBUS_UNIT_ID", 1),
    "timeout": 2.0,
    "start_coil": _env_int("MODBUS_START_COIL", 0),
    "pause_coil": _env_int("MODBUS_PAUSE_COIL", 1),
    "counter_register": _env_int("MODBUS_COUNTER_REGISTER", 0),
    "counter_words": _env_int("MODBUS_COUNTER_WORDS", 2),
    "poll_ms": _env_int("MODBUS_POLL_MS", 500),
    "pulso_duracion_ms": _env_int("PULSO_DURACION_MS", 300),
    "max_delta": _env_int("MODBUS_COUNTER_MAX_DELTA", 10000),
    "modo_simulacion": _env_bool("MODBUS_SIMULACION", not bool(os.environ.get("MODBUS_HOST", "").strip())),
}


# Cada cuanto se guarda en la BD el total de cortes de la sesion activa, como
# respaldo ante cortes de luz o cierres abruptos.
CORTES_GUARDAR_INTERVALO_MS = 30000

# Tiempo sin recibir cortes (en segundos) con la maquina en marcha que
# dispara automaticamente el modal de seleccion de paro. 0 = desactivado.
PARO_IDLE_TIMEOUT_S = 60

# Selector de causa de paro: cuadricula con las causas mas usadas.
CAUSAS_FRECUENTES_LIMITE = 6
CAUSAS_GRID_COLUMNAS = 3

# Roles con autoridad para autorizar la reanudacion de un paro (ademas del
# operador dueno de la sesion, que siempre puede).
ROLES_AUTORIZAN_PARO = ("admin", "supervisor")

# Roles con acceso a cada vista protegida de la navegacion (se valida con
# huella al pulsar el boton del panel lateral).
ROLES_ACCESO_SESIONES = ("admin", "supervisor")
ROLES_ACCESO_ADMIN = ("admin",)

import os

RUTA_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(RUTA_BASE, "planta_corte.db")

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
FPRINTD_TIMEOUT_S = 15

LIBFPRINT_ENROLL_TIMEOUT_S = 120
LIBFPRINT_IDENTIFY_TIMEOUT_S = 90
LIBFPRINT_MAX_RETRIES = 90

# --- GPIO (Raspberry Pi 4, BCM) ---
GPIO_CONFIG = {
    "rele_start": 5,
    "rele_pause": 6,
    "sensor_corte": 27,
    "conteo_bouncetime_ms": 50,
    "pulso_duracion_ms": 300,
    "modo_simulacion": False,
}
GPIO_REFRESH_MS = 100

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

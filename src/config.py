import json
import logging
import os
import shutil
import sys
import tempfile

from dotenv import load_dotenv

log = logging.getLogger(__name__)

RUTA_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ---------------------------------------------------------------------------
# Carpeta de datos persistente (solo empaquetado)
# ---------------------------------------------------------------------------
# En el .exe empaquetado, `.env`, `planta_corte.db` y `logs/` viven en una
# carpeta FUERA de la instalacion (por defecto %USERPROFILE%\WTSControlData)
# para que sobrevivan a cada actualizacion del dist. La carpeta se crea en la
# primera ejecucion y los datos que ya vivieran junto al .exe se migran ahi
# una sola vez (nunca se sobrescribe informacion existente).
VAR_DIR_DATOS = "BIOMETRICO_DIR_DATOS"
NOMBRE_DIR_DATOS = "WTSControlData"
NOMBRE_DB = "planta_corte.db"


def _directorio_datos():
    """Carpeta persistente de datos. En desarrollo es la raiz del proyecto."""
    if getattr(sys, "frozen", False):
        override = os.environ.get(VAR_DIR_DATOS, "").strip()
        if override:
            return os.path.abspath(override)
        base = os.environ.get("USERPROFILE") or os.path.expanduser("~")
        return os.path.join(base, NOMBRE_DIR_DATOS)
    return RUTA_BASE


def _leer_lineas(ruta):
    """Lee un .env a lineas, quitando un posible BOM UTF-8 de la primera
    (lo agregan algunos editores/consolas y python-dotenv no lo limpia:
    la primera clave quedaria como \ufeffCLAVE)."""
    with open(ruta, "r", encoding="utf-8") as f:
        lineas = f.readlines()
    if lineas and lineas[0].startswith("\ufeff"):
        lineas[0] = lineas[0][1:]
    return lineas


def _quitar_lineas_ruta(lineas):
    """Deja fuera las lineas DB_PATH/LOG_DIR de un .env (se apuntan a la
    carpeta de datos al migrar)."""
    return [
        l for l in lineas
        if not l.lstrip().startswith(("DB_PATH=", "LOG_DIR="))
    ]


def _asegurar_env(dir_datos, dir_exe=None):
    """Garantiza un .env en la carpeta de datos y devuelve su ruta.

    Si ya existe, lo devuelve tal cual. Si no, lo crea con el contenido del
    .env del .exe (migrado, sin DB_PATH/LOG_DIR) y si no existe, con el
    .env.example empaquetado; como ultimo recurso con unos defaults minimos.
    Siempre termina con DB_PATH y LOG_DIR apuntando a la carpeta de datos.
    """
    ruta_env = os.path.join(dir_datos, ".env")
    if os.path.exists(ruta_env):
        return ruta_env

    lineas = None
    if dir_exe:
        origen = os.path.join(dir_exe, ".env")
        if os.path.exists(origen):
            lineas = _quitar_lineas_ruta(_leer_lineas(origen))

    if lineas is None:
        if getattr(sys, "frozen", False):
            ejemplo = os.path.join(
                getattr(sys, "_MEIPASS", dir_exe or ""), ".env.example"
            )
        else:
            ejemplo = os.path.join(RUTA_BASE, ".env.example")
        if ejemplo and os.path.exists(ejemplo):
            lineas = _quitar_lineas_ruta(_leer_lineas(ejemplo))

    if lineas is None:
        lineas = [
            "# .env generado automaticamente en la carpeta de datos.\n",
            "# Edita solo lo que necesites; se conserva entre actualizaciones.\n",
            "MODBUS_HOST=\n",
            "MODBUS_SIMULACION=1\n",
            "BIOMETRICO_KIOSKO=1\n",
        ]

    lineas.append("\n")
    lineas.append(f"DB_PATH={os.path.join(dir_datos, NOMBRE_DB)}\n")
    lineas.append(f"LOG_DIR={os.path.join(dir_datos, 'logs')}\n")
    with open(ruta_env, "w", encoding="utf-8") as f:
        f.writelines(lineas)
    log.info(".env creado en %s", ruta_env)
    return ruta_env


def _migrar_desde_exe(dir_datos, dir_exe=None, meipass=None):
    """Migra .env, BD y logs de la carpeta del .exe a la carpeta de datos.

    Solo copia lo que aun no exista en la carpeta de datos (primera ejecucion
    tras actualizar el .exe) y nunca sobrescribe datos existentes.
    """
    os.makedirs(dir_datos, exist_ok=True)
    _asegurar_env(dir_datos, dir_exe=dir_exe)

    fuentes = set()
    if dir_exe:
        fuentes.add(dir_exe)
    if meipass:
        fuentes.add(meipass)

    for fuente in fuentes:
        db_origen = os.path.join(fuente, NOMBRE_DB)
        db_destino = os.path.join(dir_datos, NOMBRE_DB)
        if os.path.exists(db_origen) and not os.path.exists(db_destino):
            shutil.copy2(db_origen, db_destino)
            log.info("BD migrada: %s -> %s", db_origen, db_destino)

        logs_origen = os.path.join(fuente, "logs")
        logs_destino = os.path.join(dir_datos, "logs")
        if os.path.isdir(logs_origen) and not os.path.exists(logs_destino):
            shutil.copytree(logs_origen, logs_destino)
            log.info("Logs migrados: %s -> %s", logs_origen, logs_destino)


def _asegurar_datos(dir_datos):
    """Solo empaquetado: prepara la carpeta de datos y migra los datos que
    vivieran junto al .exe. Idempotente."""
    if not getattr(sys, "frozen", False):
        return
    dir_exe = os.path.dirname(sys.executable)
    meipass = getattr(sys, "_MEIPASS", None)
    _migrar_desde_exe(dir_datos, dir_exe, meipass)


# ---------------------------------------------------------------------------
# config.json (archivo de configuracion de la aplicacion)
# ---------------------------------------------------------------------------
# En PRODUCCION (exe) reemplaza al .env: mismas claves (MODBUS_HOST,
# UPDATE_SOURCE, SEGURO_*, DB_PATH, LOG_DIR, ...) en JSON, y es el archivo
# que la app SI puede escribir en caliente (p. ej. el tema claro/oscuro),
# con escritura atomica. En la primera ejecucion se genera automaticamente
# importando las claves del .env que ya existiera en la carpeta de datos.
# En DESARROLLO la configuracion operativa sigue siendo el .env de la raiz;
# config.json local solo guarda preferencias de UI (tema).
NOMBRE_CONFIG_JSON = "config.json"


def ruta_config_json():
    """Ruta del config.json activo: carpeta de datos (produccion) o raiz
    del proyecto (desarrollo)."""
    return os.path.join(DIR_DATOS, NOMBRE_CONFIG_JSON)


def _leer_json(ruta):
    try:
        with open(ruta, "r", encoding="utf-8") as f:
            datos = json.load(f)
        return datos if isinstance(datos, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception:  # noqa: BLE001 - JSON corrupto no debe tirar el arranque
        log.warning("config.json ilegible (%s); se ignora", ruta, exc_info=True)
        return {}


def _escribir_json(ruta, datos):
    """Escritura atomica: temp + replace para no dejar un JSON a medias si
    se va la luz a mitad de guardado."""
    directorio = os.path.dirname(ruta) or "."
    fd, tmp = tempfile.mkstemp(prefix=".config-", dir=directorio)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(datos, f, indent=2, ensure_ascii=True, sort_keys=True)
            f.write("\n")
        os.replace(tmp, ruta)
    except Exception:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def guardar_config(clave, valor):
    """Guarda una clave en el config.json activo (escritura atomica)."""
    ruta = ruta_config_json()
    datos = _leer_json(ruta)
    datos[clave] = valor
    _escribir_json(ruta, datos)
    log.info("config.json: %s = %s", clave, valor)


def leer_config(clave, por_defecto=None):
    """Lee una clave del config.json activo (o el default)."""
    return _leer_json(ruta_config_json()).get(clave, por_defecto)


# Claves operativas que en PRODUCCION se leen del config.json (no del .env)
# y que, si faltan, se siembran con su default para que queden visibles y
# editables. En desarrollo la configuracion operativa sigue siendo el `.env`
# de la raiz. `MODBUS_SIMULACION` se omite: es derivado de `MODBUS_HOST`.
CONFIG_POR_DEFECTO = {
    "UPDATE_SOURCE": "",
    "UPDATE_TIMEOUT_S": 8,
    # Modbus: valores MEDIDOS en el PLC real (Zelio SR3 + SR3NET01BD,
    # 24/10/2026). Una config heredada del modulo Advantech (modo "coil",
    # contador en la palabra 0, 2 palabras) NO funciona con el Zelio: los
    # comandos y la torre no salen y el contador pierde un corte por pulso.
    "MODBUS_HOST": "",
    "MODBUS_PORT": 502,
    "MODBUS_UNIT_ID": 1,
    # "registro" = FC06 sobre las palabras J (el NET01BD no expone coils).
    "MODBUS_CMD_MODE": "registro",
    "MODBUS_START_COIL": 0,
    "MODBUS_PAUSE_COIL": 1,
    "MODBUS_START_REGISTER": 16,
    "MODBUS_START_BIT": 0,
    "MODBUS_PAUSE_REGISTER": 16,
    "MODBUS_PAUSE_BIT": 1,
    # El contador vive en O1 (dir 20) y es de 16 bits: O2 es la palabra de
    # PULSOS, no la palabra alta. Leer 2 palabras pierde cortes.
    "MODBUS_COUNTER_REGISTER": 20,
    "MODBUS_COUNTER_WORDS": 1,
    "MODBUS_COUNTER_LITTLE_ENDIAN": 1,
    "MODBUS_POLL_MS": 500,
    "PULSO_DURACION_MS": 300,
    "MODBUS_COUNTER_MAX_DELTA": 10000,
    "MODBUS_START_COIL_INVERTIDO": 0,
    "MODBUS_PAUSE_COIL_INVERTIDO": 0,
    # Torre de luces: comparte la palabra de comando J1 (dir 16) con marcha
    # (bit0) y paro (bit1); bit2=verde (Q3), bit3=ambar (Q4), bit4=roja (Q5),
    # bit5=alarma/buzzer (Q6).
    "MODBUS_TOWER_REGISTER": 16,
    "MODBUS_TOWER_GREEN_BIT": 2,
    "MODBUS_TOWER_AMBER_BIT": 3,
    "MODBUS_TOWER_RED_BIT": 4,
    "MODBUS_TOWER_ALARM_BIT": 5,
    "MODBUS_TOWER_HEARTBEAT_REGISTER": 19,
    "MODBUS_TOWER_HEARTBEAT_BIT": 0,
    "TORRE_HEARTBEAT_MS": 2000,
    "TORRE_ALARMA_DURACION_S": 3,
    "TORRE_ALARMA_PULSO_ON_MS": 500,
    "TORRE_ALARMA_PULSO_OFF_MS": 500,
    "SEGURO_PARO_SEGUNDOS": 3,
    "SEGURO_RAFAGA_SEGUNDOS": 7,
    "SEGURO_RAFAGA_CORTES": 5,
    "PRIMERA_PIEZA_TIMEOUT_S": 900,
    # Exportacion automatica del reporte del dia (ver EXPORT_AUTO_CONFIG).
    "EXPORT_AUTO_ACTIVO": 1,
    "EXPORT_CADA_HORA": 1,
    "EXPORT_DIR_AUTO": "",
    # Integracion Easy (control remoto de estacion)
    "EASY_HOST": "192.168.1.84",
    "EASY_PUERTO": 5000,
    "EASY_RUTINA": "buscar_easy",
    "EASY_TIMEOUT": 30,
}


def _aplicar_config_json():
    """Produccion: carga config.json sobre el entorno del proceso.

    Si no existe, lo GENERA importando las claves del .env de la carpeta de
    datos (migracion de una sola vez; DB_PATH/LOG_DIR se normalizan a la
    carpeta de datos). Las claves del archivo NO pisan variables de entorno
    ya presentes (setdefault), salvo que vengan del propio archivo.
    """
    ruta = ruta_config_json()
    datos = _leer_json(ruta)
    if not datos:
        origen = {}
        ruta_env = os.path.join(DIR_DATOS, ".env")
        if os.path.exists(ruta_env):
            for linea in _leer_lineas(ruta_env):
                texto = linea.strip()
                if not texto or texto.startswith("#") or "=" not in texto:
                    continue
                clave, _, valor = texto.partition("=")
                origen[clave.strip()] = valor.strip()
        origen["DB_PATH"] = os.path.join(DIR_DATOS, NOMBRE_DB)
        origen["LOG_DIR"] = os.path.join(DIR_DATOS, "logs")
        datos = origen
        _escribir_json(ruta, datos)
        log.info("config.json generado desde .env en %s", ruta)
    # Sembrar con su default las claves operativas que falten (sin pisar las
    # que ya esten, editadas o heredadas del .env).
    cambios = False
    for clave, por_defecto in CONFIG_POR_DEFECTO.items():
        if clave not in datos:
            datos[clave] = por_defecto
            cambios = True
    if cambios:
        _escribir_json(ruta, datos)
    for clave, valor in datos.items():
        if clave == VAR_DIR_DATOS:
            continue  # esa decide DONDE esta esta carpeta: solo entorno
        os.environ.setdefault(str(clave), str(valor))


# ---------------------------------------------------------------------------
# Carga de la configuracion
# ---------------------------------------------------------------------------
DIR_DATOS = _directorio_datos()

if getattr(sys, "frozen", False):
    _asegurar_datos(DIR_DATOS)

# Produccion (exe): config.json en la carpeta de datos es LA configuracion
# (generado desde el .env heredado si hacia falta). Desarrollo: .env de la
# raiz, mas un config.json local opcional solo para preferencias de UI.
if getattr(sys, "frozen", False):
    _aplicar_config_json()
else:
    ruta_env = os.path.join(RUTA_BASE, ".env")
    load_dotenv(ruta_env)
    for clave, valor in _leer_json(ruta_config_json()).items():
        if clave != VAR_DIR_DATOS:
            os.environ.setdefault(str(clave), str(valor))

# Ruta de la BD configurable (.env / config.json). Empaquetado: por defecto
# vive en la carpeta de datos persistente (sobrevive a las actualizaciones
# del .exe); en desarrollo, en la raiz del proyecto.
DB_PATH = os.environ.get("DB_PATH") or os.path.join(DIR_DATOS, NOMBRE_DB)

# Directorio de logs diarios con rotacion (30 dias).
LOG_DIR = os.environ.get("LOG_DIR") or os.path.join(DIR_DATOS, "logs")

# Zona horaria oficial de la planta (America/Monterrey).
ZONA_HORARIA = "America/Monterrey"

CAPTURE_TIMEOUT_MS = 60000
# Timeout CORTO para la captura MULTIPLE encadenada (registro de operador):
# una captura en vuelo no se puede cancelar (llamada nativa bloqueante), asi
# que si el usuario pulsa Guardar/Detener a media captura, el hilo queda
# ocupando el lector hasta que expira. Con 15 s la ventana maxima de "lector
# ocupado" es breve; al expirar, la cadena se rearma sola. Las capturas
# simples (agregar/reemplazar) conservan los 60 s.
CAPTURE_TIMEOUT_CADENA_MS = 15000
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


# --- Actualizaciones por red (opcional) ---
# URL base del servidor de actualizaciones (p. ej. http://10.0.0.2:8080).
# Vacio => la app se comporta igual que hoy (sin boton de actualizar).
UPDATE_SOURCE = os.environ.get("UPDATE_SOURCE", "").strip()

# Timeout de las consultas/descargas HTTP al servidor de actualizaciones.
UPDATE_TIMEOUT_S = _env_int("UPDATE_TIMEOUT_S", 8)


# --- Exportacion automatica del reporte del dia a Excel (opcional) ---
# La app puede generar los reportes sola, sin que nadie entre a Sesiones:
#   - cada hora: snapshot PARCIAL del dia en curso (para que un supervisor
#     vea el turno en vivo; lleva filas 'En curso');
#   - cierre FINAL del dia: se dispara al cerrar la ultima sesion del dia o
#     al cerrar la app (mientras la PC sigue encendida), y al arrancar si un
#     dia terminado quedo pendiente (catch-up). No se espera a una hora fija
#     porque el fin de turno varia.
# `dir` vacio => <carpeta de datos>/exportaciones (junto a la BD, para que
# sobreviva a las actualizaciones del .exe). Pon `activo` en 0 para apagarla.
EXPORT_AUTO_CONFIG = {
    "activo": _env_bool("EXPORT_AUTO_ACTIVO", True),
    "cada_hora": _env_bool("EXPORT_CADA_HORA", True),
    "dir": os.environ.get("EXPORT_DIR_AUTO", "").strip(),
}



# --- Integracion Easy (agente de control remoto de estacion de trabajo) ---
# Al cargar un trabajo se envia el numero de parte al agente Easy para que
# la estacion lo busque automaticamente. Dejar EASY_HOST vacio para
# deshabilitar la integracion sin tocar el codigo.
EASY_CONFIG = {
    "host": os.environ.get("EASY_HOST", "192.168.1.84").strip(),
    "puerto": _env_int("EASY_PUERTO", 5000),
    "rutina": os.environ.get("EASY_RUTINA", "buscar_easy").strip(),
    "timeout": _env_int("EASY_TIMEOUT", 30),
    "token": os.environ.get("EASY_TOKEN", "").strip(),
}


# --- Modbus TCP (PC Fanless Windows) ---
# El CONTADOR de cortes vive en el modulo/PLC: el PC solo hace polling por
# red; NUNCA cuenta flancos localmente (Windows no es RTOS y un
# micro-congelamiento perderia cortes). Sin `MODBUS_HOST` o con
# `MODBUS_SIMULACION=1` se cae a modo simulacion.
#
# Hay DOS modos de comando (`MODBUS_CMD_MODE`), porque el hardware cambio:
#   - "coil"     : modulo Advantech WISE-4060LAN (FC05, coils 16-19).
#   - "registro" : Zelio Logic 2 SR3 + modulo Ethernet SR3NET01BD. Este
#                  NO expone coils: solo 4 palabras de ENTRADA (J1..J4, dirs
#                  16-19, escritura del master) y 4 de SALIDA (O1..O4, dirs
#                  20-23, solo lectura). Los comandos van como un BIT dentro
#                  de una palabra J.
MODBUS_CONFIG = {
    "host": os.environ.get("MODBUS_HOST", "").strip(),
    "port": _env_int("MODBUS_PORT", 502),
    "unit_id": _env_int("MODBUS_UNIT_ID", 1),
    "timeout": 2.0,
    # Modo de escritura de los comandos: "coil" (FC05) o "registro" (FC06).
    "cmd_mode": os.environ.get("MODBUS_CMD_MODE", "coil").strip().lower(),
    "start_coil": _env_int("MODBUS_START_COIL", 0),
    "pause_coil": _env_int("MODBUS_PAUSE_COIL", 1),
    # Modo "registro": palabra J y bit de cada comando (0 = bit0).
    # MEDIDO en el PLC real (24/10/2026): el FBD del Zelio traduce UNA SOLA
    # palabra de comando, J1 (dir 16), con los bits 0-5:
    #   bit0(1)=Q1 marcha, bit1(2)=Q2 paro, bit2(4)=Q3 torre verde,
    #   bit3(8)=Q4 torre ambar, bit4(16)=Q5 torre roja, bit5(32)=Q6 alarma.
    # J2/J3/J4 (dirs 17/18/19) NO controlan nada en el programa actual.
    # Por eso START, PAUSE y TORRE comparten la palabra 16 y el HAL mantiene
    # el valor vigente en `_reg_j` para no pisar los bits de los demas.
    "start_register": _env_int("MODBUS_START_REGISTER", 16),
    "start_bit": _env_int("MODBUS_START_BIT", 0),
    "pause_register": _env_int("MODBUS_PAUSE_REGISTER", 16),
    "pause_bit": _env_int("MODBUS_PAUSE_BIT", 1),
    "counter_register": _env_int("MODBUS_COUNTER_REGISTER", 0),
    # MEDIDO en el PLC real (SR3NET01BD): el contador de cortes esta en O1
    # y es de 16 bits. O2 NO es la palabra alta del contador: es la palabra
    # de PULSOS del PLC (se enciende un instante en cada corte y se apaga
    # solo). Por eso se lee SOLO O1: combinar O1+O2 como 32 bits daria un
    # valor corrupto (+65536 en el instante del pulso), el HAL descartaria
    # el salto y se PIERDEN cortes. El HAL solo necesita deltas y el
    # wraparound a 65535 lo resuelve (`_max_valor`).
    "counter_words": _env_int("MODBUS_COUNTER_WORDS", 1),
    "counter_little_endian": _env_bool("MODBUS_COUNTER_LITTLE_ENDIAN", True),
    "poll_ms": _env_int("MODBUS_POLL_MS", 500),
    "pulso_duracion_ms": _env_int("PULSO_DURACION_MS", 300),
    "max_delta": _env_int("MODBUS_COUNTER_MAX_DELTA", 10000),
    "modo_simulacion": _env_bool(
        "MODBUS_SIMULACION",
        not bool(os.environ.get("MODBUS_HOST", "").strip()),
    ),
    # Polaridad del nivel activo por senal (START pulso / PAUSE latch), igual
    # en los dos modos. Por defecto el nivel activo es True (rele energizado /
    # contacto cerrado). Si el cableado de la maquina es al reves (la maquina
    # actua cuando el circuito se ABRE), poner 1 invierte: activo = False,
    # reposo = True. En modo "registro" la inversion equivale a invertir el
    # bit (activo = bit a 0).
    "start_coil_invertido": _env_bool("MODBUS_START_COIL_INVERTIDO", False),
    "pause_coil_invertido": _env_bool("MODBUS_PAUSE_COIL_INVERTIDO", False),
    # Torre de luces (señalizacion) - comparte la palabra de comando J1 (dir 16)
    # con marcha (bit0) y paro (bit1):
    #   bit2=verde, bit3=ambar, bit4=roja, bit5=alarma
    # J4 (dir 19): heartbeat bit0 (conmutado por la PC cada TORRE_HEARTBEAT_MS).
    # El programa del PLC NO usa J4 (no hay watchdog); se mantiene por si se
    # agrega despues.
    "tower_register": _env_int("MODBUS_TOWER_REGISTER", 16),
    "tower_heartbeat_register": _env_int("MODBUS_TOWER_HEARTBEAT_REGISTER", 19),
    "tower_green_bit": _env_int("MODBUS_TOWER_GREEN_BIT", 2),
    "tower_amber_bit": _env_int("MODBUS_TOWER_AMBER_BIT", 3),
    "tower_red_bit": _env_int("MODBUS_TOWER_RED_BIT", 4),
    "tower_alarm_bit": _env_int("MODBUS_TOWER_ALARM_BIT", 5),
    "tower_heartbeat_bit": _env_int("MODBUS_TOWER_HEARTBEAT_BIT", 0),
    "tower_alarm_pulso_on_ms": _env_int("TORRE_ALARMA_PULSO_ON_MS", 500),
    "tower_alarm_pulso_off_ms": _env_int("TORRE_ALARMA_PULSO_OFF_MS", 500),
    "tower_alarm_duracion_s": _env_int("TORRE_ALARMA_DURACION_S", 3),
    "tower_heartbeat_ms": _env_int("TORRE_HEARTBEAT_MS", 2000),
    "tower_heartbeat_timeout_s": _env_int("TORRE_HEARTBEAT_TIMEOUT_S", 10),
}


def _avisar_config_modbus_heredada(cfg):
    """Avisa si la config de Modbus sigue siendo la del modulo viejo.

    El `.env` de desarrollo se actualiza a mano, pero en PRODUCCION la fuente
    es `config.json`: si viene de una version anterior (Advantech) conserva
    sus valores y la siembra de `CONFIG_POR_DEFECTO` no los pisa (solo agrega
    las claves que faltan). Con el Zelio eso significa comandos/torre que no
    salen (modo coil) o un contador que pierde un corte por pulso (2
    palabras). Se avisa en el log; la correccion es editar `config.json`.
    """
    if not cfg.get("host"):
        return
    if cfg.get("cmd_mode") != "registro":
        log.warning(
            "Modbus: MODBUS_CMD_MODE=%r con el PLC Zelio (host %s). El "
            "NET01BD no expone coils: MARCHA/PARO y la torre no saldrian. "
            "Pon MODBUS_CMD_MODE=registro (ver MAPA_MODBUS_ZELIO.md).",
            cfg.get("cmd_mode"), cfg.get("host"),
        )
        return
    if cfg.get("counter_words") != 1 or cfg.get("counter_register") < 16:
        log.warning(
            "Modbus: contador en registro %s con %s palabra(s). MEDIDO en el "
            "PLC: el contador esta en O1 (dir 20) y es de 16 bits (O2 es la "
            "palabra de PULSOS). Usa MODBUS_COUNTER_REGISTER=20 y "
            "MODBUS_COUNTER_WORDS=1 o se pierde un corte por pulso.",
            cfg.get("counter_register"), cfg.get("counter_words"),
        )


_avisar_config_modbus_heredada(MODBUS_CONFIG)


# Cada cuanto se guarda en la BD el total de cortes de la sesion activa, como
# respaldo ante cortes de luz o cierres abruptos.
CORTES_GUARDAR_INTERVALO_MS = 30000

# Tiempo sin recibir cortes (en segundos) con la maquina en marcha que
# dispara automaticamente el modal de seleccion de paro. 0 = desactivado.
# OJO: NO es la tolerancia de la torre de luces. La torre usa
# `PRIMERA_PIEZA_TIMEOUT_S` (ver abajo): son dos tiempos distintos.
PARO_IDLE_TIMEOUT_S = 60

# Seguro anti-paro / anti-apagado: bloquea el boton PARO y el apagado (cierre
# de sesion) mientras la maquina este en marcha y se haya recibido un corte
# dentro de estos ultimos segundos (la maquina sigue cortando).
SEGURO_PARO_SEGUNDOS = _env_int("SEGURO_PARO_SEGUNDOS", 3)

# Seguro anti-corrida en modo "Primera pieza": si dentro de esta ventana de
# tiempo (segundos) entran mas de SEGURO_RAFAGA_CORTES cortes excluidos, se
# pregunta al operador si la maquina ya empezo a correr; al confirmar y
# autorizar, los cortes hechos durante el modo se incorporan a la sesion.
# 0 en cualquiera de los dos = desactivado.
SEGURO_RAFAGA_SEGUNDOS = _env_int("SEGURO_RAFAGA_SEGUNDOS", 7)
SEGURO_RAFAGA_CORTES = _env_int("SEGURO_RAFAGA_CORTES", 5)

# Timeout del modo "Primera pieza" (segundos). Pasado este tiempo sin salir
# del modo, la salida (para iniciar produccion) exige autorizacion de un rol
# con `autorizar_paro` (supervisor/admin). La maquina NO se apaga ni se sale
# del modo automaticamente; solo se endurece la autorizacion. 0 = desactivado.
# Es TAMBIEN la tolerancia de la torre de luces: un paro real (manual,
# automatico, modo PARO o Mantenimiento con la maquina detenida) se queda en
# ambar este tiempo y luego pasa a roja (Q5) + alarma/buzzer (Q6). Por eso se
# llama "tolerancia de paro" en la operacion. NO confundir con
# `PARO_IDLE_TIMEOUT_S` (el minuto del auto-paro por inactividad).
PRIMERA_PIEZA_TIMEOUT_S = _env_int("PRIMERA_PIEZA_TIMEOUT_S", 900)

# Selector de causa de paro: cuadricula con las causas mas usadas.
CAUSAS_FRECUENTES_LIMITE = 6
CAUSAS_GRID_COLUMNAS = 3

# Modo DESARROLLO sin lector. Con MODO_DEV=true la biometria NO intenta usar
# el lector y en la pantalla de inicio de sesion aparece el boton
# "Entrar como DEV (sin lector)", que inicia sesion directo con el operador
# temporal de desarrollo (obtener_operador_temporal). Pensado para probar la
# interfaz sin hardware biometrico. Nunca debe activarse en produccion.
MODO_DEV = _env_bool("MODO_DEV", False)

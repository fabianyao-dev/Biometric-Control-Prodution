"""Migracion automatica del config.json heredado del modulo Advantech al
PLC Zelio (SR3 + SR3NET01BD).

El `config.json` de la carpeta de datos es la configuracion del .exe. La
siembra de `CONFIG_POR_DEFECTO` solo AGREGA claves faltantes (nunca pisa
valores editados a mano), asi que un config de la era Advantech sobrevive a
la actualizacion de la app con un mapa que NO funciona con el Zelio: coils
16/17, contador de 2 palabras en el registro 0 y sin `MODBUS_CMD_MODE`.

Estos tests fijan la conducta de la migracion (`_migrar_config_a_zelio`) y de
su aplicacion al arrancar el exe (`_aplicar_config_json`).

OJO: los tests NUNCA tocan el config.json real: `ruta_config_json` y
`DIR_DATOS` se apuntan a un temporal con monkeypatch.
"""

import json
import os

import pytest

from src import config

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def config_advantech():
    """Config.json de la era Advantech (coils 16/17, contador 0/2 palabras)."""
    return {
        "BIOMETRICO_KIOSKO": "1",
        "DB_PATH": "C:\\Users\\Dell\\WTSControlData\\planta_corte.db",
        "LOG_DIR": "C:\\Users\\Dell\\WTSControlData\\logs",
        "EXPORT_DIR_AUTO": "\\\\192.168.1.3\\fileserver\\produccion",
        "MODBUS_HOST": "192.168.1.20",
        "MODBUS_PORT": "502",
        "MODBUS_UNIT_ID": "1",
        "MODBUS_SIMULACION": "0",
        "MODBUS_START_COIL": "16",
        "MODBUS_PAUSE_COIL": "17",
        "MODBUS_COUNTER_REGISTER": "0",
        "MODBUS_COUNTER_WORDS": "2",
        "MODBUS_COUNTER_LITTLE_ENDIAN": "1",
        "MODBUS_POLL_MS": "500",
        "MODBUS_COUNTER_MAX_DELTA": "10000",
        "PULSO_DURACION_MS": "1000",
        "SEGURO_PARO_SEGUNDOS": "3",
        "PRIMERA_PIEZA_TIMEOUT_S": 900,
        "UPDATE_SOURCE": "",
        "tema": "claro",
    }


@pytest.fixture()
def config_zelio():
    """Config.json ya migrado al Zelio (no debe volver a tocarse)."""
    return {
        "MODBUS_HOST": config.IP_PLC_ZELIO,
        "MODBUS_CMD_MODE": "registro",
        "MODBUS_START_COIL": 0,
        "MODBUS_PAUSE_COIL": 1,
        "MODBUS_START_REGISTER": 16,
        "MODBUS_START_BIT": 0,
        "MODBUS_PAUSE_REGISTER": 16,
        "MODBUS_PAUSE_BIT": 1,
        "MODBUS_COUNTER_REGISTER": 20,
        "MODBUS_COUNTER_WORDS": 1,
        "MODBUS_COUNTER_LITTLE_ENDIAN": 1,
        "MODBUS_TOWER_REGISTER": 16,
        "MODBUS_TOWER_GREEN_BIT": 2,
        "MODBUS_TOWER_AMBER_BIT": 3,
        "MODBUS_TOWER_RED_BIT": 4,
        "MODBUS_TOWER_ALARM_BIT": 5,
        "MODBUS_TOWER_HEARTBEAT_REGISTER": 19,
        "MODBUS_TOWER_HEARTBEAT_BIT": 0,
        "PULSO_DURACION_MS": 300,
    }


@pytest.fixture()
def config_aplicable(tmp_path, monkeypatch):
    """Apunta la config.json a un temporal y aísla os.environ.

    `_aplicar_config_json` vuelca el archivo sobre el entorno con
    `setdefault`: una variable ya presente en el proceso gana (es el
    comportamiento de produccion). Para simular un proceso recien arrancado
    se quitan del entorno copiado las claves operativas que trae el
    archivo. `DB_PATH` y `LOG_DIR` se dejan como los pone el conftest
    (temporal), para que el test nunca toque la BD real.

    `os.environ` se reemplaza por una copia para que el test no contamine
    al resto de la suite ni al proceso.
    """
    ruta = str(tmp_path / "config.json")
    monkeypatch.setattr(config, "ruta_config_json", lambda: ruta)
    monkeypatch.setattr(config, "DIR_DATOS", str(tmp_path))

    entorno = dict(os.environ)
    for clave in list(entorno):
        if clave.startswith(("MODBUS_", "TORRE_", "EXPORT_", "UPDATE_",
                             "SEGURO_", "EASY_")):
            entorno.pop(clave)
    for clave in ("PULSO_DURACION_MS", "PRIMERA_PIEZA_TIMEOUT_S",
                  "BIOMETRICO_KIOSKO", "tema"):
        entorno.pop(clave, None)
    monkeypatch.setattr(os, "environ", entorno)
    return ruta


# ---------------------------------------------------------------------------
# Deteccion del perfil heredado
# ---------------------------------------------------------------------------

def test_detecta_config_advantech(config_advantech):
    assert config._es_config_advantech(config_advantech) is True


def test_no_detecta_config_ya_zelio(config_zelio):
    assert config._es_config_advantech(config_zelio) is False


def test_no_detecta_sin_host(config_advantech):
    """Sin MODBUS_HOST no se sabe contra que hardware se configuro."""
    config_advantech["MODBUS_HOST"] = ""
    assert config._es_config_advantech(config_advantech) is False


# ---------------------------------------------------------------------------
# Migracion
# ---------------------------------------------------------------------------

def test_migra_comandos_y_torre_al_mapa_measured(config_advantech):
    cambios = config._migrar_config_a_zelio(config_advantech)

    assert cambios, "la migracion debe reportar los cambios aplicados"
    # Comandos: bits de J1 (dir 16): bit0 marcha, bit1 paro.
    assert config_advantech["MODBUS_CMD_MODE"] == "registro"
    assert config_advantech["MODBUS_START_REGISTER"] == 16
    assert config_advantech["MODBUS_START_BIT"] == 0
    assert config_advantech["MODBUS_PAUSE_REGISTER"] == 16
    assert config_advantech["MODBUS_PAUSE_BIT"] == 1
    # Torre: misma palabra J1, bits 2-5.
    assert config_advantech["MODBUS_TOWER_REGISTER"] == 16
    assert config_advantech["MODBUS_TOWER_GREEN_BIT"] == 2
    assert config_advantech["MODBUS_TOWER_AMBER_BIT"] == 3
    assert config_advantech["MODBUS_TOWER_RED_BIT"] == 4
    assert config_advantech["MODBUS_TOWER_ALARM_BIT"] == 5
    # Heartbeat en J4 (dir 19).
    assert config_advantech["MODBUS_TOWER_HEARTBEAT_REGISTER"] == 19
    # Coils del modulo viejo: inertes en modo registro, pero se dejan en sus
    # defaults para que no queden como mapa engañoso.
    assert config_advantech["MODBUS_START_COIL"] == 0
    assert config_advantech["MODBUS_PAUSE_COIL"] == 1


def test_migra_contador_a_o1_de_16_bits(config_advantech):
    """O1 (dir 20) y UNA palabra: O2 es la palabra de pulsos, no la alta."""
    config._migrar_config_a_zelio(config_advantech)

    assert config_advantech["MODBUS_COUNTER_REGISTER"] == 20
    assert config_advantech["MODBUS_COUNTER_WORDS"] == 1
    assert str(config_advantech["MODBUS_COUNTER_LITTLE_ENDIAN"]) == "1"


def test_migra_la_ip_al_plc_zelio(config_advantech):
    config._migrar_config_a_zelio(config_advantech)
    assert config_advantech["MODBUS_HOST"] == config.IP_PLC_ZELIO


def test_migra_desactiva_simulacion(config_advantech):
    """Con la IP real del PLC, la app no debe quedarse simulando."""
    config_advantech["MODBUS_SIMULACION"] = "1"
    config._migrar_config_a_zelio(config_advantech)
    assert config_advantech["MODBUS_SIMULACION"] == 0


def test_migracion_no_toca_rutas_ni_resto(config_advantech):
    """Solo el mapa de hardware: rutas, exportacion, updates y seguros intactos."""
    antes = dict(config_advantech)
    config._migrar_config_a_zelio(config_advantech)

    for clave in ("DB_PATH", "LOG_DIR", "EXPORT_DIR_AUTO", "UPDATE_SOURCE",
                  "SEGURO_PARO_SEGUNDOS", "PRIMERA_PIEZA_TIMEOUT_S",
                  "BIOMETRICO_KIOSKO", "tema"):
        assert config_advantech[clave] == antes[clave], clave


def test_migracion_no_pisa_parametros_de_conexion(config_advantech):
    """Puerto, unit id, sondeo y delta maximo valen para cualquier hardware:
    si estan ajustados a mano, la migracion los deja como estan."""
    config_advantech["MODBUS_PORT"] = "1502"
    config_advantech["MODBUS_UNIT_ID"] = "3"
    config_advantech["MODBUS_POLL_MS"] = "1000"
    config_advantech["MODBUS_COUNTER_MAX_DELTA"] = "5000"

    config._migrar_config_a_zelio(config_advantech)

    assert config_advantech["MODBUS_PORT"] == "1502"
    assert config_advantech["MODBUS_UNIT_ID"] == "3"
    assert config_advantech["MODBUS_POLL_MS"] == "1000"
    assert config_advantech["MODBUS_COUNTER_MAX_DELTA"] == "5000"


def test_migracion_es_idempotente(config_advantech):
    config._migrar_config_a_zelio(config_advantech)
    despues = dict(config_advantech)

    cambios = config._migrar_config_a_zelio(config_advantech)

    assert cambios == []
    assert config_advantech == despues


def test_no_migra_config_ya_zelio(config_zelio):
    antes = dict(config_zelio)
    cambios = config._migrar_config_a_zelio(config_zelio)

    assert cambios == []
    assert config_zelio == antes


# ---------------------------------------------------------------------------
# Aplicacion al arrancar el exe
# ---------------------------------------------------------------------------

def test_aplicar_config_json_migra_y_persiste(config_advantech, config_aplicable):
    with open(config_aplicable, "w", encoding="utf-8") as f:
        json.dump(config_advantech, f)

    config._aplicar_config_json()

    with open(config_aplicable, "r", encoding="utf-8") as f:
        guardado = json.load(f)
    assert guardado["MODBUS_CMD_MODE"] == "registro"
    assert guardado["MODBUS_COUNTER_REGISTER"] == 20
    assert guardado["MODBUS_COUNTER_WORDS"] == 1
    assert guardado["MODBUS_HOST"] == config.IP_PLC_ZELIO
    # Las rutas siguen intactas.
    assert guardado["DB_PATH"] == config_advantech["DB_PATH"]
    assert guardado["LOG_DIR"] == config_advantech["LOG_DIR"]


def test_aplicar_config_json_siembra_claves_faltantes(config_aplicable):
    """Las claves que faltan se agregan con su default (comportamiento previo)."""
    with open(config_aplicable, "w", encoding="utf-8") as f:
        json.dump({"MODBUS_HOST": config.IP_PLC_ZELIO, "tema": "claro"}, f)

    config._aplicar_config_json()

    with open(config_aplicable, "r", encoding="utf-8") as f:
        guardado = json.load(f)
    assert guardado["MODBUS_CMD_MODE"] == "registro"
    assert guardado["MODBUS_COUNTER_REGISTER"] == 20
    assert guardado["PRIMERA_PIEZA_TIMEOUT_S"] == 900


def test_aplicar_config_json_no_pisa_valores_existentes(config_zelio, config_aplicable):
    """La siembra nunca pisa lo editado a mano."""
    config_zelio["MODBUS_COUNTER_REGISTER"] = 21  # valor a proposito
    config_zelio["MODBUS_CMD_MODE"] = "registro"
    with open(config_aplicable, "w", encoding="utf-8") as f:
        json.dump(config_zelio, f)

    config._aplicar_config_json()

    with open(config_aplicable, "r", encoding="utf-8") as f:
        guardado = json.load(f)
    assert guardado["MODBUS_COUNTER_REGISTER"] == 21


def test_aplicar_config_json_deja_el_mapa_zelio_en_el_entorno(
    config_advantech, config_aplicable
):
    """Lo migrado debe ser lo que lee el HAL (MODBUS_CONFIG), no el JSON."""
    with open(config_aplicable, "w", encoding="utf-8") as f:
        json.dump(config_advantech, f)

    config._aplicar_config_json()

    assert os.environ["MODBUS_CMD_MODE"] == "registro"
    assert os.environ["MODBUS_HOST"] == config.IP_PLC_ZELIO
    assert os.environ["MODBUS_COUNTER_REGISTER"] == "20"
    assert os.environ["MODBUS_COUNTER_WORDS"] == "1"

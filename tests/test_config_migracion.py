"""Migracion automatica de la configuracion heredada: claves MODBUS_* a PLC_*
y mapa del modulo Advantech al PLC Zelio (SR3 + SR3NET01BD).

El `config.json` de la carpeta de datos es la configuracion del .exe. La
siembra de `CONFIG_POR_DEFECTO` solo AGREGA claves faltantes (nunca pisa
valores editados a mano), asi que un config de una version anterior sobrevive
a la actualizacion de la app: puede conservar los nombres viejos `MODBUS_*` o
el mapa Advantech (coils 16/17, contador de 2 palabras en el registro 0 y sin
`PLC_CMD_MODE`). Ambos se migran solos al arrancar.

Estos tests fijan la conducta del renombrado (`_renombrar_claves_heredadas`),
de la migracion al Zelio (`_migrar_config_a_zelio`) y de su aplicacion al
arrancar el exe (`_aplicar_config_json`).

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
        "PLC_HOST": "192.168.1.20",
        "PLC_PORT": "502",
        "PLC_UNIT_ID": "1",
        "PLC_SIMULACION": "0",
        "PLC_START_COIL": "16",
        "PLC_PAUSE_COIL": "17",
        "PLC_COUNTER_REGISTER": "0",
        "PLC_COUNTER_WORDS": "2",
        "PLC_COUNTER_LITTLE_ENDIAN": "1",
        "PLC_POLL_MS": "500",
        "PLC_COUNTER_MAX_DELTA": "10000",
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
        "PLC_HOST": config.IP_PLC_ZELIO,
        "PLC_CMD_MODE": "registro",
        "PLC_START_COIL": 0,
        "PLC_PAUSE_COIL": 1,
        "PLC_START_REGISTER": 16,
        "PLC_START_BIT": 0,
        "PLC_PAUSE_REGISTER": 16,
        "PLC_PAUSE_BIT": 1,
        "PLC_COUNTER_REGISTER": 20,
        "PLC_COUNTER_WORDS": 1,
        "PLC_COUNTER_LITTLE_ENDIAN": 1,
        "PLC_TOWER_REGISTER": 16,
        "PLC_TOWER_GREEN_BIT": 2,
        "PLC_TOWER_AMBER_BIT": 3,
        "PLC_TOWER_RED_BIT": 4,
        "PLC_TOWER_ALARM_BIT": 5,
        "PLC_TOWER_HEARTBEAT_REGISTER": 19,
        "PLC_TOWER_HEARTBEAT_BIT": 0,
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
        if clave.startswith(("PLC_", "MODBUS_", "TORRE_", "EXPORT_",
                             "UPDATE_", "SEGURO_", "EASY_")):
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
    """Sin PLC_HOST no se sabe contra que hardware se configuro."""
    config_advantech["PLC_HOST"] = ""
    assert config._es_config_advantech(config_advantech) is False


# ---------------------------------------------------------------------------
# Migracion
# ---------------------------------------------------------------------------

def test_migra_comandos_y_torre_al_mapa_measured(config_advantech):
    cambios = config._migrar_config_a_zelio(config_advantech)

    assert cambios, "la migracion debe reportar los cambios aplicados"
    # Comandos: bits de J1 (dir 16): bit0 marcha, bit1 paro.
    assert config_advantech["PLC_CMD_MODE"] == "registro"
    assert config_advantech["PLC_START_REGISTER"] == 16
    assert config_advantech["PLC_START_BIT"] == 0
    assert config_advantech["PLC_PAUSE_REGISTER"] == 16
    assert config_advantech["PLC_PAUSE_BIT"] == 1
    # Torre: misma palabra J1, bits 2-5.
    assert config_advantech["PLC_TOWER_REGISTER"] == 16
    assert config_advantech["PLC_TOWER_GREEN_BIT"] == 2
    assert config_advantech["PLC_TOWER_AMBER_BIT"] == 3
    assert config_advantech["PLC_TOWER_RED_BIT"] == 4
    assert config_advantech["PLC_TOWER_ALARM_BIT"] == 5
    # Heartbeat en J4 (dir 19).
    assert config_advantech["PLC_TOWER_HEARTBEAT_REGISTER"] == 19
    # Coils del modulo viejo: inertes en modo registro, pero se dejan en sus
    # defaults para que no queden como mapa engañoso.
    assert config_advantech["PLC_START_COIL"] == 0
    assert config_advantech["PLC_PAUSE_COIL"] == 1


def test_migra_contador_a_o1_de_16_bits(config_advantech):
    """O1 (dir 20) y UNA palabra: O2 es la palabra de pulsos, no la alta."""
    config._migrar_config_a_zelio(config_advantech)

    assert config_advantech["PLC_COUNTER_REGISTER"] == 20
    assert config_advantech["PLC_COUNTER_WORDS"] == 1
    assert str(config_advantech["PLC_COUNTER_LITTLE_ENDIAN"]) == "1"


def test_migra_la_ip_al_plc_zelio(config_advantech):
    config._migrar_config_a_zelio(config_advantech)
    assert config_advantech["PLC_HOST"] == config.IP_PLC_ZELIO


def test_migra_desactiva_simulacion(config_advantech):
    """Con la IP real del PLC, la app no debe quedarse simulando."""
    config_advantech["PLC_SIMULACION"] = "1"
    config._migrar_config_a_zelio(config_advantech)
    assert config_advantech["PLC_SIMULACION"] == 0


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
    config_advantech["PLC_PORT"] = "1502"
    config_advantech["PLC_UNIT_ID"] = "3"
    config_advantech["PLC_POLL_MS"] = "1000"
    config_advantech["PLC_COUNTER_MAX_DELTA"] = "5000"

    config._migrar_config_a_zelio(config_advantech)

    assert config_advantech["PLC_PORT"] == "1502"
    assert config_advantech["PLC_UNIT_ID"] == "3"
    assert config_advantech["PLC_POLL_MS"] == "1000"
    assert config_advantech["PLC_COUNTER_MAX_DELTA"] == "5000"


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
# Renombrado de claves MODBUS_* -> PLC_*
# ---------------------------------------------------------------------------

def test_renombra_claves_de_config_heredado():
    datos = {
        "MODBUS_HOST": "10.0.0.9",
        "MODBUS_POLL_MS": "250",
        "MODBUS_SIMULACION": "1",
        "tema": "oscuro",
    }

    cambios = config._renombrar_claves_heredadas(datos)

    assert datos["PLC_HOST"] == "10.0.0.9"
    assert datos["PLC_POLL_MS"] == "250"
    assert datos["PLC_SIMULACION"] == "1"
    assert datos["tema"] == "oscuro"
    assert not [c for c in datos if c.startswith("MODBUS_")]
    assert len(cambios) == 3


def test_la_clave_nueva_gana_sobre_la_vieja():
    datos = {"MODBUS_HOST": "10.0.0.9", "PLC_HOST": "10.0.0.10"}

    config._renombrar_claves_heredadas(datos)

    assert datos == {"PLC_HOST": "10.0.0.10"}


def test_renombra_el_entorno_heredado(monkeypatch):
    entorno = {"MODBUS_HOST": "10.0.0.9", "MODBUS_POLL_MS": "250"}
    monkeypatch.setattr(os, "environ", entorno)

    cambios = config._renombrar_entorno_heredado()

    assert entorno["PLC_HOST"] == "10.0.0.9"
    assert entorno["PLC_POLL_MS"] == "250"
    assert len(cambios) == 2


def test_aplicar_config_json_renombra_y_persiste(config_aplicable):
    """Un config.json con las claves viejas MODBUS_* se migra solo."""
    with open(config_aplicable, "w", encoding="utf-8") as f:
        json.dump({
            "MODBUS_HOST": config.IP_PLC_ZELIO,
            "MODBUS_CMD_MODE": "registro",
        }, f)

    config._aplicar_config_json()

    with open(config_aplicable, "r", encoding="utf-8") as f:
        guardado = json.load(f)
    assert guardado["PLC_HOST"] == config.IP_PLC_ZELIO
    assert guardado["PLC_CMD_MODE"] == "registro"
    assert "MODBUS_HOST" not in guardado
    assert "MODBUS_CMD_MODE" not in guardado
    assert os.environ["PLC_HOST"] == config.IP_PLC_ZELIO


# ---------------------------------------------------------------------------
# Aplicacion al arrancar el exe
# ---------------------------------------------------------------------------

def test_aplicar_config_json_migra_y_persiste(config_advantech, config_aplicable):
    with open(config_aplicable, "w", encoding="utf-8") as f:
        json.dump(config_advantech, f)

    config._aplicar_config_json()

    with open(config_aplicable, "r", encoding="utf-8") as f:
        guardado = json.load(f)
    assert guardado["PLC_CMD_MODE"] == "registro"
    assert guardado["PLC_COUNTER_REGISTER"] == 20
    assert guardado["PLC_COUNTER_WORDS"] == 1
    assert guardado["PLC_HOST"] == config.IP_PLC_ZELIO
    # Las rutas siguen intactas.
    assert guardado["DB_PATH"] == config_advantech["DB_PATH"]
    assert guardado["LOG_DIR"] == config_advantech["LOG_DIR"]


def test_aplicar_config_json_siembra_claves_faltantes(config_aplicable):
    """Las claves que faltan se agregan con su default (comportamiento previo)."""
    with open(config_aplicable, "w", encoding="utf-8") as f:
        json.dump({"PLC_HOST": config.IP_PLC_ZELIO, "tema": "claro"}, f)

    config._aplicar_config_json()

    with open(config_aplicable, "r", encoding="utf-8") as f:
        guardado = json.load(f)
    assert guardado["PLC_CMD_MODE"] == "registro"
    assert guardado["PLC_COUNTER_REGISTER"] == 20
    assert guardado["PRIMERA_PIEZA_TIMEOUT_S"] == 900


def test_aplicar_config_json_no_pisa_valores_existentes(config_zelio, config_aplicable):
    """La siembra nunca pisa lo editado a mano."""
    config_zelio["PLC_COUNTER_REGISTER"] = 21  # valor a proposito
    config_zelio["PLC_CMD_MODE"] = "registro"
    with open(config_aplicable, "w", encoding="utf-8") as f:
        json.dump(config_zelio, f)

    config._aplicar_config_json()

    with open(config_aplicable, "r", encoding="utf-8") as f:
        guardado = json.load(f)
    assert guardado["PLC_COUNTER_REGISTER"] == 21


def test_aplicar_config_json_deja_el_mapa_zelio_en_el_entorno(
    config_advantech, config_aplicable
):
    """Lo migrado debe ser lo que lee el HAL (PLC_CONFIG), no el JSON."""
    with open(config_aplicable, "w", encoding="utf-8") as f:
        json.dump(config_advantech, f)

    config._aplicar_config_json()

    assert os.environ["PLC_CMD_MODE"] == "registro"
    assert os.environ["PLC_HOST"] == config.IP_PLC_ZELIO
    assert os.environ["PLC_COUNTER_REGISTER"] == "20"
    assert os.environ["PLC_COUNTER_WORDS"] == "1"

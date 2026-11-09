"""
test_simulador_plc.py - El emulador de PLC (`test/simulador_plc.py`) sirve de
verdad y la app (HAL) se conecta a el.

Regresion del interbloqueo: el emulador envolvia las llamadas a DataBank
(`set_holding_registers`/`get_holding_registers`) con `_h_regs_lock`, que
NO es reentrante y que esos metodos ya toman por dentro. Resultado: el
emulador se quedaba bloqueado en el primer corte, el servidor Modbus dejaba
de responder y la app lo veia "PLC sin conexion".

El emulador es un script MANUAL de `test/`, asi que aqui se carga por ruta
(NO se importa como modulo de pytest) y se ejercita como servidor real.
"""

import importlib.util
import os
import socket
import threading
import time

import pytest
from pyModbusTCP.server import ModbusServer

from src.hardware import plc_controller as mod

RUTA_SIMULADOR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "test",
    "simulador_plc.py",
)

O_CONTADOR = 20   # O1XT1


@pytest.fixture(scope="module")
def simulador():
    """Carga `test/simulador_plc.py` como modulo (script manual de planta)."""
    spec = importlib.util.spec_from_file_location(
        "simulador_plc_bajo_prueba", RUTA_SIMULADOR
    )
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def _puerto_libre():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _banco(simulador, velocidad=0.0, inicial=0):
    return simulador.BancoZelioPLC(
        dir_contador=O_CONTADOR, inicial=inicial, velocidad=velocidad
    )


def _servidor(banco, puerto):
    srv = ModbusServer(host="127.0.0.1", port=puerto, no_block=True,
                        data_bank=banco)
    srv.start()
    time.sleep(0.1)
    return srv


def _config_hal(puerto, **extra):
    """Config del HAL con el mapa MEDIDO del Zelio (no depende del .env)."""
    cfg = {
        "host": "127.0.0.1",
        "port": puerto,
        "unit_id": 1,
        "timeout": 2.0,
        "cmd_mode": "registro",
        "start_register": 16,
        "start_bit": 0,
        "pause_register": 16,
        "pause_bit": 1,
        "counter_register": O_CONTADOR,
        "counter_words": 1,
        "counter_little_endian": True,
        "poll_ms": 100,
        "pulso_duracion_ms": 50,
        "max_delta": 10000,
        "modo_simulacion": False,
        "start_coil_invertido": False,
        "pause_coil_invertido": False,
        "tower_register": 16,
        "tower_heartbeat_register": 19,
        "tower_green_bit": 2,
        "tower_amber_bit": 3,
        "tower_red_bit": 4,
        "tower_alarm_bit": 5,
        "tower_heartbeat_bit": 0,
        "tower_hb_ms": 500,
    }
    cfg.update(extra)
    return cfg


def _correr_con_timeout(funcion, timeout=3.0):
    """Ejecuta `funcion` en un hilo y devuelve si termino a tiempo."""
    hilo = threading.Thread(target=funcion, daemon=True)
    hilo.start()
    hilo.join(timeout)
    return not hilo.is_alive()


def _esperar_conexion(ctrl, timeout=5.0):
    """El HAL se enlaza desde su hilo de polling: se espera a que conecte."""
    fin = time.time() + timeout
    while time.time() < fin:
        if ctrl.conectado():
            return True
        time.sleep(0.05)
    return ctrl.conectado()


def test_el_emulador_no_se_interbloquea_al_contar(simulador):
    """Contar, resetear e imprimir el estado NO deben quedar colgados."""
    banco = _banco(simulador)

    assert _correr_con_timeout(lambda: banco.sumar_cortes(1)) is True
    assert banco.get_holding_registers(O_CONTADOR, 1) == [1]
    # O2 es la palabra de PULSO: se enciende con el corte.
    assert banco.get_holding_registers(O_CONTADOR + 1, 1) == [1]

    assert _correr_con_timeout(lambda: banco.resetear_contador()) is True
    assert banco.get_holding_registers(O_CONTADOR, 1) == [0]

    assert _correr_con_timeout(lambda: banco.imprimir_estado()) is True


def test_el_contador_automatico_no_deja_colgado_el_servidor(simulador):
    """Con el auto-conteo activo el servidor sigue respondiendo."""
    banco = _banco(simulador, velocidad=5.0)
    puerto = _puerto_libre()
    srv = _servidor(banco, puerto)
    banco.iniciar()
    try:
        ctrl = mod.PLCController(_config_hal(puerto))
        try:
            assert _esperar_conexion(ctrl) is True
            # El auto-conteo ya debe haber movido el contador del emulador.
            fin = time.time() + 3.0
            while time.time() < fin and ctrl.cortes_totales() == 0:
                time.sleep(0.05)
            assert ctrl.cortes_totales() > 0
            # Y el enlace sigue vivo (antes se caia al primer corte).
            assert ctrl.conectado() is True
        finally:
            ctrl.cleanup()
    finally:
        banco.detener()
        srv.stop()


def test_la_app_conecta_al_emulador_y_cuenta_los_cortes(simulador):
    """El HAL real se enlaza al emulador y acumula los cortes de O1."""
    banco = _banco(simulador)
    puerto = _puerto_libre()
    srv = _servidor(banco, puerto)
    try:
        ctrl = mod.PLCController(_config_hal(puerto))
        try:
            assert _esperar_conexion(ctrl) is True
            assert ctrl.cortes_totales() == 0

            banco.sumar_cortes(3)
            fin = time.time() + 3.0
            while time.time() < fin and ctrl.cortes_totales() < 3:
                time.sleep(0.05)
            assert ctrl.cortes_totales() == 3
        finally:
            ctrl.cleanup()
    finally:
        srv.stop()


def test_la_marcha_y_el_paro_llegan_al_emulador(simulador):
    """MARCHA suelta el latch de PARO y pulsa START en J1 (dir 16)."""
    banco = _banco(simulador)
    puerto = _puerto_libre()
    srv = _servidor(banco, puerto)
    try:
        ctrl = mod.PLCController(_config_hal(puerto))
        try:
            assert _esperar_conexion(ctrl) is True
            # Al conectar, el HAL latchea el PARO (J1 bit1).
            assert ctrl._reg_j.get(16, 0) & 0x02

            ctrl.maquina_lista()
            # El emulador debe ver el pulso de START (bit0) y el PARO
            # liberado (bit1 = 0) al terminar la secuencia.
            fin = time.time() + 3.0
            visto_pulso = False
            while time.time() < fin:
                palabra = banco.get_holding_registers(16, 1)[0]
                if palabra & 0x01:
                    visto_pulso = True
                elif visto_pulso:
                    break
                time.sleep(0.01)
            assert visto_pulso is True
            palabra = banco.get_holding_registers(16, 1)[0]
            assert palabra & 0x01 == 0   # el pulso ya termino
            assert palabra & 0x02 == 0   # el latch de PARO quedo soltado
        finally:
            ctrl.cleanup()
    finally:
        srv.stop()


def test_torre_roja_y_buzzer_con_la_maquina_encendida(simulador):
    """Modo PARO con zona 'maquina encendida': la maquina SIGUE en marcha y,
    al vencer la tolerancia, la torre va a ROJA (Q5) + alarma (Q6).

    Es el caso que fallaba: la roja exigia la maquina detenida, asi que en
    los paros donde la maquina debe seguir encendida nunca llegaba.
    """
    from src.gui.modulos.corte.inicio_view import InicioView

    banco = _banco(simulador)
    puerto = _puerto_libre()
    srv = _servidor(banco, puerto)
    try:
        ctrl = mod.PLCController(_config_hal(puerto))
        try:
            assert _esperar_conexion(ctrl) is True
            ctrl.maquina_lista()
            time.sleep(0.3)
            assert ctrl.maquina_detenida() is False   # maquina EN MARCHA

            vista = InicioView.__new__(InicioView)
            vista.controlador = ctrl
            vista.sesion_id = 1
            vista._modo_mantenimiento = False
            vista._modo_paro = True
            vista._primera_pieza = False
            vista._en_paro = True
            vista._paro_inicio_momento = time.time() - 120
            vista._ultimo_color_rojo = None

            assert vista._estado_torre() == (False, False, True)
            vista._actualizar_torre()

            # Q5 (roja) encendida y Q6 (alarma) parpadeando durante la
            # ventana de 3 s.
            fin = time.time() + 3.0
            vista_roja = False
            alarma = False
            while time.time() < fin:
                palabra = banco.get_holding_registers(16, 1)[0]
                vista_roja = vista_roja or bool(palabra & 0x10)
                alarma = alarma or bool(palabra & 0x20)
                if vista_roja and alarma:
                    break
                time.sleep(0.02)
            assert vista_roja is True
            assert alarma is True
        finally:
            ctrl.cleanup()
    finally:
        srv.stop()

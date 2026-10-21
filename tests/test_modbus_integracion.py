"""
test_modbus_integracion.py - Prueba de extremo a extremo del HAL de Modbus
contra un servidor Modbus TCP real (emulado dentro del test).

Comprueba que el modo "registro" (Zelio SR3NET01BD) habla el protocolo de
verdad por el socket:

    - FC06 (write_single_register) hacia las palabras J (16-19).
    - FC03 (read_holding_registers) hacia las palabras O (20-23).

A diferencia de `test_modbus_hal.py` (que inyecta un cliente falso), aqui
las escrituras viajan por la red y las registra el servidor.
"""

import socket
import time

import pytest
from pyModbusTCP.server import DataBank, ModbusServer

from src.hardware import modbus_controller as mod

J_START = 16   # J1XT1
J_PAUSE = 17   # J2XT1
O_CONTADOR = 20  # O1XT1


class BancoZelio(DataBank):
    """DataBank que registra lo que escribe el master."""

    def __init__(self):
        super().__init__()
        self.escrituras = []

    def on_coils_change(self, address, from_value, to_value, srv_info):
        self.escrituras.append(("coil", address, bool(to_value)))

    def on_holding_registers_change(self, address, from_value, to_value,
                                    srv_info):
        self.escrituras.append(("registro", address, to_value))


def _puerto_libre():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def servidor():
    """Servidor Modbus TCP en un puerto libre."""
    banco = BancoZelio()
    puerto = _puerto_libre()
    srv = ModbusServer(host="127.0.0.1", port=puerto, no_block=True,
                        data_bank=banco)
    srv.start()
    time.sleep(0.1)
    try:
        yield banco, puerto
    finally:
        srv.stop()


def _controlador(puerto, **extra):
    cfg = {
        "host": "127.0.0.1",
        "port": puerto,
        "unit_id": 1,
        "timeout": 2.0,
        "cmd_mode": "registro",
        "start_register": J_START,
        "start_bit": 0,
        "pause_register": J_PAUSE,
        "pause_bit": 0,
        "counter_register": O_CONTADOR,
        "counter_words": 2,
        "counter_little_endian": True,
        "poll_ms": 200,
        "pulso_duracion_ms": 50,
        "max_delta": 10000,
        "modo_simulacion": False,
        "start_coil_invertido": False,
        "pause_coil_invertido": False,
    }
    cfg.update(extra)
    return mod.ModbusController(cfg, iniciar_polling=False)


def _esperar(condicion, timeout=3.0):
    fin = time.time() + timeout
    while time.time() < fin:
        if condicion():
            return True
        time.sleep(0.01)
    return False


def test_el_hal_escribe_en_las_palabras_J_por_el_socket(servidor):
    """MARCHA: suelta el PARO y pulsa el START en las palabras J."""
    banco, puerto = servidor
    ctrl = _controlador(puerto)

    assert ctrl._conectar() is True
    # Al conectar, el PARO queda latched (J2 = 1).
    assert ("registro", J_PAUSE, 1) in banco.escrituras
    banco.escrituras.clear()

    ctrl.maquina_lista()
    assert _esperar(lambda: len(banco.escrituras) >= 3)

    assert banco.escrituras == [
        ("registro", J_PAUSE, 0),   # suelta el latch de PARO
        ("registro", J_START, 1),   # pulso de MARCHA
        ("registro", J_START, 0),   # vuelve a reposo
    ]
    ctrl.cleanup()


def test_el_contador_se_lee_de_las_palabras_O(servidor):
    """El contador del PLC llega por O1/O2 y la PC acumula los deltas."""
    banco, puerto = servidor
    banco.set_holding_registers(O_CONTADOR, [7, 0])
    ctrl = _controlador(puerto)

    assert ctrl._conectar() is True
    assert ctrl.cortes_totales() == 0   # la lectura inicial es la linea base

    banco.set_holding_registers(O_CONTADOR, [10, 0])
    ctrl._poll_contador()

    assert ctrl.cortes_totales() == 3
    ctrl.cleanup()


def test_el_cierre_de_la_app_asegura_el_paro(servidor):
    """Al cerrar la app, el PARO se latchea otra vez por el socket.

    Se arranca primero (soltando el latch de PARO) para que el cierre
    implique un cambio real de la palabra J2.
    """
    banco, puerto = servidor
    ctrl = _controlador(puerto)
    ctrl._conectar()
    ctrl.maquina_lista()
    assert _esperar(lambda: ("registro", J_PAUSE, 0) in banco.escrituras)
    banco.escrituras.clear()

    ctrl.cleanup()

    assert ("registro", J_PAUSE, 1) in banco.escrituras

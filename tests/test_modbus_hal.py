"""
test_modbus_hal.py - Pruebas del HAL de Modbus (ModbusController).

Cubren los DOS modos de comando del controlador:

    - "coil"     : modulo Advantech (FC05, coils). Comportamiento original.
    - "registro" : Zelio Logic 2 SR3 + modulo Ethernet SR3NET01BD (FC06). El
                   NET01BD no expone coils: START y PAUSE son bits dentro
                   de las palabras J (16-19), y el contador se lee de las
                   palabras O (20-23).

No tocan hardware: se inyecta un cliente Modbus falso que registra las
escrituras.
"""

import time

import pytest

from src.hardware import modbus_controller as mod


class ClienteFalso:
    """Cliente Modbus en memoria: registra escrituras y sirve lecturas."""

    def __init__(self, *args, **kwargs):
        self.escrituras = []      # ("coil"|"registro", direccion, valor)
        self.lecturas = []        # (direccion, cantidad)
        self.registros = {}       # direccion -> valor (para las lecturas)
        self.cerrado = False

    def read_holding_registers(self, reg_addr, reg_nb=1):
        self.lecturas.append((reg_addr, reg_nb))
        return [self.registros.get(reg_addr + i, 0) for i in range(reg_nb)]

    def write_single_coil(self, bit_addr, bit_value):
        self.escrituras.append(("coil", bit_addr, bool(bit_value)))
        return True

    def write_single_register(self, reg_addr, reg_value):
        self.escrituras.append(("registro", reg_addr, reg_value))
        return True

    def close(self):
        self.cerrado = True


def _controlador(monkeypatch, **extra):
    """Crea un ModbusController con cliente falso y sin hilo de polling."""
    cliente = ClienteFalso()
    monkeypatch.setattr(mod, "ModbusClient", lambda *a, **k: cliente)
    cfg = {
        "host": "10.0.0.1",
        "port": 502,
        "unit_id": 1,
        "timeout": 2.0,
        "cmd_mode": "registro",
        "start_coil": 16,
        "pause_coil": 17,
        "start_register": 16,
        "start_bit": 0,
        # MEDIDO en el PLC real: un solo word de comando (dir 16) con
        # bit0=marcha, bit1=paro, bit2..5=torre.
        "pause_register": 16,
        "pause_bit": 1,
        "tower_register": 16,
        "tower_green_bit": 2,
        "tower_amber_bit": 3,
        "tower_red_bit": 4,
        "tower_alarm_bit": 5,
        "tower_heartbeat_register": 19,
        "counter_register": 20,
        "counter_words": 2,
        "counter_little_endian": True,
        "poll_ms": 500,
        "pulso_duracion_ms": 10,
        "max_delta": 10000,
        "modo_simulacion": False,
        "start_coil_invertido": False,
        "pause_coil_invertido": False,
    }
    cfg.update(extra)
    return mod.ModbusController(cfg, iniciar_polling=False), cliente


def _esperar(condicion, timeout=2.0):
    """Espera a que se cumpla la condicion (las acciones van en hilo)."""
    fin = time.time() + timeout
    while time.time() < fin:
        if condicion():
            return True
        time.sleep(0.01)
    return False


# ----------------------------------------------------------------------
# Modo "registro" (Zelio SR3NET01BD)
# ----------------------------------------------------------------------

def test_paro_inicial_latchea_la_palabra_de_pausa(monkeypatch):
    """Al establecer el enlace, el PARO queda latched (J1 bit1 = 1)."""
    ctrl, cliente = _controlador(monkeypatch)
    ctrl._conectar()

    assert cliente.escrituras == [("registro", 16, 0b10)]
    assert ctrl.conectado()


def test_marcha_suelta_el_paro_y_luego_pulsa_el_start(monkeypatch):
    """Orden obligatorio: PARO a reposo, luego pulso de START (y vuelta)."""
    ctrl, cliente = _controlador(monkeypatch)
    ctrl._conectar()
    cliente.escrituras.clear()

    ctrl.maquina_lista()
    assert _esperar(lambda: len(cliente.escrituras) >= 3)

    assert cliente.escrituras == [
        ("registro", 16, 0),   # suelta el latch de PARO
        ("registro", 16, 1),   # pulso de MARCHA
        ("registro", 16, 0),   # vuelve a reposo
    ]


def test_paro_queda_latcheado_hasta_reanudar(monkeypatch):
    """El PARO es sostenido: la palabra de pausa queda con el bit a 1."""
    ctrl, cliente = _controlador(monkeypatch)
    ctrl._conectar()
    cliente.escrituras.clear()

    ctrl.maquina_pausada()
    assert _esperar(lambda: cliente.escrituras)

    assert ("registro", 16, 0b10) in cliente.escrituras


def test_cierre_de_la_app_asegura_el_paro(monkeypatch):
    """Al cerrar la app con la maquina arrancada, el PARO se vuelve a
    latchear: la maquina no queda cortando sin supervision."""
    ctrl, cliente = _controlador(monkeypatch)
    ctrl._conectar()
    ctrl.maquina_lista()
    assert _esperar(lambda: len(cliente.escrituras) >= 3)
    cliente.escrituras.clear()

    ctrl.cleanup()

    assert any(e[:2] == ("registro", 16) and e[2] & 0b10
               for e in cliente.escrituras), (
        "el cierre debe dejar el bit de PARO en 1"
    )


def test_start_y_pause_pueden_compartir_palabra(monkeypatch):
    """Con START y PAUSE en la misma palabra J, los bits no se pisan."""
    ctrl, cliente = _controlador(
        monkeypatch, start_register=16, start_bit=0,
        pause_register=16, pause_bit=1,
    )
    ctrl._conectar()
    # Al conectar se latchea el PARO: 0b10 (solo el bit de PAUSE).
    assert cliente.escrituras[0] == ("registro", 16, 2)
    cliente.escrituras.clear()

    ctrl.maquina_lista()
    assert _esperar(lambda: len(cliente.escrituras) >= 3)

    # Al arrancar: se suelta PAUSE (0b00) y se pulsa START (0b01).
    assert cliente.escrituras[0] == ("registro", 16, 0)
    assert cliente.escrituras[1] == ("registro", 16, 1)
    assert cliente.escrituras[2] == ("registro", 16, 0)


def test_el_paro_inicial_no_pisa_una_marcha_ya_ordenada(monkeypatch):
    """Carrera real (medida en el PLC): si el operador pulsa MARCHA antes de
    que se establezca el enlace, el latch de PARO inicial NO debe pisar esa
    orden, o la maquina se queda detenida.

    La secuencia de MARCHA se conecta ella misma si no hay enlace."""
    ctrl, cliente = _controlador(monkeypatch)

    ctrl.maquina_lista()   # MARCHA antes de que haya conexion
    assert _esperar(lambda: len(cliente.escrituras) >= 3)

    # Ni latch de PARO (bit1 = 1) ni MARCHA perdida: se conecto y arranco.
    assert ("registro", 16, 0b10) not in cliente.escrituras
    assert cliente.escrituras == [
        ("registro", 16, 0),   # suelta el latch de PARO
        ("registro", 16, 1),   # pulso de MARCHA
        ("registro", 16, 0),   # vuelve a reposo
    ]
    assert ctrl.conectado()


def test_contador_se_lee_de_las_palabras_O(monkeypatch):
    """El contador del PLC llega por las palabras O (dir 20-23) y la PC
    acumula la diferencia entre sondeos.

    La primera lectura (al conectar) es solo la LINEA BASE del contador de
    la maquina: no se suma al conteo de la sesion, por eso el total arranca
    en 0 y lo que se acumula son los deltas.
    """
    ctrl, cliente = _controlador(monkeypatch)
    cliente.registros[20] = 100
    cliente.registros[21] = 0
    ctrl._conectar()

    assert cliente.lecturas[0] == (20, 2)
    assert ctrl.cortes_totales() == 0

    # El PLC avanza 7 cortes (palabra baja 107).
    cliente.registros[20] = 107
    ctrl._poll_contador()

    assert ctrl.cortes_totales() == 7


def test_contador_de_32_bits_usa_palabra_baja_primero(monkeypatch):
    """Con 2 palabras (O1/O2), el valor se arma con la palabra baja primero
    (MODBUS_COUNTER_LITTLE_ENDIAN=1)."""
    ctrl, cliente = _controlador(monkeypatch)
    cliente.registros[20] = 5      # palabra baja
    cliente.registros[21] = 2      # palabra alta
    ctrl._conectar()
    ctrl._poll_contador()           # sin cambios: delta 0

    assert ctrl.cortes_totales() == 0

    # La palabra BAJA avanza 7 (5 -> 12). Con little-endian el delta es 7;
    # con big-endian el salto seria 458752 y el modulo lo descartaria.
    cliente.registros[20] = 12
    ctrl._poll_contador()

    assert ctrl.cortes_totales() == 7


def test_contador_de_16_bits_ignora_la_palabra_alta_inestable(monkeypatch):
    """MEDIDO en el PLC real (SR3NET01BD): el contador esta en O1 y es de 16
    bits. O2 NO es la palabra alta del contador: es la palabra de PULSOS
    del PLC (se enciende un instante en cada corte y se apaga solo).

    Con MODBUS_COUNTER_WORDS=1 el HAL lee SOLO O1, de modo que el pulso de
    O2 no corrompe el valor: no se pierde el corte ni se cuela un salto de
    +65536 (que el modulo descartaria por anomalo).
    """
    ctrl, cliente = _controlador(monkeypatch, counter_words=1)
    cliente.registros[20] = 13
    cliente.registros[21] = 0
    ctrl._conectar()

    # El PLC publica el corte siguiente y pulsa O2 en el mismo instante.
    cliente.registros[20] = 14
    cliente.registros[21] = 1
    ctrl._poll_contador()

    assert ctrl.cortes_totales() == 1

    # La lectura siguiente (O2 ya de vuelta a 0) no inventa cortes.
    cliente.registros[21] = 0
    ctrl._poll_contador()

    assert ctrl.cortes_totales() == 1


def test_contador_de_16_bits_gestiona_el_wraparound(monkeypatch):
    """Con 16 bits, al pasar de 65535 a 0 el delta es 1 (wraparound), no un
    salto anomalo que el modulo descartaria."""
    ctrl, cliente = _controlador(monkeypatch, counter_words=1)
    cliente.registros[20] = 65535
    ctrl._conectar()

    cliente.registros[20] = 0
    ctrl._poll_contador()

    assert ctrl.cortes_totales() == 1


def test_polaridad_invertida_invierte_el_bit(monkeypatch):
    """Con polaridad invertida (logica NC), la accion es el bit a 0."""
    ctrl, cliente = _controlador(
        monkeypatch, start_coil_invertido=True, pause_coil_invertido=True,
    )
    ctrl._conectar()
    cliente.escrituras.clear()

    ctrl.maquina_pausada()
    assert _esperar(lambda: cliente.escrituras)

    # Invertido: "paro" = bit de PAUSE a 0, "reposo" = bit a 1.
    escrituras = [e for e in cliente.escrituras if e[:2] == ("registro", 16)]
    assert escrituras, "el paro debe escribir la palabra de comando"
    assert escrituras[-1][2] & 0b10 == 0


# ----------------------------------------------------------------------
# Modo "coil" (modulo Advantech) - no debe cambiar de comportamiento
# ----------------------------------------------------------------------

def test_modo_coil_conserva_el_comportamiento(monkeypatch):
    """En modo coil se sigue usando write_single_coil (FC05)."""
    ctrl, cliente = _controlador(monkeypatch, cmd_mode="coil")
    ctrl._conectar()
    cliente.escrituras.clear()

    ctrl.maquina_pausada()
    assert _esperar(lambda: cliente.escrituras)

    assert ("coil", 17, True) in cliente.escrituras
    assert not any(e[0] == "registro" for e in cliente.escrituras)


def test_modo_coil_pulsa_el_start_como_coil(monkeypatch):
    ctrl, cliente = _controlador(monkeypatch, cmd_mode="coil")
    ctrl._conectar()
    cliente.escrituras.clear()

    ctrl.maquina_lista()
    assert _esperar(lambda: len(cliente.escrituras) >= 3)

    assert ("coil", 17, False) in cliente.escrituras   # suelta el PARO
    assert ("coil", 16, True) in cliente.escrituras    # pulso de MARCHA
    assert ("coil", 16, False) in cliente.escrituras   # reposo


# ----------------------------------------------------------------------
# Contrato comun (lo que consume la GUI)
# ----------------------------------------------------------------------

def test_reanudar_reutiliza_el_mismo_pulso_de_marcha(monkeypatch):
    ctrl, cliente = _controlador(monkeypatch)
    ctrl._conectar()
    ctrl.maquina_pausada()
    assert _esperar(lambda: cliente.escrituras)
    cliente.escrituras.clear()

    ctrl.reprisar_maquina()
    assert _esperar(lambda: len(cliente.escrituras) >= 3)

    assert ("registro", 16, 1) in cliente.escrituras
    assert ctrl.maquina_detenida() is False


def test_modo_simulacion_no_toca_la_red(monkeypatch):
    """Sin host, el controlador queda en simulacion y no escribe nada."""
    cliente = ClienteFalso()
    monkeypatch.setattr(mod, "ModbusClient", lambda *a, **k: cliente)
    ctrl = mod.ModbusController(
        {"host": "", "modo_simulacion": True, "cmd_mode": "registro"},
        iniciar_polling=False,
    )

    ctrl.maquina_lista()
    ctrl.maquina_pausada()
    time.sleep(0.05)

    assert cliente.escrituras == []
    assert ctrl.en_simulacion() is True


@pytest.mark.parametrize("modo", ["coil", "registro"])
def test_cleanup_es_idempotente(monkeypatch, modo):
    ctrl, cliente = _controlador(monkeypatch, cmd_mode=modo)
    ctrl._conectar()

    ctrl.cleanup()
    ctrl.cleanup()

    assert ctrl.conectado() is False


# ----------------------------------------------------------------------
# Torre de luces (J1, bits 2..5) y heartbeat (J4)
# ----------------------------------------------------------------------

def test_torre_escribe_los_tres_bits_en_la_misma_palabra(monkeypatch):
    """Verde/ambar/roja viven en J1 (dir 16): una escritura por cambio.

    La palabra conserva el latch de PARO (bit1), que se activa al conectar.
    """
    ctrl, cliente = _controlador(monkeypatch)
    ctrl._conectar()
    cliente.escrituras.clear()

    ctrl.establecer_torre(True, False, False)
    assert cliente.escrituras == [("registro", 16, 0b0_0110)]

    ctrl.establecer_torre(False, True, False)
    assert cliente.escrituras[-1] == ("registro", 16, 0b0_1010)

    ctrl.establecer_torre(False, False, True)
    assert cliente.escrituras[-1] == ("registro", 16, 0b1_0010)

    ctrl.establecer_torre(False, False, False)
    assert cliente.escrituras[-1] == ("registro", 16, 0b0_0010)


def test_torre_es_idempotente(monkeypatch):
    """Repetir el mismo estado no genera trafico Modbus."""
    ctrl, cliente = _controlador(monkeypatch)
    ctrl._conectar()
    ctrl.establecer_torre(False, True, False)
    cliente.escrituras.clear()

    ctrl.establecer_torre(False, True, False)
    ctrl.establecer_torre(False, True, False)

    assert cliente.escrituras == []


def test_torre_conserva_los_bits_de_comando_en_la_palabra(monkeypatch):
    """Los bits de torre NO deben borrar otros bits de la misma palabra J."""
    ctrl, cliente = _controlador(monkeypatch)
    ctrl._conectar()          # latch de PARO: J1 bit1 = 1 (palabra = 0b10)
    cliente.escrituras.clear()

    ctrl.establecer_torre(True, False, False)

    registro, palabra = cliente.escrituras[-1][1:]
    assert registro == 16
    assert palabra & 0b10, "el bit de PARO debe conservarse"
    assert palabra & 0b100, "el verde debe encenderse"


def test_alarma_parpadea_y_termina(monkeypatch):
    """Al entrar en rojo la alarma se enciende y se apaga (discontinua) y
    deja de sonar al cumplirse la duracion."""
    ctrl, cliente = _controlador(monkeypatch, tower_alarm_duracion_s=0.3)
    ctrl._conectar()
    ctrl.establecer_torre(False, False, True)
    cliente.escrituras.clear()

    ctrl.pulso_alarma()
    ctrl._gestionar_alarma()
    # Primer tick: alarma ENCENDIDA junto con la roja.
    assert cliente.escrituras[-1] == ("registro", 16, 0b11_0010)

    ctrl._gestionar_alarma()
    # Segundo tick: alarma APAGADA (la roja sigue).
    assert cliente.escrituras[-1] == ("registro", 16, 0b1_0010)

    time.sleep(0.35)
    ctrl._gestionar_alarma()

    assert ctrl._torre_alarma_activa is False
    assert cliente.escrituras[-1] == ("registro", 16, 0b1_0010)


def test_pulso_alarma_es_idempotente(monkeypatch):
    """Mientras la ventana siga abierta no se reinicia el parpadeo."""
    ctrl, cliente = _controlador(monkeypatch)
    ctrl._conectar()

    ctrl.pulso_alarma()
    fin = ctrl._alarma_fin
    ctrl.pulso_alarma()

    assert ctrl._alarma_fin == fin


def test_heartbeat_conmuta_el_bit_de_j4(monkeypatch):
    """J4 (dir 19) bit0 debe cambiar en cada envio: el PLC lo vigila."""
    ctrl, cliente = _controlador(monkeypatch)
    ctrl._conectar()
    cliente.escrituras.clear()

    ctrl._conmutar_heartbeat()
    ctrl._conmutar_heartbeat()
    ctrl._conmutar_heartbeat()

    assert cliente.escrituras == [
        ("registro", 19, 1),
        ("registro", 19, 0),
        ("registro", 19, 1),
    ]


def test_cierre_apaga_la_torre_y_el_heartbeat(monkeypatch):
    """Al cerrar la app la torre no puede quedar encendida."""
    ctrl, cliente = _controlador(monkeypatch)
    ctrl._conectar()
    ctrl.establecer_torre(True, False, False)
    ctrl._conmutar_heartbeat()
    cliente.escrituras.clear()

    ctrl.cleanup()

    palabras = [e[2] for e in cliente.escrituras if e[:2] == ("registro", 16)]
    assert palabras, "el cierre debe escribir la palabra de comando"
    assert palabras[-1] & 0b111100 == 0, "los bits de torre/alarma quedan en 0"
    assert palabras[-1] & 0b10, "el PARO sigue latcheado"
    assert ("registro", 19, 0) in cliente.escrituras


def test_torre_en_simulacion_no_toca_la_red(monkeypatch):
    cliente = ClienteFalso()
    monkeypatch.setattr(mod, "ModbusClient", lambda *a, **k: cliente)
    ctrl = mod.ModbusController(
        {"host": "", "modo_simulacion": True, "cmd_mode": "registro"},
        iniciar_polling=False,
    )

    ctrl.establecer_torre(True, False, False)
    ctrl.pulso_alarma()
    ctrl._gestionar_alarma()
    ctrl._conmutar_heartbeat()

    assert cliente.escrituras == []

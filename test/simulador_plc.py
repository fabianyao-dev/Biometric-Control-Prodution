"""
simulador_plc.py - Emulador de PLC Zelio (SR3 + SR3NET01BD) por Modbus TCP.

Servidor Modbus TCP que replica fielmente el mapa de registros medido en el
PLC Zelio real de planta (192.158.1.80) para pruebas completas de WTSControl
sin necesidad de hardware.

Mapa de registros emulado (Zelio Logic 2 SR3 + modulo Ethernet SR3NET01BD):
    Palabras J (dir 16-19, PC -> PLC):
        - J1 (dir 16):
            * bit 0: START (pulso momentaneo ~300ms de marcha)
            * bit 1: PARO (latch sostenido: 1 = maquina detenida)
            * bit 2: Torre VERDE (produccion en curso)
            * bit 3: Torre AMBAR (paro reciente / tolerancia)
            * bit 4: Torre ROJA (paro prolongado)
            * bit 5: ALARMA / buzzer discontinuo
        - J2 (dir 17): libre
        - J3 (dir 18): libre
        - J4 (dir 19):
            * bit 0: Heartbeat (conmutado por la PC cada 2s)

    Palabras O (dir 20-23, PLC -> PC):
        - O1 (dir 20): Contador de cortes (16 bits, 0..65535, con wraparound)
        - O2 (dir 21): Pulso de corte (destella en 1 un instante en cada corte)
        - O3 (dir 22): Libre / reservado
        - O4 (dir 23): Libre / reservado

Uso:
    venv\\Scripts\\python test\\simulador_plc.py                    # 127.0.0.1:502, +2 cortes/seg
    venv\\Scripts\\python test\\simulador_plc.py --port 5020       # puerto alternativo
    venv\\Scripts\\python test\\simulador_plc.py --velocidad 0     # solo cortes manuales (Enter)
    venv\\Scripts\\python test\\simulador_plc.py --inicial 500     # arrancar con 500 cortes

Comandos en la consola del simulador:
    Enter o +      +1 corte manual (incrementa O1 y pulsa O2)
    c              correr contador automatico
    p              pausar contador automatico
    v <N>          cambiar velocidad a N cortes/segundo (ej. v 5)
    r              resetear contador a 0
    s              mostrar estado actual de palabras J y O
    h o ?          mostrar ayuda
    q o salir      detener simulador
"""

import argparse
import os
import sys
import threading
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pyModbusTCP.server import DataBank, ModbusServer

from src import config

sys.stdout.reconfigure(encoding="utf-8")

J_BASE = 16   # J1..J4 (dirs 16, 17, 18, 19)
O_BASE = 20   # O1..O4 (dirs 20, 21, 22, 23)
MAX_CONTADOR_16 = 65535


def _marca():
    return datetime.now().strftime("%H:%M:%S")


def _log(*args):
    print(*args, flush=True)


class BancoZelioPLC(DataBank):
    """DataBank que modela la logica del Zelio Logic 2 con SR3NET01BD."""

    def __init__(self, dir_contador=20, inicial=0, velocidad=2.0):
        super().__init__()
        self._dir_contador = int(dir_contador)
        self._contador = int(inicial) % (MAX_CONTADOR_16 + 1)
        self._velocidad_objetivo = max(0.0, float(velocidad))
        self._acumulado = 0.0
        self._auto = self._velocidad_objetivo > 0

        # Estado del PLC
        self._maquina_marcha = False
        self._ultimo_heartbeat = None
        self._hb_valor = 0
        self._j1_previo = 0

        # Inicializar palabras J (16..19) y O (20..23) en 0
        self.set_holding_registers(J_BASE, [0, 0, 0, 0])
        self.set_holding_registers(O_BASE, [self._contador, 0, 0, 0])

        self._stop = threading.Event()
        self._th_contador = None

    def iniciar(self):
        self._th_contador = threading.Thread(
            target=self._bucle_plc, daemon=True, name="zelio-sim-worker"
        )
        self._th_contador.start()

    def sumar_cortes(self, cantidad=1):
        if cantidad <= 0:
            return
        with self._h_regs_lock:
            self._contador = (self._contador + cantidad) & MAX_CONTADOR_16
            # O1: contador, O2: pulso de corte activo
            self.set_holding_registers(O_BASE, [self._contador, 1])

        _log(
            f"[{_marca()}] +{cantidad} corte(s) -> "
            f"O1 (contador) = {self._contador} | O2 = 1 (pulso)"
        )

        # Apagar el pulso O2 tras 150 ms para simular el comportamiento real del PLC
        def _apagar_pulso():
            time.sleep(0.15)
            with self._h_regs_lock:
                self.set_holding_registers(O_BASE + 1, [0])

        threading.Thread(target=_apagar_pulso, daemon=True).start()

    def _bucle_plc(self):
        prev = time.monotonic()
        prox_reporte = prev + 3.0

        while not self._stop.is_set():
            time.sleep(0.05)
            ahora = time.monotonic()
            dt = ahora - prev
            prev = ahora

            if self._auto:
                self._acumulado += self._velocidad_objetivo * dt
                if self._acumulado >= 1.0:
                    cortes = int(self._acumulado)
                    self._acumulado -= cortes
                    self.sumar_cortes(cortes)

            # Reporte periodico en consola
            if ahora >= prox_reporte:
                prox_reporte = ahora + 5.0
                estado = "CORRIENDO" if self._auto else "PAUSADO"
                maquina = "EN MARCHA" if self._maquina_marcha else "DETENIDA (PARO)"
                _log(
                    f"[{_marca()}] [ZELIO] Contador O1: {self._contador} "
                    f"({estado}) | Maquina: {maquina}"
                )

    def reanudar_contador(self):
        self._auto = True
        self._acumulado = 0.0
        _log(f"[{_marca()}] Contador automatico: CORRIENDO ({self._velocidad_objetivo} cortes/seg)")

    def pausar_contador(self):
        self._auto = False
        _log(f"[{_marca()}] Contador automatico: PAUSADO")

    def cambiar_velocidad(self, velocidad):
        self._velocidad_objetivo = max(0.0, float(velocidad))
        if self._velocidad_objetivo > 0:
            self.reanudar_contador()
        else:
            self.pausar_contador()
        _log(f"[{_marca()}] Velocidad ajustada: {self._velocidad_objetivo} cortes/seg")

    def resetear_contador(self):
        with self._h_regs_lock:
            self._contador = 0
            self.set_holding_registers(O_BASE, [0])
        _log(f"[{_marca()}] Contador O1 reiniciado a 0")

    def imprimir_estado(self):
        with self._h_regs_lock:
            j = self.get_holding_registers(J_BASE, 4) or [0, 0, 0, 0]
            o = self.get_holding_registers(O_BASE, 4) or [0, 0, 0, 0]

        j1 = j[0]
        start = (j1 >> 0) & 1
        paro = (j1 >> 1) & 1
        verde = (j1 >> 2) & 1
        ambar = (j1 >> 3) & 1
        roja = (j1 >> 4) & 1
        alarma = (j1 >> 5) & 1
        hb = (j[3] >> 0) & 1 if len(j) > 3 else 0

        torre = []
        if verde:
            torre.append("VERDE")
        if ambar:
            torre.append("AMBAR")
        if roja:
            torre.append("ROJA")
        if alarma:
            torre.append("ALARMA")
        torre_txt = " + ".join(torre) if torre else "APAGADA"

        _log("=" * 60)
        _log(f"ESTADO DEL PLC ZELIO ({_marca()}):")
        _log("  Entradas PC -> PLC (dirs 16-19):")
        _log(f"    J1 (dir 16) = {j1} (0b{j1:08b})")
        _log(f"       START={start} | PARO={paro} | TORRE=[{torre_txt}]")
        _log(f"    J2 (dir 17) = {j[1]} | J3 (dir 18) = {j[2]}")
        _log(f"    J4 (dir 19) = {j[3]} -> Heartbeat bit0={hb}")
        _log("  Salidas PLC -> PC (dirs 20-23):")
        _log(f"    O1 (dir 20, contador) = {o[0]}")
        _log(f"    O2 (dir 21, pulso)    = {o[1]}")
        _log(f"    O3 (dir 22) = {o[2]} | O4 (dir 23) = {o[3]}")
        _log("  Estado logico:")
        _log(
            f"    Auto-conteo : {'ACTIVO' if self._auto else 'PAUSADO'} "
            f"({self._velocidad_objetivo} cortes/seg)"
        )
        _log(f"    Maquina     : {'EN MARCHA' if self._maquina_marcha else 'DETENIDA'}")
        _log("=" * 60)

    def detener(self):
        self._stop.set()
        if self._th_contador is not None:
            self._th_contador.join(timeout=2.0)

    # ------------------------------------------------------------------
    # Intercepcion de escrituras del Master (la App WTSControl)
    # ------------------------------------------------------------------

    def on_holding_registers_change(self, address, from_value, to_value, srv_info):
        """Monitorea escrituras del Master en palabras J1..J4."""
        if address == J_BASE:  # J1: START, PARO, TORRE
            cambios = []
            start = (to_value >> 0) & 1
            paro = (to_value >> 1) & 1
            verde = (to_value >> 2) & 1
            ambar = (to_value >> 3) & 1
            roja = (to_value >> 4) & 1
            alarma = (to_value >> 5) & 1

            if start:
                cambios.append("PULSO START (Q1)")
                self._maquina_marcha = True
            if paro:
                cambios.append("LATCH PARO (Q2)")
                self._maquina_marcha = False
            elif not paro and not start and from_value is not None and ((from_value >> 1) & 1):
                cambios.append("LIBERAR PARO")

            luces = []
            if verde:
                luces.append("VERDE (Q3)")
            if ambar:
                luces.append("AMBAR (Q4)")
            if roja:
                luces.append("ROJA (Q5)")
            if alarma:
                luces.append("ALARMA (Q6)")
            if luces:
                cambios.append(f"Torre: {', '.join(luces)}")
            else:
                cambios.append("Torre: APAGADA")

            detalle = " | ".join(cambios)
            _log(f"[{_marca()}] [ESC J1 dir 16] = {to_value} (0b{to_value:08b}) -> {detalle}")

        elif address == J_BASE + 3:  # J4 (dir 19): Heartbeat
            latido = (to_value >> 0) & 1
            self._ultimo_heartbeat = time.monotonic()
            self._hb_valor = latido
            # Solo loguear si hay cambio de bit para no saturar consola
            if from_value is None or ((from_value ^ to_value) & 1):
                _log(f"[{_marca()}] [ESC J4 dir 19] Heartbeat bit0={latido}")

        elif address in (J_BASE + 1, J_BASE + 2):
            _log(f"[{_marca()}] [ESC J{address - J_BASE + 1} dir {address}] = {to_value}")
        else:
            _log(f"[{_marca()}] [ESC Registro {address}] = {to_value}")


AYUDA = """
Comandos disponibles (terminal del simulador):
  Enter o +      +1 corte manual (incrementa O1 y pulsa O2)
  c              correr contador automatico
  p              pausar contador automatico
  v <N>          cambiar velocidad a N cortes/segundo (ej. v 3)
  r              resetear contador a 0
  s              mostrar estado actual de palabras J y O
  h o ?          mostrar esta ayuda
  q o salir      detener el simulador
"""


def _bucle_interactivo(banco):
    while True:
        try:
            linea = sys.stdin.readline()
        except KeyboardInterrupt:
            return False
        if not linea:  # EOF
            return True
        cmd = linea.strip().lower()
        if cmd in ("", "+"):
            banco.sumar_cortes(1)
        elif cmd in ("c", "correr"):
            banco.reanudar_contador()
        elif cmd in ("p", "pausar", "parar"):
            banco.pausar_contador()
        elif cmd.startswith("v "):
            try:
                banco.cambiar_velocidad(float(cmd[2:].strip()))
            except ValueError:
                _log("Uso: v <cortes/seg>  (ej. v 2.5)")
        elif cmd in ("r", "reset"):
            banco.resetear_contador()
        elif cmd in ("s", "status", "estado"):
            banco.imprimir_estado()
        elif cmd in ("h", "?", "ayuda"):
            _log(AYUDA)
        elif cmd in ("q", "salir", "exit"):
            return False
        else:
            _log("Comando no reconocido. Escribe 'h' o '?' para ayuda.")


def main():
    cfg = config.MODBUS_CONFIG
    parser = argparse.ArgumentParser(
        description="Emulador Modbus TCP para PLC Zelio Logic 2 (SR3 + SR3NET01BD)"
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Direccion IP a escuchar (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=cfg.get("port", 502),
        help=f"Puerto Modbus TCP (default: {cfg.get('port', 502)})",
    )
    parser.add_argument(
        "--velocidad",
        type=float,
        default=2.0,
        help="Velocidad de cortes/segundo automaticos (default: 2.0; 0 = solo manual)",
    )
    parser.add_argument(
        "--inicial",
        type=int,
        default=0,
        help="Valor inicial del contador O1 (default: 0)",
    )
    parser.add_argument(
        "--contador",
        type=int,
        default=cfg.get("counter_register", 20),
        help=f"Direccion del registro contador (default: {cfg.get('counter_register', 20)})",
    )

    args = parser.parse_args()

    banco = BancoZelioPLC(
        dir_contador=args.contador,
        inicial=args.inicial,
        velocidad=args.velocidad,
    )
    servidor = ModbusServer(
        host=args.host,
        port=args.port,
        no_block=True,
        data_bank=banco,
    )

    try:
        servidor.start()
    except ModbusServer.NetworkError as e:
        _log(f"[ERROR] No se pudo abrir {args.host}:{args.port} ({e})")
        _log("Sugerencia: Si el puerto 502 requiere permisos o esta en uso, prueba: --port 5020")
        return 1

    banco.iniciar()

    _log("=" * 65)
    _log(f" SIMULADOR PLC ZELIO SR3NET01BD ESCUCHANDO EN {args.host}:{args.port}")
    _log("=" * 65)
    _log("  Entradas J (dirs 16-19) : J1 (START/PARO/TORRE), J4 (Heartbeat)")
    _log(f"  Salidas O (dirs 20-23)  : O1 (Contador reg {args.contador}), O2 (Pulso)")
    _log(f"  Contador inicial        : {args.inicial}")
    _log(f"  Velocidad automatica    : {args.velocidad} cortes/seg")
    _log("=" * 65)
    _log(AYUDA)

    try:
        seguir = _bucle_interactivo(banco)
        if not seguir:
            _log("Deteniendo simulador PLC...")
        else:
            _log("Modo no interactivo activo. Ctrl+C para salir.")
            while True:
                time.sleep(1.0)
    except KeyboardInterrupt:
        _log("\nInterrumpido por el usuario. Deteniendo simulador...")
    finally:
        banco.detener()
        servidor.stop()

    return 0


if __name__ == "__main__":
    sys.exit(main())

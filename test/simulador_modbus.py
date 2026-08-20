"""
simulador_modbus.py - Emulador Modbus TCP del modulo Advantech (pruebas).

Servidor Modbus TCP que imita el comportamiento del modulo real (contador
interno + coils START/PAUSE) para probar ModbusController, test_modbus.py y la
GUI SIN hardware. Corre en un proceso aparte ("en paralelo") mientras la app
se conecta por red (MODBUS_HOST=127.0.0.1).

Comportamiento emulado:
    - Registro contador (MODBUS_COUNTER_REGISTER, little-endian como el
      WISE-4060LAN: palabra baja primero) que sube solo a `--velocidad`
      cortes/segundo y/o +1 por Enter. El wraparound del contador se replica
      como en el modulo real.
    - Coils START/PAUSE (MODBUS_START_COIL / MODBUS_PAUSE_COIL): cada
      escritura se imprime en consola con marca de tiempo, para verificar
      que los pulsos son momentaneos (~PULSO_DURACION_MS).
    - Cualquier escritura a registros de holding se loguea (p. ej. un reset
      externo del contador).

Uso:
    venv\\Scripts\\python test\\simulador_modbus.py              # 127.0.0.1:502, +2 cortes/seg
    venv\\Scripts\\python test\\simulador_modbus.py --velocidad 0   # arranca en pausa (solo manual)
    venv\\Scripts\\python test\\simulador_modbus.py --port 5020 --inicial 100

En la terminal del simulador (ademas del log de relevadores/contador):
    Enter o +   +1 corte manual      c = correr contador     p = pausar contador
    v N = velocidad a N cortes/seg   h/? = ayuda             q/salir = detener

Despues, en OTRA terminal (apuntar la app al simulador):
    venv\\Scripts\\python test\\test_modbus.py --ip 127.0.0.1
    o bien con MODBUS_HOST=127.0.0.1 en el .env para la GUI / ModbusController.
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


def _marca():
    return datetime.now().strftime("%H:%M:%S")


def _log(*args):
    print(*args, flush=True)


class BancoModbus(DataBank):
    """DataBank del modulo simulado: contador auto-incremental + log de coils."""

    def __init__(self, palabras_contador, start_coil, pause_coil, counter_register):
        super().__init__()
        self._palabras = int(palabras_contador)
        self._start_coil = int(start_coil)
        self._pause_coil = int(pause_coil)
        self._counter_register = int(counter_register)
        self._bits = 16 * self._palabras
        self._max_valor = (1 << self._bits) - 1

        self._contador = 0
        self._acumulado = 0.0
        self._velocidad_objetivo = 0.0
        self._auto = False
        self._stop = threading.Event()
        self._th_contador = None

    # ------------------------------------------------------------------
    # Contador
    # ------------------------------------------------------------------

    def iniciar_contador(self, inicial, velocidad):
        self._contador = int(inicial) % self._max_valor
        self._velocidad_objetivo = max(0.0, float(velocidad))
        self._auto = self._velocidad_objetivo > 0
        self._escribir_contador()
        self._th_contador = threading.Thread(
            target=self._bucle_contador, daemon=True
        )
        self._th_contador.start()

    def _escribir_contador(self):
        valor = self._contador & self._max_valor
        regs = []
        for i in range(self._palabras):
            regs.append((valor >> (16 * i)) & 0xFFFF)
        self.set_holding_registers(self._counter_register, regs)

    def sumar_cortes(self, cantidad):
        if cantidad <= 0:
            return
        with self._h_regs_lock:
            self._contador = (self._contador + cantidad) % self._max_valor
        self._escribir_contador()
        _log(f"[{_marca()}] +{cantidad} corte(s) -> contador {self._contador}")

    def _bucle_contador(self):
        prev = time.monotonic()
        prox_status = prev + 2.0
        while not self._stop.is_set():
            time.sleep(0.1)
            ahora = time.monotonic()
            dt = ahora - prev
            prev = ahora
            if self._auto:
                self._acumulado += self._velocidad_objetivo * dt
                if self._acumulado >= 1.0:
                    enteros = int(self._acumulado)
                    self._acumulado -= enteros
                    self.sumar_cortes(enteros)
            if ahora >= prox_status:
                prox_status = ahora + 2.0
                with self._h_regs_lock:
                    valor = self._contador
                estado = "en pausa" if not self._auto else "corriendo"
                _log(f"[{_marca()}] Contador: {valor} ({estado})")

    def reanudar_contador(self):
        self._auto = True
        self._acumulado = 0.0
        _log("Contador automatico: CORRIENDO")

    def pausar_contador(self):
        self._auto = False
        _log("Contador automatico: PAUSADO")

    def cambiar_velocidad(self, velocidad):
        self._velocidad_objetivo = max(0.0, float(velocidad))
        if self._velocidad_objetivo > 0:
            self.reanudar_contador()
        else:
            self.pausar_contador()
        _log(f"Velocidad: {self._velocidad_objetivo} cortes/seg")

    def detener(self):
        self._stop.set()
        if self._th_contador is not None:
            self._th_contador.join(timeout=2.0)

    # ------------------------------------------------------------------
    # Callbacks del DataBank (se invocan desde los hilos del servidor)
    # ------------------------------------------------------------------

    def on_coils_change(self, address, from_value, to_value, srv_info):
        if address == self._start_coil:
            nombre = "START"
        elif address == self._pause_coil:
            nombre = "PAUSE"
        else:
            nombre = f"coil {address}"
        estado = "ENCENDIDO" if to_value else "APAGADO"
        _log(f"[{_marca()}] Escritura coil {nombre} ({address}): {estado}")

    def on_holding_registers_change(self, address, from_value, to_value,
                                    srv_info):
        if address == self._counter_register:
            _log(f"[{_marca()}] Registro contador sobrescrito: {to_value}")


AYUDA = """Comandos (terminal del simulador):
  Enter o +      +1 corte manual
  c              correr contador automatico
  p              pausar contador
  v N            velocidad a N cortes/seg (v 0 = pausar)
  h o ?          ayuda
  q o salir      detener el simulador"""


def _bucle_comandos(banco):
    """Lee comandos de la terminal. True = seguir, False = salir."""
    while True:
        try:
            linea = sys.stdin.readline()
        except KeyboardInterrupt:
            return False
        if not linea:  # EOF (stdin cerrado / no interactivo)
            return True
        cmd = linea.strip().lower()
        if cmd in ("", "+"):
            banco.sumar_cortes(1)
        elif cmd in ("c", "correr"):
            banco.reanudar_contador()
        elif cmd in ("p", "parar"):
            banco.pausar_contador()
        elif cmd.startswith("v "):
            try:
                banco.cambiar_velocidad(float(cmd[2:]))
            except ValueError:
                _log("Uso: v <cortes/seg>")
        elif cmd in ("h", "?", "ayuda"):
            _log(AYUDA)
        elif cmd in ("q", "salir"):
            return False
        else:
            _log("Comando no reconocido. Escribe 'h' para ayuda.")


def main():
    cfg = config.MODBUS_CONFIG
    parser = argparse.ArgumentParser(
        description="Emulador Modbus TCP del modulo Advantech"
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=cfg["port"])
    parser.add_argument("--velocidad", type=float, default=2.0,
                        help="Cortes/segundo automaticos (0 = solo manual)")
    parser.add_argument("--inicial", type=int, default=0,
                        help="Valor inicial del contador")
    args = parser.parse_args()

    banco = BancoModbus(
        cfg["counter_words"], cfg["start_coil"], cfg["pause_coil"],
        cfg["counter_register"],
    )
    servidor = ModbusServer(host=args.host, port=args.port, no_block=True,
                            data_bank=banco)
    try:
        servidor.start()
    except ModbusServer.NetworkError as e:
        _log(f"No se pudo abrir {args.host}:{args.port}: {e}")
        return 1

    banco.iniciar_contador(args.inicial, args.velocidad)
    _log(f"Simulador Modbus en {args.host}:{args.port} "
         f"(unit_id={cfg['unit_id']})")
    _log(f"  contador: reg {cfg['counter_register']} x{cfg['counter_words']} "
         f"words, inicial {args.inicial}, {args.velocidad} cortes/seg")
    _log(f"  coils: START={cfg['start_coil']} PAUSE={cfg['pause_coil']}")
    _log(AYUDA)
    try:
        seguir = _bucle_comandos(banco)
        if not seguir:
            _log("Deteniendo simulador...")
        else:
            _log("Entrada no interactiva; servidor escuchando. "
                 "Ctrl+C para salir.")
            while True:
                time.sleep(0.5)
    except KeyboardInterrupt:
        _log("\nDeteniendo simulador...")
    finally:
        banco.detener()
        servidor.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())

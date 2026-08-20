"""
simulacion_controller.py - HAL de relevadores y contador de cortes (simulacion).

El hardware real (relevadores y contador de cortes) se controla via Modbus
TCP con el modulo Advantech (ver modbus_controller.py). SimulacionController
queda como HAL de fallback y desarrollo: cuando no hay MODBUS_HOST la GUI corre
en modo simulacion, los pulsos a los relevadores solo se registran en el log
y los cortes se suman con simular_corte(). Mantiene el mismo contrato que
ModbusController para que la GUI no cambie:

    - maquina_lista()    -> simula pulso en rele START (arranca)
    - maquina_pausada()  -> simula latch en rele PAUSE (paro sostenido)
    - reprisar_maquina() -> reanuda tras autorizar un paro
    - cortes_totales()   -> int (contador de cortes)
    - reset_conteo()     -> pone el contador en 0
    - establecer_conteo(total) -> restaura desde el checkpoint de la BD
    - segundos_sin_corte() -> float (alimenta SEGURO_PARO_SEGUNDOS)
    - segundos_desde_arranque() -> float (alimenta PARO_IDLE_TIMEOUT_S)
    - simular_corte()    -> suma un corte
    - maquina_detenida() -> bool
    - en_simulacion()    -> siempre True
    - cleanup()          -> idempotente
"""

import logging
import threading
import time

from src import config

log = logging.getLogger(__name__)


class SimulacionController:
    """HAL de relevadores y contador en modo simulacion.

    Sin MODBUS_HOST el sistema trabaja sin hardware: los pulsos no se envian
    a ningun pin (solo log) y el contador se alimenta con simular_corte().
    """

    def __init__(self, simulacion_config=None):
        cfg = dict(simulacion_config or config.SIMULACION_CONFIG)

        self._pin_start = cfg.get("rele_start")
        self._pin_pause = cfg.get("rele_pause")
        self._pin_sensor = cfg.get("sensor_corte")
        self._pulso_ms = int(cfg.get("pulso_duracion_ms", 300))

        self._lock = threading.Lock()
        self._cortes = 0
        # `_ultimo_corte` SOLO se actualiza con cortes reales (simular_corte);
        # `_ultimo_arranque` es la ultima vez que la maquina arranco/reanudo
        # (gracia del auto-paro). Ver modbus_controller.py.
        self._ultimo_corte = time.time()
        self._ultimo_arranque = time.time()
        self._maquina_en_marcha = False
        log.info("SimulacionController en modo SIMULACION (sin hardware)")

    def en_simulacion(self) -> bool:
        return True

    # ------------------------------------------------------------------
    # Contador de cortes
    # ------------------------------------------------------------------

    def _sumar_corte(self, channel=None):
        with self._lock:
            self._cortes += 1
            self._ultimo_corte = time.time()

    def segundos_sin_corte(self) -> float:
        """Segundos transcurridos desde el ultimo corte real."""
        with self._lock:
            return time.time() - self._ultimo_corte

    def segundos_desde_arranque(self) -> float:
        """Tiempo desde que la maquina arranco o reanudo (o inf si detenida)."""
        with self._lock:
            if not self._maquina_en_marcha:
                return float("inf")
            return time.time() - self._ultimo_arranque

    def simular_corte(self):
        """Suma un corte (usado por la GUI en modo simulacion / pruebas)."""
        self._sumar_corte()

    def cortes_totales(self) -> int:
        with self._lock:
            return self._cortes

    def reset_conteo(self):
        with self._lock:
            self._cortes = 0

    def establecer_conteo(self, total: int):
        """Restaura el contador desde el ultimo checkpoint de la BD.

        Se usa al retomar una sesion interrumpida: los cortes se siguen
        sumando sobre este total como base.
        """
        with self._lock:
            self._cortes = int(total)

    # ------------------------------------------------------------------
    # Relevadores (simulacion)
    # ------------------------------------------------------------------

    _RELES = {
        "_pin_start": "RELE_ENCENDIDO",
        "_pin_pause": "RELE_PARO",
        "_pin_sensor": "SENSOR_CORTE",
    }

    def _nombre_rele(self, pin):
        for attr, nombre in self._RELES.items():
            if getattr(self, attr, None) == pin:
                return nombre
        return f"pin_{pin}"

    def maquina_lista(self):
        """Simula el arranque: suelta el rele de PARO (latch) y pulsa START."""
        if self._maquina_en_marcha:
            return
        log.info("-> MARCHA: pulso RELE_ENCENDIDO (start_pin=%s) [simulacion]",
                 self._pin_start)
        self._maquina_en_marcha = True
        self._ultimo_arranque = time.time()
        log.info("Maquina INICIADA (pulso enviado)")

    def maquina_pausada(self):
        """Simula PARO SOSTENIDO: rele PAUSE en nivel activo (latch)."""
        log.info("-> PARO: latch RELE_PARO (pause_pin=%s) [simulacion]",
                 self._pin_pause)
        self._maquina_en_marcha = False
        log.info("Maquina en PARO (rele sostenido)")

    def reprisar_maquina(self):
        """Reanuda la produccion tras un paro autorizado."""
        self.maquina_lista()

    def maquina_detenida(self) -> bool:
        return not self._maquina_en_marcha

    # ------------------------------------------------------------------
    # Cierre
    # ------------------------------------------------------------------

    def cleanup(self):
        """Resetea el estado. Idempotente."""
        if getattr(self, "_cleaned", False):
            return
        self._cleaned = True
        self._maquina_en_marcha = False
        log.info("SimulacionController liberado")

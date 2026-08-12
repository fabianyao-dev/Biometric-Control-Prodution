"""
modbus_controller.py - HAL Modbus TCP para la PC Fanless (Windows).

Sustituye a SimulacionController manteniendo EXACTAMENTE la misma interfaz
publica (ver docstring de simulacion_controller.py), para que la GUI jamas se
entere de que el hardware cambio de simulacion a red.

Diseno (decisiones de planta):
    - EL CONTADOR DE CORTES VIVE EN EL MODULO. El modulo Advantech cuenta los
      pulsos del sensor en un contador interno de alta velocidad (por
      hardware); la PC NUNCA detecta flancos localmente, porque Windows no es
      un SO en tiempo real y un micro-congelamiento del proceso perderia
      conteos. La PC solo hace polling por red (MODBUS_POLL_MS) y suma la
      diferencia del registro contador.
    - Los relevadores se siguen manejando como PULSO MOMENTANEO (circuito
      tipo boton, ver simulacion_controller.py): escribir el coil en True
      durante PULSO_DURACION_MS y volver a False. Nunca dejar un rele
      energizado.
    - La conexion es defensiva: si la red se cae (cable por vibracion), la UI
      no crashea; el controlador marca `desconectado`, reintenta en segundo
      plano y expone `conectado()` para que la GUI muestre una alerta.

El mapa de registros (coils y registro contador) es CONFIGURABLE desde .env
(MODBUS_START_COIL, MODBUS_PAUSE_COIL, MODBUS_COUNTER_REGISTER) para que un
cambio de modelo/marca del modulo no toque el codigo fuente.

Contrato (identico a SimulacionController):
    - maquina_lista()     -> pulso en coil START (arranca)
    - maquina_pausada()   -> pulso en coil PAUSE (paro)
    - reprisar_maquina()  -> reanuda tras autorizar un paro
    - cortes_totales()    -> int (acumulado local)
    - reset_conteo()      -> pone el contador local en 0
    - establecer_conteo(n)-> base desde el ultimo checkpoint de la BD
    - segundos_sin_corte()-> float (alimenta PARO_IDLE_TIMEOUT_S)
    - simular_corte()     -> suma un corte (modo simulacion / pruebas)
    - maquina_detenida()  -> bool
    - conectado()         -> bool (estado del enlace Modbus, para la UI)
    - cleanup()           -> detiene hilos y cierra el socket (siempre!)
"""

import logging
import threading
import time

from src import config

log = logging.getLogger(__name__)

try:
    from pyModbusTCP.client import ModbusClient
except ImportError:  # pragma: no cover - pyModbusTCP en requirements.txt
    ModbusClient = None


class ModbusController:
    """Controlador de reles y contador de cortes via Modbus TCP."""

    def __init__(self, modbus_config=None):
        cfg = dict(modbus_config or config.MODBUS_CONFIG)

        self._host = cfg.get("host", "").strip()
        self._port = int(cfg.get("port", 502))
        self._unit_id = int(cfg.get("unit_id", 1))
        self._timeout = float(cfg.get("timeout", 2.0))
        self._start_coil = int(cfg.get("start_coil", 0))
        self._pause_coil = int(cfg.get("pause_coil", 1))
        self._counter_register = int(cfg.get("counter_register", 0))
        self._counter_words = int(cfg.get("counter_words", 2))
        self._poll_ms = int(cfg.get("poll_ms", 500))
        self._pulso_ms = int(cfg.get("pulso_duracion_ms", 300))
        self._max_delta = int(cfg.get("max_delta", 10000))
        self._simulacion = bool(cfg.get("modo_simulacion"))

        self._bits = 16 * self._counter_words
        self._max_valor = (1 << self._bits) - 1

        self._lock = threading.Lock()          # estado compartido con la UI
        self._lock_modbus = threading.Lock()   # socket: un request a la vez
        self._stop = threading.Event()

        self._modbus = None
        self._conectado = False
        self._cortes = 0
        self._ultimo_contador = 0
        self._ultimo_corte = time.time()
        self._maquina_en_marcha = False
        self._cleaned = False

        if self._simulacion or not self._host:
            self._simulacion = True
            log.info("Modbus en SIMULACION (sin MODBUS_HOST o "
                     "MODBUS_SIMULACION=1).")
        else:
            if ModbusClient is None:
                log.error("pyModbusTCP no instalado; Modbus en simulacion.")
                self._simulacion = True
            else:
                self._arrancar_polling()

    # ------------------------------------------------------------------
    # Conexion y polling
    # ------------------------------------------------------------------

    def _arrancar_polling(self):
        threading.Thread(target=self._bucle_polling, daemon=True).start()

    def _conectar(self) -> bool:
        """Abre el socket y lee el contador una vez para validar el enlace."""
        with self._lock_modbus:
            try:
                cliente = ModbusClient(
                    self._host, self._port, unit_id=self._unit_id,
                    timeout=self._timeout, auto_open=True,
                )
                regs = cliente.read_holding_registers(
                    self._counter_register, self._counter_words
                )
                if not regs or len(regs) < self._counter_words:
                    cliente.close()
                    return False
                lectura = self._combinar_regs(regs)
                self._modbus = cliente
                self._conectado = True
                self._ultimo_contador = lectura
                log.info("Modbus conectado a %s:%s (contador=%s).",
                         self._host, self._port, lectura)
                return True
            except Exception as e:  # noqa: BLE001
                log.warning("Modbus sin conexion (%s).", e)
                self._modbus = None
                self._conectado = False
                return False

    def _combinar_regs(self, regs):
        """Junta los registros de 16 bits en un valor (big-endian)."""
        valor = 0
        for r in regs[: self._counter_words]:
            valor = (valor << 16) | (r & 0xFFFF)
        return valor

    def _bucle_polling(self):
        """Ciclo de polling: leer contador, sumar delta, reconectar si cae."""
        reintento = 1.0
        while not self._stop.is_set():
            if not self._conectado:
                if self._conectar():
                    reintento = 1.0
                else:
                    time.sleep(reintento)
                    reintento = min(reintento * 2, 5.0)
                    continue
            self._poll_contador()
            self._stop.wait(self._poll_ms / 1000.0)

    def _poll_contador(self):
        with self._lock_modbus:
            cliente = self._modbus
            if cliente is None:
                self._conectado = False
                return
            try:
                regs = cliente.read_holding_registers(
                    self._counter_register, self._counter_words
                )
            except Exception as e:  # noqa: BLE001
                log.warning("Modbus: fallo lectura (%s); marcando "
                            "desconectado.", e)
                self._desconectar()
                return
        if regs is None:
            log.warning("Modbus: fallo de lectura (None); desconectando.")
            self._desconectar()
            return
        if len(regs) < self._counter_words:
            log.warning("Modbus: lectura corta (%s); desconectando.", regs)
            self._desconectar()
            return
        valor = self._combinar_regs(regs)
        with self._lock:
            delta = valor - self._ultimo_contador
            if delta < 0:
                delta += self._max_valor + 1  # wraparound del contador
            if delta > self._max_delta:
                # Reset del modulo / salto anomalo: no contar basura.
                delta = 0
            self._ultimo_contador = valor
            if delta:
                self._cortes += delta
                self._ultimo_corte = time.time()

    def _desconectar(self):
        cliente = self._modbus
        self._modbus = None
        self._conectado = False
        if cliente is not None:
            try:
                cliente.close()
            except Exception:  # noqa: BLE001
                pass

    def conectado(self) -> bool:
        """True si hay enlace Modbus activo (para alerta en la UI)."""
        return self._conectado

    def en_simulacion(self) -> bool:
        """True si el controlador corre sin modulo real (sin alerta UI)."""
        return self._simulacion

    # ------------------------------------------------------------------
    # Contador de cortes
    # ------------------------------------------------------------------

    def _sumar_corte(self, cantidad=1):
        with self._lock:
            self._cortes += cantidad
            self._ultimo_corte = time.time()

    def simular_corte(self):
        """Suma un corte (modo simulacion / pruebas)."""
        self._sumar_corte()

    def segundos_sin_corte(self) -> float:
        with self._lock:
            return time.time() - self._ultimo_corte

    def cortes_totales(self) -> int:
        with self._lock:
            return self._cortes

    def reset_conteo(self):
        with self._lock:
            self._cortes = 0
            self._ultimo_corte = time.time()

    def establecer_conteo(self, total: int):
        """Restaura el contador desde el ultimo checkpoint de la BD."""
        with self._lock:
            self._cortes = int(total)
            self._ultimo_corte = time.time()

    # ------------------------------------------------------------------
    # Relees (pulso momentaneo tipo boton)
    # ------------------------------------------------------------------

    def maquina_lista(self):
        if self._maquina_en_marcha:
            return
        log.info("-> MARCHA: pulso coil START (%s).", self._start_coil)
        self._maquina_en_marcha = True
        self._ultimo_corte = time.time()
        self._pulso_coil(self._start_coil)

    def maquina_pausada(self):
        log.info("-> PARO: pulso coil PAUSE (%s).", self._pause_coil)
        self._maquina_en_marcha = False
        self._pulso_coil(self._pause_coil)

    def reprisar_maquina(self):
        """Reanuda la produccion tras un paro autorizado."""
        self.maquina_lista()

    def maquina_detenida(self) -> bool:
        return not self._maquina_en_marcha

    def _pulso_coil(self, coil):
        """Pulso momentaneo del coil en un hilo de fondo.

        True durante PULSO_DURACION_MS (rele energizado, simula el boton) y
        luego False (rele desenergizado). El lock del socket serializa los
        pulsos y el polling para no solapar dos relevadores. En modo
        simulacion no hay socket: los pulsos son un no-op silencioso.
        """
        if self._simulacion:
            return

        def _pulso():
            with self._lock_modbus:
                cliente = self._modbus
                if not self._conectado or cliente is None:
                    log.warning("Modbus sin conexion: no se pudo pulsar "
                                "el coil %s.", coil)
                    return
                try:
                    cliente.write_single_coil(coil, True)
                    log.info("Coil %s ENCENDIDO (%s ms).", coil, self._pulso_ms)
                    time.sleep(self._pulso_ms / 1000.0)
                    cliente.write_single_coil(coil, False)
                    log.info("Coil %s APAGADO.", coil)
                except Exception as e:  # noqa: BLE001
                    log.warning("Fallo el pulso del coil %s: %s", coil, e)
                    try:
                        cliente.write_single_coil(coil, False)
                    except Exception:  # noqa: BLE001
                        pass
                    self._desconectar()

        threading.Thread(target=_pulso, daemon=True).start()

    # ------------------------------------------------------------------
    # Cierre
    # ------------------------------------------------------------------

    def cleanup(self):
        """Detiene el polling y cierra el socket. Idempotente."""
        if self._cleaned:
            return
        self._cleaned = True
        self._stop.set()
        with self._lock_modbus:
            self._maquina_en_marcha = False
            self._desconectar()
        log.info("ModbusController detenido (hilo de polling finalizado).")

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
    - El rele START es PULSO MOMENTANEO (arranque tipo boton): escribir el
      coil en True durante PULSO_DURACION_MS y volver a False. Nunca dejar
      START energizado.
    - El rele PAUSE es PARO SOSTENIDO (latch, cableado validado en campo):
      `maquina_pausada()` deja el coil en su nivel activo y LO MANTIENE hasta
      que `reprisar_maquina()`/`maquina_lista()` lo vuelve a reposo (la
      maquina queda detenida mientras el rele este activo). Nunca se
      auto-libera: si la app se cierra con la maquina en paro, el rele queda
      energizado y la maquina sigue detenida (estado seguro).
    - Al INICIAR el programa, el controlador deja PAUSE en su nivel activo
      (maquina detenida, "como si estuviera en paro") la primera vez que se
      establece el enlace Modbus; la maquina no arranca hasta que el operador
      la inicia. No se repite en reconexiones posteriores para no parar una
      maquina que ya este en marcha.
    - La polaridad de cada coil es configurable desde .env
      (MODBUS_START_COIL_INVERTIDO / MODBUS_PAUSE_COIL_INVERTIDO): por
      defecto el nivel activo es True (contacto cerrado = boton presionado,
      para botones NA en paralelo); con invertido=1 el nivel activo es False
      (contacto abierto) para cableados donde la maquina actua al abrir
      (boton NA en serie o logica NC).
    - La conexion es defensiva: si la red se cae (cable por vibracion), la UI
      no crashea; el controlador marca `desconectado`, reintenta en segundo
      plano y expone `conectado()` para que la GUI muestre una alerta.

El mapa de registros (coils y registro contador) es CONFIGURABLE desde .env
(MODBUS_START_COIL, MODBUS_PAUSE_COIL, MODBUS_COUNTER_REGISTER) para que un
cambio de modelo/marca del modulo no toque el codigo fuente.

Contrato (identico a SimulacionController):
    - maquina_lista()     -> suelta PARO (si quedo en latch) + pulso START
    - maquina_pausada()   -> latch en coil PAUSE (paro sostenido)
    - reprisar_maquina()  -> reanuda tras autorizar un paro
    - cortes_totales()    -> int (acumulado local)
    - reset_conteo()      -> pone el contador local en 0
    - establecer_conteo(n)-> base desde el ultimo checkpoint de la BD
    - suspender_conteo()  -> excluye cortes nuevos (modo Primera pieza)
    - retomar_conteo()    -> vuelve a contar; los excluidos se pierden
    - incorporar_excluidos() -> confirma los excluidos y reanuda el conteo
    - cortes_excluidos()  -> int (cortes hechos con conteo suspendido)
    - segundos_sin_corte()-> float (alimenta SEGURO_PARO_SEGUNDOS)
    - segundos_desde_arranque()-> float (alimenta PARO_IDLE_TIMEOUT_S)
    - reiniciar_gracia_inactividad() -> reinicia la gracia del auto-paro
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
        self._counter_little_endian = bool(cfg.get("counter_little_endian", True))
        self._poll_ms = int(cfg.get("poll_ms", 500))
        self._pulso_ms = int(cfg.get("pulso_duracion_ms", 300))
        self._max_delta = int(cfg.get("max_delta", 10000))
        self._simulacion = bool(cfg.get("modo_simulacion"))
        self._start_invertido = bool(cfg.get("start_coil_invertido", False))
        self._pause_invertido = bool(cfg.get("pause_coil_invertido", False))

        self._bits = 16 * self._counter_words
        self._max_valor = (1 << self._bits) - 1

        self._lock = threading.Lock()          # estado compartido con la UI
        self._lock_modbus = threading.Lock()   # socket: un request a la vez
        self._stop = threading.Event()

        self._modbus = None
        self._conectado = False
        self._cortes = 0
        self._ultimo_contador = 0
        # Exclusion de cortes (modo "Primera pieza"): con el conteo
        # suspendido los deltas van a `_cortes_excluidos`, NO a `_cortes`.
        # Viven solo en memoria y se pierden al retomar (piezas de prueba/
        # setup que no cuentan como produccion de la sesion).
        self._cortes_excluidos = 0
        self._conteo_suspendido = False
        # `_ultimo_corte` SOLO se actualiza con cortes reales (deltas del
        # contador). `_ultimo_arranque` es la ultima vez que la maquina
        # arranco/reanudo (gracia del auto-paro). Mezclarlos hacia que el
        # seguro anti-corte creyera que habia un corte justo despues de
        # arrancar o reanudar.
        self._ultimo_corte = time.time()
        self._ultimo_arranque = time.time()
        self._maquina_en_marcha = False
        self._pausa_inicial_aplicada = False
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
                self._aplicar_paro_inicial(cliente)
                log.info("Modbus conectado a %s:%s (contador=%s).",
                         self._host, self._port, lectura)
                return True
            except Exception as e:  # noqa: BLE001
                log.warning("Modbus sin conexion (%s).", e)
                self._modbus = None
                self._conectado = False
                return False

    def _combinar_regs(self, regs):
        """Junta los registros de 16 bits en un valor.

        El WISE-4060LAN guarda el valor de 32 bits con la palabra MENOS
        significativa en el primer registro (little-endian: 40001=low,
        40002=high). Configurable con MODBUS_COUNTER_LITTLE_ENDIAN por si un
        modelo distinto usa big-endian (alta primero).
        """
        registros = regs[: self._counter_words]
        if self._counter_little_endian:
            registros = list(reversed(registros))
        valor = 0
        for r in registros:
            valor = (valor << 16) | (r & 0xFFFF)
        return valor

    def _aplicar_paro_inicial(self, cliente):
        """Latch PAUSE en su nivel activo la primera vez que se establece el
        enlace, dejando la maquina detenida (como si estuviera en paro) hasta
        que el operador la inicie.

        Solo se aplica una vez por ejecucion: en reconexiones posteriores la
        maquina podria estar en marcha y no debe pararse por una caida de red.
        """
        if self._pausa_inicial_aplicada:
            return
        try:
            cliente.write_single_coil(
                self._pause_coil, self._nivel_activo(self._pause_invertido)
            )
            self._pausa_inicial_aplicada = True
            log.info("Inicio en PARO: coil PAUSE (%s) latch activo.",
                     self._pause_coil)
        except Exception as e:  # noqa: BLE001
            log.warning("No se pudo latchear PAUSE al iniciar: %s", e)

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
        # Unico punto de acumulacion (aplica la exclusion de Primera pieza).
        if delta:
            self._sumar_corte(delta)

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
        """Unico punto de acumulacion de cortes (polling y simular_corte).

        Con `suspender_conteo()` activo (modo Primera pieza), la cantidad va
        a `_cortes_excluidos`: se muestra aparte pero NUNCA entra a
        `cortes_totales()` ni a la BD, y se pierde al retomar. `_ultimo_corte`
        SIEMPRE se actualiza: son cortes fisicos reales y el seguro
        anti-paro/apagado debe seguir viendo actividad.
        """
        with self._lock:
            self._ultimo_corte = time.time()
            if self._conteo_suspendido:
                self._cortes_excluidos += cantidad
            else:
                self._cortes += cantidad

    def suspender_conteo(self):
        """Empieza a EXCLUIR cortes del total de la sesion (modo Primera
        pieza): se acumulan solo en memoria (`cortes_excluidos`)."""
        with self._lock:
            self._conteo_suspendido = True
            self._cortes_excluidos = 0

    def retomar_conteo(self):
        """Vuelve a contar cortes para la sesion; los excluidos se pierden
        (se descartan las piezas hechas durante Primera pieza)."""
        with self._lock:
            self._conteo_suspendido = False
            self._cortes_excluidos = 0

    def incorporar_excluidos(self):
        """Confirma los cortes excluidos como produccion real y reanuda el
        conteo (corrida iniciada durante Primera pieza, ya autorizada): el
        acumulado temporal pasa al total de la sesion."""
        with self._lock:
            self._cortes += self._cortes_excluidos
            self._cortes_excluidos = 0
            self._conteo_suspendido = False

    def cortes_excluidos(self) -> int:
        """Cortes hechos con el conteo suspendido (solo memoria)."""
        with self._lock:
            return self._cortes_excluidos

    def simular_corte(self):
        """Suma un corte (modo simulacion / pruebas)."""
        self._sumar_corte()

    def segundos_sin_corte(self) -> float:
        with self._lock:
            return time.time() - self._ultimo_corte

    def segundos_desde_arranque(self) -> float:
        """Tiempo desde que la maquina arranco o reanudo (o inf si detenida).

        Alimenta el auto-paro por inactividad: la maquina arranca/reanuda con
        una gracia de `PARO_IDLE_TIMEOUT_S`, independiente de cuando fue el
        ultimo corte real.
        """
        with self._lock:
            if not self._maquina_en_marcha:
                return float("inf")
            return time.time() - self._ultimo_arranque

    def reiniciar_gracia_inactividad(self):
        """Reinicia la gracia del auto-paro por inactividad SIN contar corte
        ni tocar relevadores (p. ej. al salir del modo Primera pieza): el
        timeout vuelve a contar desde cero aunque el ultimo corte sea viejo.
        `_ultimo_corte` NO se toca (alimenta SEGURO_PARO_SEGUNDOS)."""
        with self._lock:
            self._ultimo_arranque = time.time()

    def cortes_totales(self) -> int:
        with self._lock:
            return self._cortes

    def reset_conteo(self):
        with self._lock:
            self._cortes = 0

    def establecer_conteo(self, total: int):
        """Restaura el contador desde el ultimo checkpoint de la BD."""
        with self._lock:
            self._cortes = int(total)

    # ------------------------------------------------------------------
    # Relees: START pulso momentaneo, PAUSE latch (paro sostenido)
    # ------------------------------------------------------------------

    @staticmethod
    def _nivel_activo(invertido):
        """Nivel logico del coil que activa la accion (True o False)."""
        return not invertido

    @staticmethod
    def _nivel_reposo(invertido):
        """Nivel logico del coil en reposo (sin accion)."""
        return invertido

    def maquina_lista(self):
        """Arranca la maquina: suelta el rele de PARO (por si quedo en latch)
        y pulsa START."""
        if self._maquina_en_marcha:
            return
        # El PARO es sostenido: garantizar que este en reposo antes de arrancar
        # (idempotente; tambien cubre recuperacion tras cerrar la app en paro).
        self._escribir_coil(
            self._pause_coil, self._nivel_reposo(self._pause_invertido)
        )
        log.info("-> MARCHA: pulso coil START (%s).", self._start_coil)
        self._maquina_en_marcha = True
        self._ultimo_arranque = time.time()
        self._pulso_coil(self._start_coil, invertido=self._start_invertido)

    def maquina_pausada(self):
        """Para la maquina con PARO SOSTENIDO: deja el coil PAUSE en su nivel
        activo y lo mantiene hasta reanudar (latch)."""
        log.info("-> PARO: latch coil PAUSE (%s) activo.", self._pause_coil)
        self._maquina_en_marcha = False
        self._escribir_coil(
            self._pause_coil, self._nivel_activo(self._pause_invertido)
        )

    def reprisar_maquina(self):
        """Reanuda la produccion tras un paro autorizado (suelta el latch
        PAUSE y pulsa START)."""
        self.maquina_lista()

    def maquina_detenida(self) -> bool:
        return not self._maquina_en_marcha

    def _escribir_coil(self, coil, valor):
        """Escribe el coil y LO MANTIENE en `valor` (latch), en un hilo de
        fondo. No regresa solo a reposo: la transicion la decide el estado de
        la maquina (paro/arranque). En modo simulacion es un no-op silencioso.
        """
        if self._simulacion:
            return

        def _escribir():
            with self._lock_modbus:
                cliente = self._modbus
                if not self._conectado or cliente is None:
                    log.warning("Modbus sin conexion: no se pudo escribir "
                                "el coil %s.", coil)
                    return
                try:
                    cliente.write_single_coil(coil, valor)
                    log.info("Coil %s -> %s (latch).", coil, valor)
                except Exception as e:  # noqa: BLE001
                    log.warning("Fallo escribir el coil %s: %s", coil, e)
                    self._desconectar()

        threading.Thread(target=_escribir, daemon=True).start()

    def _pulso_coil(self, coil, invertido=False):
        """Pulso momentaneo del coil (solo START) en un hilo de fondo.

        Por defecto (invertido=False): True durante PULSO_DURACION_MS (rele
        energizado, contacto cerrado, simula presionar el boton) y luego False
        (rele desenergizado). Con invertido=True se invierte la polaridad:
        el pulso activo es False y el reposo es True (para cableados donde la
        maquina actua cuando el circuito se ABRE; p. ej. boton NA en serie o
        logica NC). El lock del socket serializa los pulsos y el polling para
        no solapar dos relevadores. En modo simulacion no hay socket: los
        pulsos son un no-op silencioso.
        """
        if self._simulacion:
            return

        nivel_activo = self._nivel_activo(invertido)
        nivel_reposo = self._nivel_reposo(invertido)

        def _pulso():
            with self._lock_modbus:
                cliente = self._modbus
                if not self._conectado or cliente is None:
                    log.warning("Modbus sin conexion: no se pudo pulsar "
                                "el coil %s.", coil)
                    return
                try:
                    cliente.write_single_coil(coil, nivel_activo)
                    log.info("Coil %s PULSO (%s ms, activo=%s).", coil,
                             self._pulso_ms, nivel_activo)
                    time.sleep(self._pulso_ms / 1000.0)
                    cliente.write_single_coil(coil, nivel_reposo)
                    log.info("Coil %s a reposo (%s).", coil, nivel_reposo)
                except Exception as e:  # noqa: BLE001
                    log.warning("Fallo el pulso del coil %s: %s", coil, e)
                    try:
                        cliente.write_single_coil(coil, nivel_reposo)
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

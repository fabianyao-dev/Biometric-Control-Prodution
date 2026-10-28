"""
modbus_controller.py - HAL Modbus TCP para la PC Fanless (Windows).

Sustituye a SimulacionController manteniendo EXACTAMENTE la misma interfaz
publica (ver docstring de simulacion_controller.py), para que la GUI jamas se
entere de que el hardware cambio de simulacion a red.

MODOS DE COMANDO (el hardware cambio de modulo Advantech a PLC Zelio):
    - "coil" (por defecto): el PC escribe coils con FC05
      (write_single_coil). Es el caso del modulo Advantech WISE-4060LAN.
    - "registro": el Zelio Logic 2 con modulo Ethernet SR3NET01BD NO
      expone coils, solo 4 palabras de ENTRADA (J1..J4, dirs 16-19, que
      escribe el master) y 4 de SALIDA (O1..O4, dirs 20-23, que lee el
      master). START y PAUSE se escriben como un BIT dentro de una palabra J
      (FC06, write_single_register). La PC es la unica que escribe esas
      palabras, asi que mantiene el valor vigente en memoria y reescribe la
      palabra completa (sin read-modify-write).

Diseno (decisiones de planta):
    - EL CONTADOR DE CORTES VIVE EN EL PLC/MODULO. El hardware cuenta los
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
    - incorporar_excluidos(cantidad=None) -> confirma excluidos (o solo
      `cantidad`) y reanuda el conteo; el resto se descarta
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

    def __init__(self, modbus_config=None, iniciar_polling=True):
        """Controlador del HAL.

        `iniciar_polling=False` deja el controlador sin el hilo de fondo del
        polling (lo usan las pruebas automatizadas, que inyectan un cliente
        falso y comprueban las escrituras a mano).
        """
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

        # Modo de comando: "coil" (FC05, modulo Advantech) o "registro"
        # (FC06, Zelio SR3NET01BD: el comando es un bit de una palabra J).
        self._cmd_mode = str(cfg.get("cmd_mode", "coil")).strip().lower()
        self._start_register = int(cfg.get("start_register", 16))
        self._start_bit = int(cfg.get("start_bit", 0))
        self._pause_register = int(cfg.get("pause_register", 16))
        self._pause_bit = int(cfg.get("pause_bit", 1))

        self._bits = 16 * self._counter_words
        self._max_valor = (1 << self._bits) - 1

        self._lock = threading.Lock()          # estado compartido con la UI
        # RLock (reentrante): `_conectar()` se puede llamar desde dentro de
        # `_secuencia_marcha`, que ya tiene el lock (MARCHA sin enlace).
        self._lock_modbus = threading.RLock()  # socket: un request a la vez
        self._stop = threading.Event()

        self._modbus = None
        self._conectado = False
        self._cortes = 0
        self._ultimo_contador = 0
        # Valor vigente de cada palabra J escrita (modo "registro"): permite
        # poner o quitar un bit sin read-modify-write, porque la PC es la
        # unica que escribe esas palabras.
        self._reg_j = {}
        # Torre de luces (señalizacion): comparte la palabra de comando con
        # MARCHA (bit0) y PARO (bit1), por eso los bits de la torre empiezan
        # en 2. El HAL nunca escribe la palabra completa a cero: siempre
        # preserva los bits que no le pertenecen.
        self._tower_register = int(cfg.get("tower_register", 16))
        self._tower_hb_register = int(cfg.get("tower_heartbeat_register", 19))
        self._tower_green_bit = int(cfg.get("tower_green_bit", 2))
        self._tower_amber_bit = int(cfg.get("tower_amber_bit", 3))
        self._tower_red_bit = int(cfg.get("tower_red_bit", 4))
        self._tower_alarm_bit = int(cfg.get("tower_alarm_bit", 5))
        self._tower_hb_bit = int(cfg.get("tower_heartbeat_bit", 0))
        self._tower_alarm_on_ms = int(cfg.get("tower_alarm_pulso_on_ms", 500))
        self._tower_alarm_off_ms = int(cfg.get("tower_alarm_pulso_off_ms", 500))
        self._tower_alarm_duracion_s = float(cfg.get("tower_alarm_duracion_s", 3))
        self._tower_hb_ms = int(cfg.get("tower_heartbeat_ms", 2000))
        # Estado actual de la torre
        self._torre_verde = False
        self._torre_ambar = False
        self._torre_roja = False
        self._torre_alarma_activa = False
        self._alarma_encendida = False
        self._heartbeat_estado = False
        self._ultimo_hb = time.time()
        self._alarma_inicio = 0.0
        self._alarma_fin = 0.0
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
                if iniciar_polling:
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
                # Fuerza a reescribir J3 aunque el color deseado sea el
                # mismo que ya creia el HAL: tras (re)conectar el PLC pudo
                # quedarse con un estado viejo.
                self._torre_verde = None
                self._torre_ambar = None
                self._torre_roja = None
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

        El hardware publica el valor de 32 bits con la palabra MENOS
        significativa en el primer registro (little-endian: 40001=low,
        40002=high). Configurable con MODBUS_COUNTER_LITTLE_ENDIAN por si el
        PLC lo publica al reves (big-endian: alta primero).
        """
        registros = regs[: self._counter_words]
        if self._counter_little_endian:
            registros = list(reversed(registros))
        valor = 0
        for r in registros:
            valor = (valor << 16) | (r & 0xFFFF)
        return valor

    def _aplicar_paro_inicial(self, cliente):
        """Latch de PARO en su nivel activo la primera vez que se establece
        el enlace, dejando la maquina detenida (como si estuviera en paro)
        hasta que el operador la inicie.

        Solo se aplica una vez por ejecucion: en reconexiones posteriores la
        maquina podria estar en marcha y no debe pararse por una caida de red.
        """
        if self._pausa_inicial_aplicada:
            return
        if self._maquina_en_marcha:
            # El operador ya ordeno MARCHA (p. ej. pulso INICIAR nada mas
            # abrir la app): latchear el PARO aqui lo pisaria y la maquina
            # NO arrancaria. Se marca como aplicado para que una reconexion
            # posterior tampoco latchee el PARO con la maquina en marcha.
            log.info("Inicio en PARO omitido: ya hay MARCHA ordenada.")
            self._pausa_inicial_aplicada = True
            return
        ok = self._escribir_bajo(cliente, self._destino_pause(), True,
                                 self._pause_invertido)
        if ok:
            self._pausa_inicial_aplicada = True
            log.info("Inicio en PARO: %s latch activo.",
                     self._descripcion_pause())
        else:
            log.warning("No se pudo latchear el PARO al iniciar.")

    def _bucle_polling(self):
        """Ciclo de polling: leer contador, sumar delta, reconectar si cae."""
        reintento = 1.0
        ultimo_hb = 0.0
        while not self._stop.is_set():
            if not self._conectado:
                if self._conectar():
                    reintento = 1.0
                else:
                    time.sleep(reintento)
                    reintento = min(reintento * 2, 5.0)
                    continue
            self._poll_contador()
            ahora = time.time()
            if ahora - ultimo_hb >= self._tower_hb_ms / 1000.0:
                self._conmutar_heartbeat()
                ultimo_hb = ahora
            self._gestionar_alarma()
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
        # Al caer el enlace la torre debe quedar sin señal; el heartbeat del
        # PLC la apagara por watchdog. Se marca el estado como DESCONOCIDO
        # (None) para que, al reconectar, el primer `establecer_torre()`
        # reescriba J3 aunque el color deseado sea "apagada" (si no, el PLC
        # se quedaria con el ultimo color que alcanzo a recibir).
        self._torre_verde = None
        self._torre_ambar = None
        self._torre_roja = None
        self._torre_alarma_activa = False
        self._alarma_encendida = False
        self._alarma_fin = 0.0
        # La palabra de la torre es la MISMA que la de los comandos (dir 16):
        # NO se puede borrar del cache, o la siguiente escritura perderia el
        # latch de PARO y la maquina quedaria habilitada. Se limpian solo los
        # bits de la torre y se conservan marcha/paro.
        actual = self._reg_j.get(self._tower_register)
        if actual is not None:
            limpia = actual
            for bit in (self._tower_green_bit, self._tower_amber_bit,
                        self._tower_red_bit, self._tower_alarm_bit):
                limpia = self._con_bit(limpia, bit, False)
            self._reg_j[self._tower_register] = limpia
        self._reg_j.pop(self._tower_hb_register, None)

    def conectado(self) -> bool:
        """True si hay enlace Modbus activo (para alerta en la UI)."""
        return self._conectado

    def reconectar(self) -> bool:
        """Fuerza una reconexion inmediata (cierra el socket y reintenta ya).

        El polling en segundo plano seguiria reintentando de todos modos;
        esto solo adelanta el intento para el boton de reboot. No aplica el
        latch PAUSE inicial si ya se aplico una vez (no para una maquina en
        marcha por una caida de red). Devuelve True si hay enlace.
        """
        if self._simulacion:
            return True
        self._desconectar()
        ok = self._conectar()
        log.info("reconectar Modbus -> %s", "OK" if ok else "sin respuesta")
        return ok

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

    def incorporar_excluidos(self, cantidad=None):
        """Confirma cortes excluidos como produccion real y reanuda el conteo
        (corrida autorizada tras Primera pieza).

        Con `cantidad=None` incorpora TODOS los excluidos. Con una cantidad,
        solo esos pasan al total (p. ej. los de la ventana del seguro
        anti-corrida y posteriores); el resto se DESCARTA (piezas de prueba
        hechas antes de la deteccion).
        """
        with self._lock:
            if cantidad is None:
                n = self._cortes_excluidos
            else:
                n = min(max(int(cantidad), 0), self._cortes_excluidos)
            self._cortes += n
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
    # Salidas: START (pulso momentaneo) y PAUSE (latch sostenido)
    # ------------------------------------------------------------------
    # Dos modos de comando con el MISMO contrato publico:
    #   - "coil"     : modulo Advantech (FC05, write_single_coil).
    #   - "registro" : Zelio SR3NET01BD (FC06, write_single_register): el
    #                  comando es un BIT dentro de una palabra J. START y
    #                  PAUSE pueden vivir en palabras distintas (J1 y J2 por
    #                  defecto) o compartir una misma con bits distintos.

    @staticmethod
    def _nivel_activo(invertido):
        """Nivel logico del coil que activa la accion (True o False)."""
        return not invertido

    @staticmethod
    def _nivel_reposo(invertido):
        """Nivel logico del coil en reposo (sin accion)."""
        return invertido

    @staticmethod
    def _valor_registro(activo, invertido):
        """Valor 1/0 de la palabra segun la polaridad del cableado.

        Sin invertir: la accion es el bit a 1. Invertido (logica NC): la
        accion es el bit a 0.
        """
        if invertido:
            return 0 if activo else 1
        return 1 if activo else 0

    def _destino_start(self):
        """Destino de la salida de MARCHA: ("coil", n) o ("registro", reg, bit)."""
        if self._cmd_mode == "registro":
            return ("registro", self._start_register, self._start_bit)
        return ("coil", self._start_coil)

    def _destino_pause(self):
        """Destino de la salida de PARO: ("coil", n) o ("registro", reg, bit)."""
        if self._cmd_mode == "registro":
            return ("registro", self._pause_register, self._pause_bit)
        return ("coil", self._pause_coil)

    def _descripcion_start(self):
        """Texto legible del destino de MARCHA (para el log)."""
        if self._cmd_mode == "registro":
            return f"registro {self._start_register} bit {self._start_bit}"
        return f"coil {self._start_coil}"

    def _descripcion_pause(self):
        """Texto legible del destino de PARO (para el log)."""
        if self._cmd_mode == "registro":
            return f"registro {self._pause_register} bit {self._pause_bit}"
        return f"coil {self._pause_coil}"

    def maquina_lista(self):
        """Arranca la maquina: suelta el rele de PARO (por si quedo en latch)
        y pulsa START."""
        if self._maquina_en_marcha:
            return
        log.info("-> MARCHA: pulso %s.", self._descripcion_start())
        self._maquina_en_marcha = True
        self._ultimo_arranque = time.time()
        if self._simulacion:
            return
        threading.Thread(target=self._secuencia_marcha, daemon=True).start()

    def _secuencia_marcha(self):
        """Suelta el latch de PARO y luego pulsa START, en ese orden y desde
        un solo hilo.

        El orden importa: si el PARO se soltara DESPUES del pulso, la maquina
        podria no arrancar (el boton de marcha quedaria anterior al de paro).
        """
        with self._lock_modbus:
            cliente = self._modbus
            if cliente is None or not self._conectado:
                # Todavia no hay enlace (el operador pulsa MARCHA nada mas
                # abrir la app): se conecta aqui o la orden se perderia.
                log.info("MARCHA sin enlace: se intenta conectar.")
                if not self._conectar():
                    log.warning("Modbus sin conexion: no se pudo arrancar.")
                    return
                cliente = self._modbus
            # 1) PARO a reposo (idempotente; tambien cubre la recuperacion
            #    tras cerrar la app con la maquina en paro).
            self._escribir_bajo(cliente, self._destino_pause(), False,
                                self._pause_invertido)
            # 2) Pulso de MARCHA.
            self._pulso_bajo(cliente, self._destino_start(),
                              self._start_invertido, self._pulso_ms)

    def maquina_pausada(self):
        """Para la maquina con PARO SOSTENIDO: deja la salida de PARO en su
        nivel activo y lo mantiene hasta reanudar (latch)."""
        log.info("-> PARO: latch %s activo.", self._descripcion_pause())
        self._maquina_en_marcha = False
        if self._simulacion:
            return
        destino = self._destino_pause()
        invertido = self._pause_invertido

        def _escribir():
            with self._lock_modbus:
                cliente = self._modbus
                if cliente is None or not self._conectado:
                    log.warning("Modbus sin conexion: no se pudo escribir "
                                "la salida de PARO.")
                    return
                self._escribir_bajo(cliente, destino, True, invertido)

        threading.Thread(target=_escribir, daemon=True).start()

    def reprisar_maquina(self):
        """Reanuda la produccion tras un paro autorizado (suelta el latch
        PAUSE y pulsa START)."""
        self.maquina_lista()

    def maquina_detenida(self) -> bool:
        return not self._maquina_en_marcha

    # ------------------------------------------------------------------
    # Escrituras de bajo nivel (el socket ya esta bloqueado por el
    # llamador: el hilo de polling y las acciones comparten el lock)
    # ------------------------------------------------------------------

    @staticmethod
    def _con_bit(palabra, bit, puesto):
        """Devuelve `palabra` con el bit indicado puesto o quitado."""
        if puesto:
            return (palabra | (1 << bit)) & 0xFFFF
        return palabra & ~(1 << bit) & 0xFFFF

    def _palabra_con_bit(self, registro, bit, puesto):
        """Valor de la palabra J con el bit puesto (o quitado).

        El cache local evita el read-modify-write: la PC es la unica que
        escribe las palabras J, asi que puede mantener el valor vigente en
        memoria y reescribir la palabra completa.
        """
        return self._con_bit(self._reg_j.get(registro, 0), bit, puesto)

    def _escribir_bajo(self, cliente, destino, activa, invertido):
        """Escribe el estado de una salida y lo MANTIENE (latch).

        `activa` es la intencion LOGICA (True = arrancar / parar, False =
        reposo). `invertido` invierte la polaridad del cableado. Devuelve
        True si la escritura se confirmo.
        """
        if destino[0] == "registro":
            bit_puesto = self._valor_registro(activa, invertido) == 1
            return self._escribir_registro_bajo(cliente, destino[1],
                                                 destino[2], bit_puesto)
        nivel = (self._nivel_activo(invertido) if activa
                 else self._nivel_reposo(invertido))
        return self._escribir_coil_bajo(cliente, destino[1], nivel)

    def _escribir_coil_bajo(self, cliente, coil, valor):
        """Escribe un coil. pyModbusTCP devuelve False ante cualquier error
        sin lanzar excepcion, asi que se verifica el retorno."""
        try:
            ok = cliente.write_single_coil(coil, valor)
        except Exception as e:  # noqa: BLE001
            log.warning("Fallo escribir el coil %s: %s", coil, e)
            self._desconectar()
            return False
        if not ok:
            log.error("El modulo rechazo escribir el coil %s.", coil)
            self._desconectar()
            return False
        log.info("Coil %s -> %s (latch).", coil, valor)
        return True

    def _escribir_registro_bajo(self, cliente, registro, bit, puesto):
        """Escribe un bit de una palabra J (Zelio SR3NET01BD)."""
        palabra = self._palabra_con_bit(registro, bit, puesto)
        try:
            ok = cliente.write_single_register(registro, palabra)
        except Exception as e:  # noqa: BLE001
            log.warning("Fallo escribir el registro %s: %s", registro, e)
            self._desconectar()
            return False
        if not ok:
            log.error("El modulo rechazo escribir el registro %s.", registro)
            self._desconectar()
            return False
        self._reg_j[registro] = palabra
        log.info("Registro %s -> %s (bit %s = %s).", registro, palabra, bit,
                 puesto)
        return True

    def _pulso_bajo(self, cliente, destino, invertido, duracion_ms):
        """Pulso momentaneo de una salida (solo MARCHA): activa, espera y
        vuelve a reposo."""
        if destino[0] == "registro":
            bit_activo = self._valor_registro(True, invertido) == 1
            if not self._escribir_registro_bajo(cliente, destino[1],
                                                  destino[2], bit_activo):
                return False
            time.sleep(duracion_ms / 1000.0)
            return self._escribir_registro_bajo(cliente, destino[1],
                                                 destino[2], not bit_activo)
        nivel_activo = self._nivel_activo(invertido)
        nivel_reposo = self._nivel_reposo(invertido)
        if not self._escribir_coil_bajo(cliente, destino[1], nivel_activo):
            return False
        time.sleep(duracion_ms / 1000.0)
        return self._escribir_coil_bajo(cliente, destino[1], nivel_reposo)

    # ------------------------------------------------------------------
    # Torre de luces (J3) y heartbeat (J4)
    # ------------------------------------------------------------------

    def establecer_torre(self, verde=False, ambar=False, roja=False):
        """Fija el estado de la torre. Idempotente: repetir el mismo estado
        no genera trafico Modbus.

        La vista Inicio decide el color; aqui solo se ejecuta. Una sola
        escritura por cambio (los tres bits van en la MISMA palabra J).
        """
        verde, ambar, roja = bool(verde), bool(ambar), bool(roja)
        if (self._torre_verde == verde and self._torre_ambar == ambar
                and self._torre_roja == roja):
            return
        self._torre_verde = verde
        self._torre_ambar = ambar
        self._torre_roja = roja
        if self._simulacion or not self._conectado or self._modbus is None:
            return
        palabra = self._reg_j.get(self._tower_register, 0)
        palabra = self._con_bit(palabra, self._tower_green_bit, verde)
        palabra = self._con_bit(palabra, self._tower_amber_bit, ambar)
        palabra = self._con_bit(palabra, self._tower_red_bit, roja)
        cliente = self._modbus
        with self._lock_modbus:
            self._escribir_registro_torre(cliente, self._tower_register,
                                          palabra)
        log.info("Torre: verde=%s ambar=%s roja=%s (reg %s = %s).",
                 verde, ambar, roja, self._tower_register, palabra)

    def _escribir_registro_torre(self, cliente, registro, palabra):
        """Escribe una palabra J de la torre.

        Un fallo aqui NO desconecta ni detiene la maquina: la torre es
        senalizacion, no seguridad. Se registra y se reintenta al siguiente
        cambio de estado.
        """
        try:
            ok = cliente.write_single_register(registro, palabra)
        except Exception as e:  # noqa: BLE001
            log.warning("Torre: fallo escribir registro %s: %s", registro, e)
            return False
        if not ok:
            log.warning("Torre: el modulo rechazo el registro %s.", registro)
            return False
        self._reg_j[registro] = palabra
        return True

    def _escribir_bit_torre(self, cliente, bit, puesto):
        palabra = self._palabra_con_bit(self._tower_register, bit, puesto)
        return self._escribir_registro_torre(cliente, self._tower_register,
                                             palabra)

    def _apagar_torre_bajo(self, cliente):
        """Apaga los bits de la torre PRESERVANDO el resto de la palabra.

        La palabra de la torre es la MISMA que la de los comandos (dir 16 en
        el PLC real), asi que escribir 0 ahi borraria el latch de PARO y
        dejaria la maquina potencialmente habilitada. Se limpian solo los
        cuatro bits de la torre y se conservan marcha (bit0) y paro (bit1).
        """
        actual = self._reg_j.get(self._tower_register, 0)
        palabra = actual
        for bit in (self._tower_green_bit, self._tower_amber_bit,
                    self._tower_red_bit, self._tower_alarm_bit):
            palabra = self._con_bit(palabra, bit, False)
        if palabra == actual:
            return True
        return self._escribir_registro_torre(cliente, self._tower_register,
                                             palabra)

    def _escribir_alarma(self, encendida):
        """Enciende o apaga el bit de alarma de la torre."""
        self._alarma_encendida = bool(encendida)
        if self._simulacion or not self._conectado or self._modbus is None:
            return
        cliente = self._modbus
        with self._lock_modbus:
            self._escribir_bit_torre(cliente, self._tower_alarm_bit,
                                     self._alarma_encendida)

    def pulso_alarma(self):
        """Arranca la alarma discontinua (solo al ENTRAR en rojo).

        El parpadeo lo ejecuta `_gestionar_alarma()` desde el hilo de
        polling; aqui solo se abre la ventana de tiempo. Es idempotente
        mientras la ventana siga abierta.
        """
        if self._torre_alarma_activa:
            return
        self._torre_alarma_activa = True
        self._alarma_inicio = time.time()
        self._alarma_fin = self._alarma_inicio + self._tower_alarm_duracion_s
        self._alarma_encendida = False
        log.info("Torre: alarma discontinua durante %.1f s.",
                 self._tower_alarm_duracion_s)

    def _gestionar_alarma(self):
        """Parpadea el bit de alarma mientras dure la ventana.

        Conmutar en cada tick (en vez de calcular la fase) garantiza que la
        senal sea DISCONTINUA aunque el sondeo no caiga exacto: con
        `_poll_ms` de 500 ms el resultado es 500 ms encendida / 500 ms
        apagada, que es justo el requisito.
        """
        if not self._torre_alarma_activa:
            return
        if time.time() >= self._alarma_fin:
            self._torre_alarma_activa = False
            self._escribir_alarma(False)
            log.info("Torre: fin de la alarma.")
            return
        self._escribir_alarma(not self._alarma_encendida)

    def _conmutar_heartbeat(self):
        """Conmuta el heartbeat de J4 para el watchdog del PLC."""
        if self._simulacion or not self._conectado or self._modbus is None:
            return
        palabra = self._palabra_con_bit(self._tower_hb_register,
                                       self._tower_hb_bit,
                                       not self._heartbeat_estado)
        cliente = self._modbus
        with self._lock_modbus:
            ok = self._escribir_registro_torre(cliente,
                                               self._tower_hb_register,
                                               palabra)
        if ok:
            self._heartbeat_estado = not self._heartbeat_estado
            self._ultimo_hb = time.time()

    # ------------------------------------------------------------------
    # Cierre
    # ------------------------------------------------------------------

    def cleanup(self):
        """Detiene el polling, ASEGURA el paro y cierra el socket. Idempotente.

        La maquina NUNCA debe quedar cortando sin supervision al morir la
        app: si hay enlace vivo se escribe el latch de PARO (paro sostenido)
        ANTES de desconectar. Con la maquina ya detenida re-latchear es
        inocuo (la salida queda energizada, su estado seguro desde el
        arranque). La escritura es SINCRONA bajo `_lock_modbus`, asi que
        espera a que un pulso START en vuelo termine antes de tocar el PARO;
        se verifica el retorno porque pyModbusTCP devuelve False ante
        cualquier error sin lanzar (ver Diagnostico 7.2.1).
        """
        if self._cleaned:
            return
        self._cleaned = True
        self._stop.set()
        with self._lock_modbus:
            cliente = self._modbus
            if (not self._simulacion and self._conectado
                    and cliente is not None):
                ok = self._escribir_bajo(cliente, self._destino_pause(),
                                         True, self._pause_invertido)
                if ok:
                    log.info("Cierre seguro: %s latch activo; maquina "
                             "asegurada en paro.", self._descripcion_pause())
                else:
                    log.error("Cierre: no se pudo asegurar el PARO (%s); "
                              "VERIFICAR LA MAQUINA MANUALMENTE.",
                              self._descripcion_pause())
                # Apagar la torre y el heartbeat al cerrar la app: la torre
                # no debe quedar encendida sin supervision. La torre vive en
                # la MISMA palabra que los comandos, asi que se limpian solo
                # sus bits (escribir 0 borraria el latch de PARO recien
                # puesto). El heartbeat sí se deja en cero.
                self._apagar_torre_bajo(cliente)
                self._escribir_registro_torre(cliente, self._tower_hb_register,
                                              0)
            self._maquina_en_marcha = False
            self._desconectar()
        log.info("ModbusController detenido (hilo de polling finalizado).")

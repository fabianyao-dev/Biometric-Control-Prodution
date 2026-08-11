"""
gpio_controller.py - Capa de abstraccion de pines (HAL) de la Raspberry Pi.

Aisla RPi.GPIO del resto de la aplicacion: la GUI jamas toca pines directo.
Unifica el corte de los reles y el contador de cortes. Si el hardware no esta
disponible, cae en modo simulacion (sin RPi.GPIO) para desarrollarse en el PC.

Circuito TIPO BOTON (pulso momentaneo): los relevadores ya no se mantienen
energizados; cada accion envia UN PULSO de PULSO_DURACION_MS como si se
presionara un pulsador, y el contactor se engancha solo. Pulso activo-bajo
(con el modulo alimentado a 5V):

    - ENVIAR PULSO = pin como SALIDA y escribir LOW (bobina energizada)
      durante la duracion configurada y, al terminar, volver el pin a ENTRADA
      (alta impedancia), cortando la corriente del optoacoplador. En algunos
      modulos el HIGH de 3.3V no alcanza a cortar la corriente; poner el pin
      en INPUT lo libera de forma confiable.

Los pulsos se envian en un hilo de fondo para no congelar la GUI y quedan
serializados (nunca hay dos relevadores energizados al mismo tiempo).

Contrato:
    - maquina_lista()   -> pulso en relé START (arranca)
    - maquina_pausada() -> pulso en relé PAUSE (paro)
    - reprisar()        -> reanuda tras autorizar un paro
    - cortes_totales()  -> int (contador de pulsos del sensor optoacoplado)
    - reset_conteo()    -> pone el contador en 0
    - cleanup()         -> libera GPIO (los pulsos son momentaneos; siempre!)
"""

import logging
import threading
import time

from src import config

log = logging.getLogger(__name__)


class GpioController:
    """Controlador de reles y contador de cortes sobre RPi.GPIO."""

    def __init__(self, gpio_config=None):
        cfg = dict(gpio_config or config.GPIO_CONFIG)

        self._pin_start = cfg.get("rele_start")
        self._pin_pause = cfg.get("rele_pause")
        self._pin_sensor = cfg.get("sensor_corte")
        self._bounce = int(cfg.get("conteo_bouncetime_ms", 50))
        self._pulso_ms = int(cfg.get("pulso_duracion_ms", 300))

        self._lock = threading.Lock()
        self._pulso_lock = threading.Lock()
        self._cortes = 0
        self._ultimo_corte = time.time()
        self._maquina_en_marcha = False
        self._simulacion = bool(cfg.get("modo_simulacion"))

        self._gpio = None
        if not self._simulacion:
            self._inicializar()

    # ------------------------------------------------------------------
    # Backend
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

    def _inicializar(self):
        """Configura RPi.GPIO. Con fallback de sim si no hay hardware."""
        try:
            import RPi.GPIO as GPIO

            GPIO.setmode(GPIO.BCM)
            GPIO.setwarnings(False)

            # Reles ACTIVOS-BAJO: bobina energizada con LOW. Estado seguro al
            # arrancar: ambos en INPUT (alta impedancia) = corriente cortada =
            # rele DESACTIVADO. No escribir HIGH: en algunos modulos 3.3V no
            # corta la corriente y el rele queda "siempre encendido".
            GPIO.setup(self._pin_start, GPIO.IN)
            GPIO.setup(self._pin_pause, GPIO.IN)
            self._maquina_en_marcha = False
            log.info("Arranque: relees en INPUT (apagados). "
                     "start=%s|IN pause=%s|IN (sensor=%s)",
                     self._pin_start, self._pin_pause, self._pin_sensor)

            # Sensor de corte: entrada con pull-down (pulso activo alto)
            GPIO.setup(self._pin_sensor, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
            GPIO.add_event_detect(
                self._pin_sensor, GPIO.RISING,
                callback=self._sumar_corte, bouncetime=self._bounce,
            )

            self._gpio = GPIO
            log.info("GPIO listo (start=%s pause=%s sensor=%s)",
                     self._pin_start, self._pin_pause, self._pin_sensor)
        except Exception as e:  # noqa: BLE001
            self._gpio = None
            self._simulacion = True
            log.warning("GPIO no disponible (%s). Modo simulacion activo.", e)

    # ------------------------------------------------------------------
    # Contador de cortes
    # ------------------------------------------------------------------

    def _sumar_corte(self, channel=None):
        with self._lock:
            self._cortes += 1
            self._ultimo_corte = time.time()

    def segundos_sin_corte(self) -> float:
        """Segundos transcurridos desde el ultimo pulso del sensor."""
        with self._lock:
            return time.time() - self._ultimo_corte

    def simular_corte(self):
        """Suma un corte (usado por la GUI en modo simulacion / pruebas)."""
        self._sumar_corte()

    def cortes_totales(self) -> int:
        with self._lock:
            return self._cortes

    def reset_conteo(self):
        with self._lock:
            self._cortes = 0
            self._ultimo_corte = time.time()

    def establecer_conteo(self, total: int):
        """Restaura el contador desde el ultimo checkpoint de la BD.

        Se usa al retomar una sesion interrumpida: los cortes de los sensores
        se siguen sumando sobre este total como base.
        """
        with self._lock:
            self._cortes = int(total)
            self._ultimo_corte = time.time()

    # ------------------------------------------------------------------
    # Reles
    # ------------------------------------------------------------------

    def maquina_lista(self):
        """Envia un pulso a relé START (arranque tipo boton).

        El pulso es momentaneo: el contactor se engancha solo. Los pulsos se
        serializan, de modo que jamas quedan START y PAUSE energizados a la
        vez (evita dejar el contactor enganchado).
        """
        if self._maquina_en_marcha:
            return
        log.info("-> MARCHA: pulso RELE_ENCENDIDO (start_pin=%s)", self._pin_start)
        self._enviar_pulso(self._pin_start)
        self._maquina_en_marcha = True
        self._ultimo_corte = time.time()
        log.info("Maquina INICIADA (pulso enviado)")

    def maquina_pausada(self):
        """Envia un pulso a relé PAUSE (paro tipo boton)."""
        log.info("-> PARO: pulso RELE_PARO (pause_pin=%s)", self._pin_pause)
        self._enviar_pulso(self._pin_pause)
        self._maquina_en_marcha = False
        log.info("Maquina en PARO (pulso enviado)")

    def reprisar_maquina(self):
        """Reanuda la produccion tras un paro autorizado."""
        self.maquina_lista()

    def maquina_detenida(self) -> bool:
        return not self._maquina_en_marcha

    def _enviar_pulso(self, pin):
        """Envia un pulso momentaneo al rele en un hilo de fondo.

        LOW durante PULSO_DURACION_MS (bobina energizada) y despues el pin
        vuelve a ENTRADA (alta impedancia), cortando la corriente. El lock de
        pulsos serializa las acciones para que no se solapen dos relevadores.
        """
        def _pulso():
            with self._pulso_lock:
                if pin is None or self._gpio is None:
                    return
                try:
                    rele = self._nombre_rele(pin)
                    self._gpio.setup(pin, self._gpio.OUT)
                    self._gpio.output(pin, self._gpio.LOW)
                    log.info("%s PULSO inicio (pin=%s | OUT/LOW, %s ms)",
                             rele, pin, self._pulso_ms)
                    time.sleep(self._pulso_ms / 1000.0)
                    self._gpio.setup(pin, self._gpio.IN)
                    log.info("%s PULSO fin (pin=%s | INPUT, corriente cortada)",
                             rele, pin)
                except Exception as e:  # noqa: BLE001
                    log.warning("Fallo al enviar pulso en pin %s: %s", pin, e)

        threading.Thread(target=_pulso, daemon=True).start()

    # ------------------------------------------------------------------
    # Cierre
    # ------------------------------------------------------------------

    def cleanup(self):
        """Libera los pines GPIO. Idempotente.

        Espera a que termine cualquier pulso en vuelo (max. PULSO_DURACION_MS)
        y deja los pines en estado seguro (INPUT / alta impedancia). Los pulsos
        son momentaneos, asi que no hay bobinas que desenergizar.
        """
        if getattr(self, "_cleaned", False):
            return
        self._cleaned = True
        with self._pulso_lock:
            self._maquina_en_marcha = False
            if self._gpio is not None:
                try:
                    self._gpio.setup(self._pin_start, self._gpio.IN)
                    self._gpio.setup(self._pin_pause, self._gpio.IN)
                    self._gpio.cleanup()
                except Exception as e:  # noqa: BLE001
                    log.warning("RPi.GPIO.cleanup fallo: %s", e)
        self._gpio = None
        log.info("GPIO liberado, pines en INPUT (estado seguro)")
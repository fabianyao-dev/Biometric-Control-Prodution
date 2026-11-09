"""Seguros de operacion y torre de luces (SeguridadMixin).

Vigila el auto-paro por inactividad y las rafagas de cortes (alarma y
confirmacion por huella), calcula la tolerancia de paro y decide el color y el
parpadeo de la torre. El HAL solo escribe los bits; la decision es de la GUI.
"""

import logging
import math
import threading
import time
from collections import deque
from datetime import datetime, timedelta

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from src import config
from src.database import (
    ESTADO_CERRADO,
    abrir_sesion,
    abrir_trabajo,
    actualizar_cortes_sesion,
    actualizar_detectados,
    ahora_local,
    cerrar_sesion,
    cerrar_trabajo_modalidad,
    confirmar_trabajo_por_apagon,
    crear_paro_por_apagon,
    finalizar_paro,
    iniciar_paro,
    listar_causas_paro,
    obtener_rol_operador,
    obtener_sesion_interrumpida,
    obtener_trabajo_abierto,
    paro_en_curso,
    pausar_trabajo,
    recortar_inicio_segmento,
    registrar_ultimo_corte,
    rol_tiene_permiso_operador,
    roles_con_permiso,
)
from src.gui.componentes.huella_modal import HuellaModal
from ..componentes.selector_causas import SelectorCausaZona
from ..componentes.modalidades_cierre import (
    MODALIDAD_FOLIO,
    ModalidadCierreDialog,
)
from src.gui.componentes.resplandor import Resplandor
from src.gui.componentes.switch import Switch
from src.gui.style import aplicar_estado, aplicar_estilo_boton

log = logging.getLogger(__name__)




class SeguridadMixin:

    def _actualizar_tolerancia_paro(self):
        """Ancla (y rearma) el comienzo del paro para la torre de luces.

        La torre pasa de ambar a ROJA cuando el paro lleva mas de
        `PRIMERA_PIEZA_TIMEOUT_S` (la "tolerancia de paro" del .env). El
        ancla se toma en cuanto hay un paro real, sin importar su origen
        (PARO manual, auto-paro por inactividad, modo PARO, Mantenimiento o
        Primera pieza); se rearma cuando el paro se RESUELVE, para que la
        alarma suene en el SIGUIENTE paro.

        OJO: la maquina puede seguir EN MARCHA durante el paro (zona con
        'maquina encendida', Mantenimiento o Primera pieza). El ancla NO se
        borra por eso: si se borrara, la tolerancia no venceria nunca en
        esos paros y la roja + buzzer no llegarian a activarse.
        """
        if self.sesion_id is None or not self._paro_real_abierto():
            self._paro_inicio_momento = None
            return
        if self._paro_inicio_momento is None:
            self._paro_inicio_momento = time.time()

    def _momento_ultimo_corte(self):
        """Timestamp local del ultimo corte real, o None si el HAL no lo da."""
        ts = self._segundos_desde(self.controlador.segundos_sin_corte)
        return ts

    def _momento_ultimo_arranque(self):
        """Timestamp local del ultimo arranque/reanudacion, o None si la
        maquina esta DETENIDA (el HAL devuelve inf) o no expone el dato."""
        return self._segundos_desde(self.controlador.segundos_desde_arranque)

    def _segundos_desde(self, getter):
        """Convierte 'hace N segundos' (o None) a timestamp local 'YYYY-MM-DD
        HH:MM:SS'. Devuelve None si el dato no es medible.

        `segundos_desde_arranque` devuelve `inf` con la maquina DETENIDA, y
        `timedelta(seconds=inf)` lanza OverflowError: sin filtrarlo aqui, el
        checkpoint revienta justo en `_momento_ultimo_arranque` (reportado en
        produccion con la maquina apagada).
        """
        try:
            segundos = float(getter())
        except Exception:  # noqa: BLE001 - un checkpoint no debe fallar
            log.debug("El HAL no expone segundos desde un evento", exc_info=True)
            return None
        if not math.isfinite(segundos) or segundos < 0:
            return None
        ahora = datetime.strptime(ahora_local(), "%Y-%m-%d %H:%M:%S")
        return (ahora - timedelta(seconds=segundos)).strftime("%Y-%m-%d %H:%M:%S")

    def _verificar_inactividad(self):
        timeout = config.PARO_IDLE_TIMEOUT_S
        if not timeout or timeout <= 0:
            return
        if (self.sesion_id is None or self._paro_idle_triggado
                or self._modal_abierto or self._en_paro
                or self._primera_pieza or self._modo_mantenimiento):
            return
        if not self._maquina_en_marcha():
            return
        # Inactividad = tiempo desde el evento mas reciente (arranque/reanuda
        # o ultimo corte real). Usar `min` da la gracia completa tras
        # arrancar/reanudar: si el ultimo corte fue hace mucho pero la maquina
        # acaba de reanudar, el contador empieza desde el arranque.
        sin_corte = self.controlador.segundos_sin_corte()
        desde_arranque = getattr(
            self.controlador, "segundos_desde_arranque", lambda: float("inf")
        )()
        ancla = min(sin_corte, desde_arranque)
        if ancla >= timeout:
            self._paro_idle_triggado = True
            log.info("Sin cortes por %s s; abriendo paro automatico "
                     "(inicio retrotraido %s s)", timeout, ancla)
            # El paro se contabiliza desde el ancla (ultimo corte o salida
            # del ultimo evento), no desde aqui: el minuto muerto cuenta.
            self._pausar_maquina(motivo="automatico", inicio_hace_s=ancla)

    def _seguro_paro_segundos(self):
        """Segundos restantes del seguro anti-corte, o None si se puede actuar.

        Bloquea PARO/APAGAR mientras la maquina este en marcha y se haya
        recibido un corte REAL dentro de los ultimos `SEGURO_PARO_SEGUNDOS`
        (la maquina sigue cortando). Arrancar/reanudar NO cuenta como corte.
        """
        if self._maquina_en_marcha():
            restante = (
                config.SEGURO_PARO_SEGUNDOS
                - self.controlador.segundos_sin_corte()
            )
            if restante > 0:
                return restante
        return None

    def _conteo_paro_suspendido(self):
        """True si el paro actual excluye los cortes del total (Primera
        pieza, Mantenimiento o MODO PARO con zona 'maquina encendida')."""
        return bool(
            self._primera_pieza
            or self._modo_mantenimiento
            or (self._modo_paro and self._modo_paro_maquina_encendida)
        )

    def _total_fisico(self):
        """Contador fisico monotono de cortes: totales + excluidos.

        Sirve para detectar rafagas tanto con el conteo normal como con el
        suspendido. `incorporar_excluidos()` mueve cortes de excluidos a
        totales sin alterar la suma, asi que el contador no retrocede al
        confirmar una corrida.
        """
        return (int(self.controlador.cortes_totales())
                + int(self.controlador.cortes_excluidos()))

    def _pulso_buzzer_plc(self):
        """Pulso del buzzer fisico de la torre (Q6). Nunca rompe la UI."""
        try:
            if hasattr(self.controlador, "pulso_alarma"):
                self.controlador.pulso_alarma()
        except Exception:  # noqa: BLE001 - sin buzzer no debe fallar nada
            log.debug("pulso_alarma fallo", exc_info=True)

    def _etiqueta_paro_actual(self):
        """Nombre legible del paro/modo activo para los mensajes del seguro."""
        if self._modo_mantenimiento:
            return "Mantenimiento"
        if self._primera_pieza:
            return "Primera pieza"
        if self._modo_paro:
            return "MODO PARO"
        return "PARO"

    def _rearmar_rafaga(self):
        """Limpia la ventana del seguro anti-corrida al salir de un paro."""
        self._muestras_rafaga.clear()
        self._ultimo_total_fisico = None
        self._rafaga_en_curso = False
        self._excluidos_previos_rafaga = 0

    def _verificar_rafaga_arranque(self):
        """Detecta una corrida no autorizada durante CUALQUIER paro real.

        Con el conteo normal o suspendido, si dentro de
        SEGURO_RAFAGA_SEGUNDOS entran mas de SEGURO_RAFAGA_CORTES cortes
        fisicos (totales + excluidos), suena el buzzer de la torre y pregunta
        al operador si la maquina ya empezo a correr; al confirmar y
        autorizar por huella (doble en Mantenimiento), los cortes de la
        ventana pasan al conteo y el paro se resuelve.
        """
        ventana = config.SEGURO_RAFAGA_SEGUNDOS
        umbral = config.SEGURO_RAFAGA_CORTES
        if not ventana or ventana <= 0 or umbral <= 0:
            return
        # En Primera pieza, si el operador de la sesion tiene el permiso
        # `iniciar_primera_pieza` la corrida SIN folio esta AUTORIZADA: el
        # anti-corrida no aplica. Con TRABAJO cargado el anti-corrida SI
        # corre para detectar la corrida y salir del modo (el conteo del
        # folio arranca al confirmar). En MANTENIMIENTO nunca se suprime.
        if (self._primera_pieza and self._trabajo is None
                and self._tiene_permiso_iniciar_primera_pieza()):
            self._rearmar_rafaga()
            return
        # Solo vigila paros REALES: paro manual/automatico, MODO PARO,
        # Mantenimiento y Primera pieza. La espera de trabajo no es un paro
        # que resolver y no debe disparar la alarma.
        if not self._paro_real_abierto() or self.sesion_id is None:
            self._rearmar_rafaga()
            return
        if self._modal_abierto:
            return  # Otro modal en curso; evaluar al cerrarse.
        actual = self._total_fisico()
        if self._ultimo_total_fisico is None:
            self._ultimo_total_fisico = actual
            return
        delta = actual - self._ultimo_total_fisico
        self._ultimo_total_fisico = actual
        ahora = time.time()
        if delta > 0:
            self._muestras_rafaga.append((ahora, delta))
        elif delta < 0:
            # Reinicio del contador fisico (inicio de sesion o cambio de
            # modalidad de conteo): baseline nuevo.
            self._muestras_rafaga.clear()
        limite = ahora - ventana
        while self._muestras_rafaga and self._muestras_rafaga[0][0] < limite:
            self._muestras_rafaga.popleft()
        en_ventana = sum(n for _, n in self._muestras_rafaga)
        if en_ventana <= umbral:
            self._rafaga_en_curso = False  # La rafaga cedio: rearmar.
            return
        if self._rafaga_en_curso:
            return  # Ya se pregunto por esta rafaga; no insistir.
        self._rafaga_en_curso = True
        # Lo cortado ANTES de la ventana son piezas de prueba: al confirmar
        # la corrida solo se incorporan los de la ventana en adelante
        # (incluidos los que ocurran mientras el modal esta abierto).
        if self._conteo_paro_suspendido():
            self._excluidos_previos_rafaga = max(
                int(self.controlador.cortes_excluidos()) - en_ventana, 0
            )
        else:
            self._excluidos_previos_rafaga = 0
        etiqueta = self._etiqueta_paro_actual()
        log.warning("Rafaga en %s: %s cortes en %s s "
                    "(%s previos quedan como prueba)",
                    etiqueta, en_ventana, ventana,
                    self._excluidos_previos_rafaga)
        self._pulso_buzzer_plc()
        self._sonar_alarma()
        self._preguntar_corrida(en_ventana, ventana)

    def _sonar_alarma(self):
        """Patron de beeps de atencion en hilo aparte (no bloquea la GUI).

        Se usa para el seguro anti-corrida y para avisar que un trabajo
        alcanzo su cantidad total.
        """

        def _sonar():
            try:
                import winsound
                for _ in range(4):
                    winsound.Beep(950, 220)
                    winsound.Beep(1400, 220)
            except Exception:  # noqa: BLE001 - sin sonido no debe fallar nada
                pass

        threading.Thread(target=_sonar, daemon=True).start()

    def _preguntar_corrida(self, n_cortes, ventana):
        """Modal '¿Ya empezo a correr?' del seguro anti-corrida."""
        modo = self._etiqueta_paro_actual()
        self._modal_abierto = True
        try:
            caja = QMessageBox(self.controller)
            caja.setWindowTitle("Posible corrida sin conteo")
            caja.setIcon(QMessageBox.Warning)
            caja.setText(
                f"Se detectaron {n_cortes} cortes en los ultimos {ventana} "
                f"segundos con el modo {modo} activo.\n\n"
                "¿Ya empezo a correr la maquina?"
            )
            btn_si = caja.addButton("Sí", QMessageBox.YesRole)
            caja.addButton("No", QMessageBox.NoRole)
            caja.exec()
            if caja.clickedButton() is btn_si:
                self._abrir_huella_corrida()
            else:
                log.info("Corrida descartada por el operador (%s sigue activo)",
                         modo)
                self._estado(
                    "Corrida descartada: los cortes siguen fuera del conteo.",
                    "info",
                )
        finally:
            self._modal_abierto = False

    def _abrir_huella_corrida(self):
        """Autorizacion por huella para contar la corrida detectada.

        En Mantenimiento PRIMERO el personal de mantenimiento y LUEGO el
        operador; en Primera pieza y en el PARO/MODO PARO solo el operador
        (dueno de la sesion o Supervisor/Admin)."""
        if self._modo_mantenimiento:
            self._pedir_huella_mantenimiento(
                self._corrida_mantenimiento_paso_operador,
                titulo="REANUDACION MANTENIMIENTO"
            )
            return
        if self._primera_pieza:
            modal = HuellaModal(
                self.controller,
                self.biometrico,
                titulo="CONFIRMAR CORRIDA",
                mensaje="Coloca tu huella para contar estos cortes como "
                        "produccion de la sesion.",
                validador=self._validar_autorizacion_paro,
                on_autenticado=self._corrida_confirmada,
                on_cancelar=lambda: self._estado(
                    "Confirmacion cancelada; el modo se mantiene activo.",
                    "info",
                ),
                mostrar_cancelar=True,
            )
        else:
            modal = HuellaModal(
                self.controller,
                self.biometrico,
                titulo="CONFIRMAR CORRIDA",
                mensaje="Coloca tu huella para contar estos cortes como "
                        "produccion de la sesion y salir del paro.",
                validador=self._validar_autorizacion_paro,
                on_autenticado=self._corrida_confirmada_paro,
                on_cancelar=lambda: self._estado(
                    "Confirmacion cancelada; el paro se mantiene abierto.",
                    "info",
                ),
                mostrar_cancelar=True,
            )
        modal.exec()

    def _corrida_confirmada(self, id_operador, nombre, causa_id=None):
        """Cierra el modo Primera pieza INCORPORANDO los cortes de la rafaga.

        Solo se incorporan los cortes de la ventana detectada y posteriores;
        los hechos antes quedan descartados (piezas de prueba).
        """
        a_incorporar = max(
            self.controlador.cortes_excluidos() - self._excluidos_previos_rafaga,
            0,
        )
        n_excluidos = self._cerrar_primera_pieza(
            id_operador, incorporar=True, cantidad=a_incorporar
        )
        self._fijar_switch(False)
        self._refrescar_estado_maquina()
        self._estado(
            f"Corrida confirmada por {nombre}: {n_excluidos} cortes "
            "incorporados al conteo.",
            "exito",
        )
        log.info("Corrida confirmada por %s: %s cortes pasaron al total "
                 "(%s previos descartados como prueba)",
                 nombre, n_excluidos, self._excluidos_previos_rafaga)

    def _corrida_confirmada_paro(self, id_operador, nombre, causa_id=None):
        """Corrida confirmada en un PARO/MODO PARO: incorpora los cortes de
        la ventana (si el conteo estaba suspendido) y resuelve el paro.

        - MODO PARO: se cierra con su causa/zona y, si la maquina estaba
          detenida, se enciende (mismo camino que 'SALIR DE PARO').
        - Paro aun NO autorizado (defensivo): se cierra sin causa y se
          reanuda la produccion.
        En un PARO normal el conteo no estaba suspendido: los cortes ya
        estan en el total de la sesion.
        """
        suspendido = self._conteo_paro_suspendido()
        a_incorporar = 0
        if suspendido:
            a_incorporar = max(
                self.controlador.cortes_excluidos()
                - self._excluidos_previos_rafaga,
                0,
            )
            self.controlador.incorporar_excluidos(a_incorporar)
        etiqueta = self._etiqueta_paro_actual()
        if self._modo_paro:
            self._modo_paro_finalizado(id_operador, nombre)
        else:
            if self.paro_id is not None:
                finalizar_paro(self.paro_id, None, id_operador)
            self.paro_id = None
            self._en_paro = False
            self._paro_idle_triggado = False
            self._paro_inicio_momento = None
            self._ultimo_color_rojo = None
            self.controlador.retomar_conteo()
            self.controlador.reprisar_maquina()
            self.controlador.reiniciar_gracia_inactividad()
            self._refrescar_estado_maquina()
        self._refrescar_labels_cortes()
        if suspendido:
            detalle = f"{a_incorporar} cortes incorporados al conteo. "
        else:
            detalle = "Los cortes ya estaban en el total de la sesion. "
        self._estado(
            f"Corrida confirmada por {nombre}: {detalle}"
            "Paro resuelto; la maquina continua en marcha.",
            "exito",
        )
        log.info("Corrida en %s confirmada por %s: %s cortes incorporados "
                 "(%s previos descartados como prueba)",
                 etiqueta, nombre, a_incorporar,
                 self._excluidos_previos_rafaga)

    def _estado_torre(self):
        """Decide el estado de la torre (funcion pura, testable).

        - Sin sesion: apagada.
        - El modal de autorizacion del paro sigue abierto (causa/zona o
          huella): ROJA + alarma desde el primer instante, sin pasar por el
          ambar ni esperar la tolerancia.
        - Hay un paro pendiente por resolver y ya vencio la tolerancia: ROJA
          (mas la alarma de Q6). OJO: esto NO depende de que la maquina este
          detenida. Hay paros en los que la maquina DEBE seguir en marcha
          (zona con 'maquina encendida', Mantenimiento, Primera pieza): la
          roja avisa de que el paro lleva demasiado tiempo abierto, no de
          que la maquina este parada.
        - Maquina en marcha sin paro vencido: VERDE, o AMBAR si hay un modo
          que suspende la produccion (Primera pieza, Mantenimiento o PARO
          con la maquina encendida por zona).
        - Maquina detenida sin paro real (espera de trabajo): AMBAR. No se
          pone roja porque no hay paro que resolver y no debe estar sonando
          entre trabajos.
        """
        if not getattr(self, "sesion_id", None):
            return (False, False, False)
        # El modal de autorizacion del paro fuerza ROJA + buzzer mientras el
        # operador elige la causa y autoriza con huella. Se marca ANTES del
        # primer refresco del paro para que la torre pase de verde a rojo
        # directo (sin un ambar transitorio).
        if getattr(self, "_paro_autorizacion_pendiente", False):
            return (False, False, True)
        # La roja se decide DESPUES: un paro vencido sigue siendo un paro
        # vencido aunque la maquina haya quedado encendida (zona con
        # 'maquina encendida', Mantenimiento o Primera pieza).
        if self._paro_real_abierto() and self._tolerancia_paro_vencida():
            return (False, False, True)
        if self._maquina_en_marcha():
            if (self._modo_mantenimiento or self._modo_paro
                    or self._primera_pieza):
                return (False, True, False)
            return (True, False, False)
        return (False, True, False)

    def _rearmar_buzzer_si_paro_vencido(self):
        """Vuelve a sonar si el paro autorizado sigue fuera de tolerancia.

        El aviso de Q6 solo se dispara al ENTRAR en rojo. Si la torre ya
        estaba roja cuando se autorizo (la tolerancia vencio con el modal
        abierto), no hay transicion nueva y el operador no oiria el segundo
        aviso. Aqui se rearma UNA vez, sin tocar el ancla de la tolerancia.
        """
        if not self._tolerancia_paro_vencida():
            return
        if getattr(self, "_ultimo_color_rojo", None) != "rojo":
            # Todavia no estaba roja: la transicion de `_actualizar_torre`
            # dispara el pulso por si sola. Solo se fuerza la evaluacion.
            self._actualizar_torre()
            return
        self._pulso_buzzer_plc()

    def _tolerancia_paro_vencida(self):
        """True si el paro lleva mas de `PRIMERA_PIEZA_TIMEOUT_S`.

        Ese es el valor de "tolerancia de paro" que se configura en el
        `.env`/`config.json` (el mismo que endurece la salida de Primera
        pieza). NO es `PARO_IDLE_TIMEOUT_S`, que es el minuto del auto-paro
        por inactividad. 0 = sin roja (se queda en ambar).
        """
        try:
            timeout = float(config.PRIMERA_PIEZA_TIMEOUT_S)
        except Exception:  # noqa: BLE001 - la torre nunca debe romper la UI
            return False
        if not timeout or timeout <= 0:
            return False
        if self._paro_inicio_momento is None:
            return False
        try:
            desde = time.time() - self._paro_inicio_momento
        except Exception:  # noqa: BLE001 - ancla corrupta: se queda en ambar
            return False
        return desde >= timeout

    def _actualizar_torre(self):
        v, a, r = self._estado_torre()
        ctrl = getattr(self, "controlador", None)
        if ctrl is None:
            return
        try:
            if hasattr(ctrl, "establecer_torre"):
                ctrl.establecer_torre(v, a, r)
        except Exception:
            log.debug("establecer_torre fallo", exc_info=True)
        if r and getattr(self, "_ultimo_color_rojo", None) != "rojo":
            try:
                if hasattr(ctrl, "pulso_alarma"):
                    ctrl.pulso_alarma()
            except Exception:
                log.debug("pulso_alarma fallo", exc_info=True)
        self._ultimo_color_rojo = "rojo" if r else None


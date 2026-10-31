"""
inicio_view.py - Vista principal de produccion (Inicio).

La pantalla separa DOS controles independientes:

SESION (boton del header, esquina superior derecha): identidad + TOTALES.
    Al iniciarla se pide huella, se abre la sesion y se REINICIA el contador
    (el total de produccion es POR SESION). El icono muestra persona (rol
    operador) o engranaje (cualquier otro rol) y el nombre del operador queda
    a su lado. NO se puede cerrar sesion con la maquina en marcha: una
    maquina encendida siempre vive dentro de una sesion (al encender entra a
    Primera pieza y pide trabajo); cerrarla dejaria cortes sin dueno.

MAQUINA (boton central grande): enciende/apaga el relevo DENTRO de la
    sesion, sin huella extra (hereda la del login). Encender pone la maquina
    en marcha y entra AUTOMATICAMENTE al modo Primera pieza (estado "ESPERA
    TRABAJO") abriendo el pedido de trabajo; la espera de trabajo queda asi
    atada al ENCENDIDO, no al login. Apagar SIN trabajo detiene el relevo
    (seguro anti-corte mediante). Apagar CON trabajo cargado hace el cierre
    completo (#5): primero elige la MODALIDAD de cierre (produccion normal
    topada a la meta / produccion parcial con confirmacion o correccion del
    conteo / Folio modificado con el nuevo total) y DETIENE la maquina,
    quedando en espera de trabajo. La confirmacion de la cantidad ES la
    autorizacion del cierre: NO se pide huella (el operador de la sesion ya
    esta autenticado al abrirla). El estado final del trabajo (Cerrado si
    alcanza la meta, Abierto si no) lo decide la BD.

Modo "Primera pieza": con la sesion abierta y la maquina en marcha, registra
el evento como un paro con la causa fija 'Primera pieza'; durante el modo la
maquina sigue en marcha y NO se aplica el auto-paro por inactividad. Al salir
del modo (switch + huella) la gracia del auto-paro se reinicia. El boton PARO
queda deshabilitado mientras este activo.

Modo "MANTENIMIENTO": al parar y elegir la causa 'mantenimiento', hace falta
una validacion DOBLE, PRIMERO huella de personal de mantenimiento (permiso
'autorizar_mantenimiento') y LUEGO la del operador de la sesion. La maquina
SIGUE EN MARCHA con el conteo suspendido (los cortes van a excluidos, con la
misma logica de rafagas que Primera pieza). El boton PARO pasa a "SALIR DE
MANTENIMIENTO" (rojo) y el boton central brilla en ambar; para salir se pide
otra vez la doble validacion (mantenimiento + operador) y se finaliza el paro
con la causa 'mantenimiento'. El boton central brilla en amarillo durante
Primera pieza y en verde al producir.

MODO PARO: TODO paro autorizado entra aqui, sea cual sea la causa (la unica
excepcion es 'mantenimiento', que conserva su modo propio). El paro queda
ABIERTO en BD y se cierra en un SEGUNDO paso, 'SALIR DE PARO' (boton PARO en
rojo o boton central), que pide la huella del operador. Lo unico que depende
de la zona elegida es la maquina: si la causa requiere zona y esa zona tiene
marcada 'maquina encendida' (Administracion -> Zonas), la maquina REPRENDE con
el conteo suspendido y los cortes van a excluidos; en cualquier otro caso
(zona normal o causa que no requiere zona) la maquina se queda DETENIDA. En
ambos casos, al pulsar SALIR DE PARO se cierra el paro y la maquina queda
ENCENDIDA (si estaba detenida, se enciende automaticamente). El estado de la
maquina muestra la causa elegida entre parentesis ('Maquina: PARO (Causa)');
que la maquina siga en marcha se distingue por el resplandor y el tooltip.

SEGURO ANTI-CORRIDA: durante el modo los cortes van a un acumulado temporal.
Si se detecta una rafaga (mas de SEGURO_RAFAGA_CORTES cortes dentro de
SEGURO_RAFAGA_SEGUNDOS, ver .env), suena una alarma y se pregunta si la
maquina ya empezo a correr; al confirmar y autorizar por huella, SOLO los
cortes de la ventana detectada y posteriores se INCORPORAN al total de la
sesion (lo excluido antes queda como piezas de prueba descartadas). Con "No"
(o sin autorizacion) todo sigue fuera del conteo y se pierde al salir del modo.

TRABAJOS POR QR: al ENCENDER la maquina se ofrece un modal CANCELABLE que
pide el escaneo de un QR `folio|num_part|cantidad_total` (escaner USB tipo
teclado) + huella. El operador manda: puede cancelar para ajustar la maquina
y hacer piezas de prueba (el modo suprime el auto-paro por inactividad) y
escanear cuando este listo con ESCANEAR TRABAJO (visible solo sin trabajo
cargado y maquina en marcha). Al aceptar se registra/retoma el trabajo en la
tabla `trabajos` (folio unico: re-escanear uno Abierto retoma su conteo; uno
Cerrado se rechaza), se salen las piezas de prueba (mismo descarte del modo)
y los cortes empiezan a contar para ese trabajo ARRANCANDO EN 1 (total -
baseline, con la Primera pieza contando como la primera pieza del folio; un
folio retomado conserva su avance y no repite el +1). El
marcador muestra NUMERO DE PARTE arriba, los digitos al centro y CANTIDAD/
META abajo; la linea inferior de estado resume sesion, folio, parte,
cantidad, meta, ciclos totales y setup. 'Cerrado' SOLO al alcanzar la
cantidad_total, y ahora SOLO via cierre manual: EL AUTO-CIERRE POR META ESTA
INHABILITADO (`_verificar_meta_trabajo` quedo comentado en
`_refrescar_contador`), asi que ni la alarma ni el dialogo de cierre se abren
solos. El cierre por el boton de MAQUINA con trabajo carga el dialogo
de cierre (#5). Lo mismo al cerrar sesion: el parcial queda Abierto. Tras un
apagon el trabajo se retoma escaneando su QR, que lo reactiva desde su
checkpoint.

CIERRE ABRUPTO (APAGON): si la app se cerro con una sesion 'Activa' (apagon,
crash, cierre de ventana), al reiniciar `_cerrar_sesion_interrumpida` NO la
recupera: los datos ya estan guardados por el checkpoint de 30 s
(`_checkpoint_cortes`), asi que solo limpia y pide una sesion NUEVA:

    1. El trabajo en curso se CONFIRMA con lo detectado en su checkpoint: las
       piezas ya se cortaron y no habra quien las vuelva a contar. Si alcanzo
       la meta queda 'Cerrado', si no 'Abierto' con su parcial (se retoma
       escaneando su QR; no hace falta autorizacion).
    2. El paro en curso se cierra con la causa implicita "Computadora
       apagada" (nadie autorizo nada, pero el reporte no debe mostrar paros
       sin causa).
    3. La sesion pasa a 'Finalizada' con el total del checkpoint.

La vista arranca deliberadamente SIN sesion (`sesion_id=None`): el header pide
huella de inicio y el operador abre un folio desde cero, con conteo en 0. El
latch PAUSE inicial del HAL deja la maquina fisicamente detenida.
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
        ancla se toma en cuanto hay un paro real con la maquina DETENIDA,
        sin importar su origen (PARO manual, auto-paro por inactividad,
        modo PARO o Mantenimiento); al volver a la marcha se rearma para
        que la alarma suene en el SIGUIENTE paro.
        """
        if (self.sesion_id is None or not self._paro_real_abierto()
                or self._maquina_en_marcha()):
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

    def _verificar_rafaga_arranque(self):
        """Detecta una corrida no autorizada en Primera pieza o Mantenimiento.

        Con el conteo suspendido, si dentro de SEGURO_RAFAGA_SEGUNDOS entran
        mas de SEGURO_RAFAGA_CORTES cortes excluidos, suena una alarma y
        pregunta al operador si la maquina ya empezo a correr; al confirmar
        y autorizar por huella (doble en Mantenimiento), lo hecho durante el
        modo pasa al conteo.
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
            self._muestras_rafaga.clear()
            self._ultimo_excluidos = 0
            self._rafaga_en_curso = False
            self._excluidos_previos_rafaga = 0
            return
        if ((not self._primera_pieza and not self._modo_mantenimiento)
                or self._en_paro
                or self.sesion_id is None or not self._maquina_en_marcha()):
            self._muestras_rafaga.clear()
            self._ultimo_excluidos = 0
            self._rafaga_en_curso = False
            self._excluidos_previos_rafaga = 0
            return
        if self._modal_abierto:
            return  # Otro modal en curso; evaluar al cerrarse.
        excluidos = self.controlador.cortes_excluidos()
        delta = excluidos - self._ultimo_excluidos
        self._ultimo_excluidos = excluidos
        ahora = time.time()
        if delta > 0:
            self._muestras_rafaga.append((ahora, delta))
        elif delta < 0:
            # Reinicio de temporales (reentrada al modo): baseline nuevo.
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
        # Lo excluido antes de la ventana son piezas de prueba: al confirmar
        # la corrida solo se incorporan los de la ventana en adelante
        # (incluidos los que ocurran mientras el modal esta abierto).
        self._excluidos_previos_rafaga = excluidos - en_ventana
        modo = "Mantenimiento" if self._modo_mantenimiento else "Primera pieza"
        log.warning("Rafaga en %s: %s cortes en %s s "
                    "(%s previos quedan como prueba)",
                    modo, en_ventana, ventana, self._excluidos_previos_rafaga)
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
        modo = "Mantenimiento" if self._modo_mantenimiento else "Primera pieza"
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
        operador; en Primera pieza solo el operador."""
        if self._modo_mantenimiento:
            self._pedir_huella_mantenimiento(
                self._corrida_mantenimiento_paso_operador,
                titulo="REANUDACION MANTENIMIENTO"
            )
            return
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

    def _estado_torre(self):
        """Decide el estado de la torre (funcion pura, testable).

        - Sin sesion: apagada.
        - Maquina en marcha: VERDE, o AMBAR si hay un modo que suspende la
          produccion (Primera pieza, Mantenimiento o PARO con la maquina
          encendida por zona).
        - Maquina detenida con un paro real: AMBAR dentro de la tolerancia y
          ROJA (mas la alarma de Q6) al vencerla.
        - Maquina detenida sin paro real (espera de trabajo, Primera pieza
          con la maquina apagada): AMBAR. No se pone roja porque no hay
          paro que resolver y no debe estar sonando entre trabajos.
        """
        if not getattr(self, "sesion_id", None):
            return (False, False, False)
        if self._maquina_en_marcha():
            if (self._modo_mantenimiento or self._modo_paro
                    or self._primera_pieza):
                return (False, True, False)
            return (True, False, False)
        if self._paro_real_abierto() and self._tolerancia_paro_vencida():
            return (False, False, True)
        return (False, True, False)

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


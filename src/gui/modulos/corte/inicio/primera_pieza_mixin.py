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




class PrimeraPiezaMixin:

    def _verificar_timeout_primera_pieza(self):
        """Aviso informativo (una sola vez) al superar el timeout del modo."""
        if not self._primera_pieza or not self._timeout_primera_pieza_superado():
            self._aviso_timeout_primera_pieza_hecho = False
            return
        if self._aviso_timeout_primera_pieza_hecho:
            return
        self._aviso_timeout_primera_pieza_hecho = True
        permitidos = " o ".join(roles_con_permiso("autorizar_paro")) or (
            "un rol autorizado"
        )
        self._estado(
            f"Primera pieza lleva mas de "
            f"{config.PRIMERA_PIEZA_TIMEOUT_S // 60} min: la salida requiere "
            f"{permitidos}.", "procesando",
        )
        log.warning("Primera pieza supero %s s; la salida exigira "
                    "autorizacion de %s", config.PRIMERA_PIEZA_TIMEOUT_S,
                    permitidos)

    def _switch_primera_pieza(self, activo):
        """El switch se alterna con autorizacion por huella al inicio y al fin.

        Durante el modo la maquina SIGUE EN MARCHA: solo se desactiva el
        auto-paro por inactividad (no se cuenta el minuto de espera de corte)
        y el evento se registra como un paro con la causa fija 'Primera
        pieza'. Al finalizar, la gracia del auto-paro se reinicia.

        Con un trabajo CARGADO en espera (modo activo), apagar el switch ES
        la salida del modo: pide huella y al salir arranca el conteo del
        folio. Con un trabajo EN PRODUCCION (fuera del modo) encender el
        switch sigue bloqueado; este guard cubre toggles en vuelo.
        """
        if self._modal_abierto or self._ajustando_switch:
            return
        if activo and self._primera_pieza:
            self._fijar_switch(True)
            return
        if (self._trabajo is not None and activo
                and not self._primera_pieza):
            self._fijar_switch(False)
            self._estado(
                f"Hay un trabajo abierto ({self._trabajo['folio']}); usa el "
                "boton de maquina para guardarlo y detener.", "error"
            )
            return
        self._abrir_huella_primera_pieza(activo)

    def _fijar_switch(self, activo):
        self._ajustando_switch = True
        self.switch_primera_pieza.fijar(activo, animar=False)
        self._ajustando_switch = False

    def _validar_salida_primera_pieza(self):
        """Validador condicional de SALIDA del modo Primera pieza.

        Si se supero el timeout configurado (`PRIMERA_PIEZA_TIMEOUT_S`), la
        salida exige autorizacion de un rol con `autorizar_paro`
        (supervisor/admin), ademas del dueno de la sesion. Fuera del timeout
        basta el validador normal del paro.
        """
        def validador(id_operador, nombre, causa_id=None):
            if not self._timeout_primera_pieza_superado():
                return self._validar_autorizacion_paro(
                    id_operador, nombre, causa_id
                )
            # Pasado el timeout, la salida exige SIEMPRE un rol con
            # `autorizar_paro` (supervisor/admin), incluso para el dueno de la
            # sesion: un descuido prolongado debe resolverlo la supervision.
            if rol_tiene_permiso_operador(id_operador, "autorizar_paro"):
                return True, None
            return False, (
                "Debe ser finalizado por Supervisor o Mantenimiento "
                "para iniciar producción"
            )
        return validador

    def _timeout_primera_pieza_superado(self) -> bool:
        """True si el modo Primera pieza lleva mas del timeout configurado."""
        timeout = config.PRIMERA_PIEZA_TIMEOUT_S
        if not timeout or timeout <= 0 or self._primera_pieza_inicio is None:
            return False
        return (time.time() - self._primera_pieza_inicio) > timeout

    def _abrir_huella_primera_pieza(self, inicio):
        if inicio and self._causa_primera_pieza_id() is None:
            self._fijar_switch(False)
            caja = QMessageBox(self.controller)
            caja.setWindowTitle("Causa faltante")
            caja.setText("No existe la causa de paro 'Primera pieza'. Agregala en "
                         "Administracion para usar este modo.")
            caja.setIcon(QMessageBox.Warning)
            caja.addButton("Aceptar", QMessageBox.AcceptRole)
            caja.exec()
            self._estado("Sin causa 'Primera pieza'; modo no disponible.", "error")
            return
        self._modal_abierto = True
        try:
            # Al SALIR del modo, si se supero el timeout, exigir rol con
            # `autorizar_paro` (punto 2); el inicio siempre usa el normal.
            validador = (
                self._validar_autorizacion_paro if inicio
                else self._validar_salida_primera_pieza()
            )
            modal = HuellaModal(
                self.controller,
                self.biometrico,
                titulo=(
                    "AUTORIZAR PRIMERA PIEZA" if inicio
                    else "FINALIZAR PRIMERA PIEZA"
                ),
                mensaje=(
                    "Coloca tu huella para iniciar el modo Primera pieza."
                    if inicio else
                    "Coloca tu huella para finalizar el modo Primera pieza."
                ),
                validador=validador,
                on_autenticado=(
                    self._primera_pieza_iniciada if inicio
                    else self._primera_pieza_finalizada
                ),
                on_cancelar=lambda: self._cancelar_primera_pieza(inicio),
                mostrar_cancelar=True,
            )
            modal.exec()
        finally:
            self._modal_abierto = False
        # El modal pudo cerrarse autenticando, cancelando, X o ESC. El switch
        # debe reflejar el estado REAL del modo: si seguimos en Primera pieza
        # (p. ej. la SALIDA fue cancelada) el switch NO debe quedar apagado.
        self._fijar_switch(self._primera_pieza)

    def _cancelar_primera_pieza(self, inicio):
        self._fijar_switch(not inicio)
        self._estado(
            "Inicio de Primera pieza cancelado." if inicio
            else "Finalizacion de Primera pieza cancelada.",
            "info",
        )

    def _primera_pieza_iniciada(self, id_operador, nombre, causa_id=None):
        self._entrar_primera_pieza(nombre)
        self._estado(f"Primera pieza iniciada por {nombre}.", "exito")

    def _primera_pieza_finalizada(self, id_operador, nombre, causa_id=None):
        self._finalizar_primera_pieza_si_activa(id_operador)
        self._fijar_switch(False)
        self._refrescar_estado_maquina()
        if self._trabajo is not None:
            # Salida del modo con trabajo cargado: aqui ARRANCA el conteo
            # del folio (los cortes de setup quedaron descartados) y la
            # maquina sigue en marcha para producir. El segmento tambien
            # arranca aqui (no en el QR). El conteo arranca en 1 (la Primera
            # pieza es la primera pieza del trabajo); un folio retomado con
            # avance conserva su cantidad y NO recibe el +1 otra vez.
            if self._cortes_trabajo() <= 0:
                self._baseline_trabajo -= 1
            recortar_inicio_segmento(
                self._trabajo["folio"], self.sesion_id
            )
            self._estado(
                f"Iniciando trabajo {self._trabajo['folio']} "
                f"({self._trabajo['num_part']})...", "exito"
            )
            log.info("Salida de Primera pieza por %s: inicia conteo del "
                     "trabajo %s", nombre, self._trabajo["folio"])
        else:
            # Sin trabajo cargado: al salir del modo la maquina se APAGA
            # (latch PAUSE) y queda detenida en espera.
            self.controlador.maquina_pausada()
            self._refrescar_estado_maquina()
            self._estado(
                f"Primera pieza finalizada por {nombre}: la maquina se "
                "detuvo.", "exito"
            )
            log.info("Salida de Primera pieza por %s sin trabajo: la "
                     "maquina se apago", nombre)

    def _finalizar_primera_pieza_si_activa(self, id_operador):
        """Cierra el paro 'Primera pieza' en curso DESCARTANDO sus cortes."""
        self._cerrar_primera_pieza(id_operador, incorporar=False)

    def _cerrar_primera_pieza(self, id_operador, incorporar=False,
                              cantidad=None):
        """Cierra el paro 'Primera pieza' en curso (causa fija + autorizador).

        Con `incorporar=False` los cortes hechos durante el modo se pierden
        (solo vivian en memoria). Con `incorporar=True` se confirman como
        produccion de la sesion: `cantidad=None` incorpora TODOS los
        excluidos; con una cantidad solo esos (ventana del seguro
        anti-corrida y posteriores) y el resto se descarta (piezas de
        prueba). Devuelve cuantos cortes se incorporaron.
        """
        if not self._primera_pieza or not self._primera_pieza_paro_id:
            return 0
        causa_id = self._causa_primera_pieza_id()
        if causa_id is None:
            log.warning("Causa 'Primera pieza' inactiva; paro %s sin causa",
                        self._primera_pieza_paro_id)
        excluidos = (
            self.controlador.cortes_excluidos() if incorporar else 0
        )
        finalizar_paro(self._primera_pieza_paro_id, causa_id, id_operador)
        self._primera_pieza_paro_id = None
        self._primera_pieza = False
        self._primera_pieza_inicio = None
        if incorporar:
            # Corrida confirmada: los cortes confirmados cuentan como
            # produccion de la sesion y el conteo sigue normal.
            self.controlador.incorporar_excluidos(cantidad)
            if cantidad is None:
                incorporados = excluidos
            else:
                incorporados = min(max(int(cantidad), 0), excluidos)
        else:
            incorporados = 0
            self.controlador.retomar_conteo()
        # Al salir del modo el minuto de inactividad arranca DE CERO: durante
        # el modo no hubo auto-paro y el tiempo sin corte acumulado no debe
        # disparar el modal justo al reanudar el conteo.
        self.controlador.reiniciar_gracia_inactividad()
        return incorporados

    def _causa_primera_pieza_id(self):
        return self._causa_id("primera pieza")

    def _causa_espera_id(self):
        return self._causa_id("esperando trabajo")

    def _abrir_espera_trabajo(self):
        """Abre el paro implicito 'Esperando trabajo' si aplica.

        Cubre el primer hueco (login -> PLAY/primer QR: la sesion abre sin
        paro) y los huecos entre trabajos (tras un cierre o al detener sin
        folio). Solo con sesion abierta, maquina DETENIDA, SIN folio
        cargado, fuera de Primera pieza/Mantenimiento y sin ningun otro paro
        en curso (el hueco PLAY -> QR ya lo cubre el paro de Primera pieza).
        Idempotente.
        """
        if (self.sesion_id is None or self._trabajo is not None
                or self._primera_pieza or self._modo_mantenimiento
                or self._espera_trabajo_paro_id is not None
                or self._en_paro or self.paro_id is not None
                or self._primera_pieza_paro_id is not None
                or self._maquina_en_marcha()):
            return
        try:
            if paro_en_curso(self.sesion_id) is not None:
                return
            self._espera_trabajo_paro_id = iniciar_paro(self.sesion_id, None)
        except Exception:  # noqa: BLE001 - la espera nunca debe tumbar la UI
            log.warning("No se pudo abrir el paro de espera", exc_info=True)
            self._espera_trabajo_paro_id = None
            return
        log.info("Espera de trabajo iniciada (paro %s, sesion %s)",
                 self._espera_trabajo_paro_id, self.sesion_id)

    def _cerrar_espera_trabajo(self, autorizador_id):
        """Cierra el paro implicito con causa 'Esperando trabajo'.

        `autorizador_id` es quien autentico la accion que termina la espera
        (el QR escaneado, PLAY, o el cierre de sesion); sin el se usa el
        operador de la sesion. Sin espera abierta no hace nada.
        """
        if self._espera_trabajo_paro_id is None:
            return
        try:
            finalizar_paro(
                self._espera_trabajo_paro_id, self._causa_espera_id(),
                autorizador_id or self.operador_id,
            )
            log.info("Espera de trabajo cerrada (paro %s)",
                     self._espera_trabajo_paro_id)
        except Exception:  # noqa: BLE001 - no debe frenar el flujo
            log.warning("No se pudo cerrar el paro de espera %s",
                        self._espera_trabajo_paro_id, exc_info=True)
        self._espera_trabajo_paro_id = None

    def _entrar_primera_pieza(self, nombre):
        """Entra al modo Primera pieza (espera de trabajo o piezas de setup).

        Registra el paro con causa 'Primera pieza' y suspende el conteo: los
        cortes van a excluidos (solo memoria) hasta que un trabajo valido se
        asigne (los descartan como piezas de prueba) o el switch vuelva a OFF.

        IDEMPOTENTE: si el modo ya esta activo NO re-registra otro paro ni
        reinicia el conteo de excluidos (solo reasegura el estado visual).
        Antes, FINALIZAR TRABAJO estando en espera de trabajo (o una meta
        instantanea al re-escanear un folio sobre-cumplido) creaba un segundo
        paro y dejaba el anterior abierto para siempre en Sesiones, ademas de
        borrar el contador de setup a mitad de modo (Diagnostico 7.2.4).
        """
        if self.sesion_id is None:
            log.warning("Primera pieza sin sesion activa; solicitud de %s "
                        "ignorada.", nombre)
            return
        if self._primera_pieza:
            # Ya en modo: conservar el paro vigente y los cortes de setup
            # acumulados.
            self._fijar_switch(True)
            self._refrescar_estado_maquina()
            log.info("Primera pieza ya activa; se conserva el paro %s "
                     "(solicitud de %s).", self._primera_pieza_paro_id,
                     nombre)
            return
        # Fin de la espera: si habia paro implicito se cierra aqui (PLAY o
        # entrada al modo), atribuido al operador de la sesion.
        self._cerrar_espera_trabajo(self.operador_id)
        self._primera_pieza_paro_id = iniciar_paro(
            self.sesion_id, self._folio_activo()
        )
        self._primera_pieza = True
        # Timestamp de entrada: la cuenta del timeout del modo arranca aqui
        # (solo la primera vez; la re-entrada idempotente no lo resetea).
        self._primera_pieza_inicio = time.time()
        # Los cortes de este modo NO cuentan para la sesion ni para ningun
        # trabajo: se acumulan solo en memoria y se pierden al salir.
        self.controlador.suspender_conteo()
        self._fijar_switch(True)
        self._refrescar_estado_maquina()
        log.info("Primera pieza iniciada por %s (paro %s)",
                 nombre, self._primera_pieza_paro_id)

    def _entrar_primera_pieza_sin_trabajo(self, id_operador, nombre):
        """Huella SIN QR: entra a Primera pieza sin folio con la maquina
        ENCENDIDA, solo si el operador autenticado tiene el permiso
        `iniciar_primera_pieza` (mantenimiento/admin). Si no, avisa y reabre
        el pedido de trabajo para que escanee un folio o cancele."""
        if not rol_tiene_permiso_operador(
                id_operador, "iniciar_primera_pieza"):
            permitidos = " o ".join(
                roles_con_permiso("iniciar_primera_pieza")
            ) or ("un rol autorizado")
            log.warning("%s (%s) intento Primera pieza sin trabajo sin "
                        "permiso", nombre, id_operador)
            caja = QMessageBox(self.controller)
            caja.setWindowTitle("Sin permiso")
            caja.setText(f"Primera pieza sin trabajo requiere el permiso "
                         f"iniciar_primera_pieza. Solo {permitidos} puede. ")
            caja.setIcon(QMessageBox.Warning)
            caja.addButton("Aceptar", QMessageBox.AcceptRole)
            caja.exec()
            self._abrir_modal_trabajo()
            return
        self._entrar_primera_pieza(nombre)
        if self.controlador.maquina_detenida():
            self.controlador.maquina_lista()
            log.info("Maquina ENCENDIDA en Primera pieza sin trabajo por %s "
                     "(permiso iniciar_primera_pieza)", nombre)
        self._refrescar_estado_maquina()
        self._refrescar_labels_cortes()
        self._estado(
            "Primera pieza SIN trabajo (permiso): la maquina esta lista, "
            "los cortes no cuentan hasta salir del modo.", "info",
        )


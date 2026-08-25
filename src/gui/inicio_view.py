"""
inicio_view.py - Vista principal de produccion (Inicio).

Maquina de estados de la maquina:
    EN ESPERA -> LISTA: al pulsar PLAY se abre un modal que pide la
                 huella de inmediato; al autenticar se abre la sesion
                 (automatica) y la maquina arranca.
    LISTA     -> EN ESPERA: al pulsar STOP se abre un modal que pide la
                 huella (operador de la sesion o un rol con el permiso
                 'autorizar_paro'); al autorizar se cierra la sesion.
    LISTA     -> PARO: al pulsar PARO (o por inactividad) se abre el modal
                 que pide motivo + huella; al autorizar se reanuda.

Con la sesion abierta y la maquina en LISTA, el switch "Primera pieza"
(autorizado por huella al iniciar y al terminar) registra el evento como un
paro con la causa fija 'Primera pieza'; durante el modo la maquina sigue en
marcha y NO se aplica el auto-paro por inactividad (no cuenta el minuto de
espera de corte). Al salir del modo la gracia del auto-paro se reinicia: el
minuto vuelve a contar desde cero. El boton PARO queda deshabilitado mientras
este activo.

SEGURO ANTI-CORRIDA: durante el modo los cortes van a un acumulado temporal.
Si se detecta una rafaga (mas de SEGURO_RAFAGA_CORTES cortes dentro de
SEGURO_RAFAGA_SEGUNDOS, ver .env), suena una alarma y se pregunta si la
maquina ya empezo a correr; al confirmar y autorizar por huella, SOLO los
cortes de la ventana detectada y posteriores se INCORPORAN al total de la
sesion (lo excluido antes queda como piezas de prueba descartadas). Con "No"
(o sin autorizacion) todo sigue fuera del conteo y se pierde al salir del modo.

TRABAJOS POR QR: al abrir la sesion la maquina entra AUTOMATICAMENTE en modo
Primera pieza (estado "ESPERA TRABAJO") y se ofrece un modal CANCELABLE que
pide el escaneo de un QR `folio|num_part|cantidad_total` (escaner USB tipo
teclado) + huella. El operador manda: puede cancelar para ajustar la maquina
y hacer piezas de prueba (el modo suprime el auto-paro por inactividad, por
eso sigue existiendo) y escanear cuando este listo con ESCANEAR TRABAJO o el
switch manual. Al aceptar se registra/retoma el trabajo en la tabla
`trabajos` (folio unico: re-escanear uno Abierto retoma su conteo; uno
Cerrado se rechaza), se salen las piezas de prueba (mismo descarte del modo)
y los cortes empiezan a contar para ese trabajo (total - baseline). El
contador muestra Total de la sesion y `NUM_PART: X/cantidad`. 'Cerrado' SOLO
al alcanzar la cantidad_total: ahi suena la alarma, se guarda la cantidad
REAL y vuelve a Primera pieza para el siguiente QR. FINALIZAR TRABAJO guarda
el parcial SIN cerrar (queda Abierto/retomable); lo mismo al cerrar sesion.
Tras un apagon se recupera el trabajo Abierto en curso desde su checkpoint.

La sesion se cuenta desde que la maquina arranca (LISTA) hasta que se
detiene; no hay boton de mantenimiento de sesion.

RECUPERACION TRAS CIERRE ABRUPTO: si la app se cerro con una sesion 'Activa'
(apagon, crash, cierre de ventana), al reiniciar se detecta en
`_revisar_sesion_interrumpida`: se restaura el operador, el total de cortes
del ultimo checkpoint y se deja la maquina en estado EN PARO. El operador
dueño o un rol con el permiso 'autorizar_paro' debe autorizar la reanudacion
(causa + huella) o cerrar formalmente la sesion; no se puede iniciar una
sesion nueva mientras exista la interrumpida.
"""

import logging
import threading
import time
from collections import deque

from PySide6.QtCore import Qt, QSize, QTimer
from PySide6.QtWidgets import (
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
    abrir_sesion,
    abrir_trabajo,
    actualizar_cantidad_cortada,
    actualizar_cortes_sesion,
    cerrar_sesion,
    completar_trabajo,
    finalizar_paro,
    iniciar_paro,
    listar_causas_paro,
    obtener_rol_operador,
    obtener_sesion_interrumpida,
    obtener_trabajo_abierto,
    paro_en_curso,
    pausar_trabajo,
    roles_con_permiso,
    rol_tiene_permiso_operador,
)
from src.gui.huella_modal import HuellaModal
from src.gui.marcador import DisplaySieteSegmentos
from src.gui.style import aplicar_estado, aplicar_estilo_boton
from src.gui.switch import Switch

log = logging.getLogger(__name__)


class InicioView(QWidget):
    def __init__(self, parent, controller, biometrico, controlador):
        super().__init__(parent)
        self.controller = controller
        self.biometrico = biometrico
        self.controlador = controlador

        self.sesion_id = None
        self.operador_id = None
        self.operador_nombre = None
        self.paro_id = None
        self._en_paro = False
        self._paro_idle_triggado = False
        self._modal_abierto = False
        self._recuperando = False
        self._primera_pieza = False
        self._primera_pieza_paro_id = None
        self._ajustando_switch = False
        # Seguro anti-corrida en Primera pieza: ventana movil de cortes
        # excluidos para detectar una corrida no autorizada.
        self._muestras_rafaga = deque()
        self._ultimo_excluidos = 0
        self._rafaga_en_curso = False
        # Cortes excluidos ANTES del inicio de la ventana detectada: son
        # piezas de prueba y NO se incorporan al confirmar la corrida.
        self._excluidos_previos_rafaga = 0
        # Trabajo abierto (fila de la tabla `trabajos`, folio unico) y el
        # valor de cortes_totales() al asignarlo: los cortes del trabajo se
        # calculan como total - baseline. Con folio re-escanado y Abierto, el
        # baseline se ajusta para RETOMAR desde `cantidad_cortada`.
        self._trabajo = None
        self._baseline_trabajo = 0

        self._crear_interfaz()
        self._revisar_sesion_interrumpida()
        self._refrescar_contador()
        self._checkpoint_cortes()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _crear_interfaz(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 24, 32, 24)
        layout.setSpacing(12)
        layout.addStretch(1)

        self.lbl_operador = QLabel("Operador: Sin sesion", self)
        self.lbl_operador.setObjectName("HeaderLabel")
        self.lbl_operador.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.lbl_operador, alignment=Qt.AlignHCenter)

        # Tablero de contadores (marcador LED de planta): el display rojo
        # de 7 segmentos muestra DESDE EL INICIO el contador del trabajo
        # (piezas hechas de la orden); sin trabajo muestra guiones. El total
        # de la sesion y el setup van en la linea inferior ambar.
        self.tablero = QFrame(self)
        self.tablero.setObjectName("Tablero")
        tab = QVBoxLayout(self.tablero)
        tab.setContentsMargins(22, 10, 22, 12)
        tab.setSpacing(4)

        self.lbl_cortes = QLabel("SIN TRABAJO", self.tablero)
        self.lbl_cortes.setObjectName("TableroEtiqueta")
        self.lbl_cortes.setAlignment(Qt.AlignCenter)
        tab.addWidget(self.lbl_cortes)

        self.display_trabajo = DisplaySieteSegmentos(self.tablero, alto=84)
        self.display_trabajo.set_valor("----")
        tab.addWidget(self.display_trabajo, alignment=Qt.AlignHCenter)

        self.lbl_cortes_trabajo = QLabel("", self.tablero)
        self.lbl_cortes_trabajo.setObjectName("TableroInfo")
        self.lbl_cortes_trabajo.setAlignment(Qt.AlignCenter)
        tab.addWidget(self.lbl_cortes_trabajo)

        layout.addWidget(self.tablero, alignment=Qt.AlignHCenter)

        fila_estado = QWidget(self)
        h = QHBoxLayout(fila_estado)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)
        self.icono_estado = QLabel(fila_estado)
        self.icono_estado.setFixedSize(24, 24)
        h.addWidget(self.icono_estado)
        self.lbl_estado_maquina = QLabel("Maquina: EN ESPERA", fila_estado)
        aplicar_estado(self.lbl_estado_maquina, "pendiente")
        h.addWidget(self.lbl_estado_maquina)
        layout.addWidget(fila_estado, alignment=Qt.AlignHCenter)

        self.lbl_detalle = QLabel("", self)
        aplicar_estado(self.lbl_detalle, "info")
        self.lbl_detalle.setAlignment(Qt.AlignCenter)
        self.lbl_detalle.setWordWrap(True)
        layout.addWidget(self.lbl_detalle)

        # --- Boton principal: PLAY (verde, lista para arrancar) o STOP
        # (rojo, con sesion activa: en espera o en paro) ---
        self.btn_poder = QPushButton(self)
        self.btn_poder.setObjectName("PowerOn")
        self.btn_poder.setIconSize(QSize(56, 56))
        self.btn_poder.clicked.connect(self._toggle_poder)
        layout.addWidget(self.btn_poder, alignment=Qt.AlignHCenter)

        self.btn_paro = QPushButton("PARO", self)
        self.btn_paro.setMinimumWidth(180)
        self.btn_paro.clicked.connect(self._boton_paro)
        layout.addWidget(self.btn_paro, alignment=Qt.AlignHCenter)

        # --- Trabajos: cerrar el trabajo actual (guarda el conteo) o
        # reabrir el escaneo del QR si se cancelo ---
        self.btn_finalizar_trabajo = QPushButton("FINALIZAR TRABAJO", self)
        self.btn_finalizar_trabajo.setMinimumWidth(180)
        self.btn_finalizar_trabajo.clicked.connect(
            self._boton_finalizar_trabajo
        )
        layout.addWidget(self.btn_finalizar_trabajo, alignment=Qt.AlignHCenter)
        self.btn_finalizar_trabajo.setVisible(False)

        self.btn_escanear = QPushButton("ESCANEAR TRABAJO", self)
        self.btn_escanear.setMinimumWidth(180)
        self.btn_escanear.clicked.connect(self._boton_escanear_trabajo)
        layout.addWidget(self.btn_escanear, alignment=Qt.AlignHCenter)
        self.btn_escanear.setVisible(False)

        self._fila_switch = QWidget(self)
        fila_h = QHBoxLayout(self._fila_switch)
        fila_h.setContentsMargins(0, 0, 0, 0)
        fila_h.setSpacing(10)
        self.switch_primera_pieza = Switch(self._fila_switch)
        self.switch_primera_pieza.toggled.connect(self._switch_primera_pieza)
        fila_h.addWidget(self.switch_primera_pieza)
        lbl_switch = QLabel("Primera pieza", self._fila_switch)
        fila_h.addWidget(lbl_switch)
        self._fila_switch.setVisible(False)
        layout.addWidget(self._fila_switch, alignment=Qt.AlignHCenter)

        self.lbl_estado = QLabel(
            "Pulsa el boton y coloca tu huella para encender.", self
        )
        aplicar_estado(self.lbl_estado, "info")
        self.lbl_estado.setAlignment(Qt.AlignCenter)
        self.lbl_estado.setWordWrap(True)
        layout.addWidget(self.lbl_estado)

        layout.addStretch(1)

    # ------------------------------------------------------------------
    # Boton de poder (interruptor)
    # ------------------------------------------------------------------

    def _toggle_poder(self):
        if self._modal_abierto:
            return
        if self.sesion_id is None:
            self._encender_maquina()
            return
        if self._seguro_paro_segundos() is not None:
            self._estado(
                "La maquina esta cortando: espera unos segundos para apagar.",
                "error",
            )
            log.info("APAGADO bloqueado por seguro anti-corte")
            return
        self._abrir_huella_cierre()

    def _encender_maquina(self):
        self._abrir_huella_encendido()

    def aplicacion_puede_cerrarse(self):
        """Guard del boton Salir del header y de cualquier cierre de ventana.

        Diferente del cierre de SESION (`_apagar_maquina`): si la maquina
        esta EN MARCHA no se permite cerrar el programa, porque quedaria
        cortando sin conteo ni supervision (el cleanup() solo puede
        latchear PAUSE si el enlace Modbus vive; ante apagon no hay nada).
        Se exige detenerla antes con el boton PARO (o salir del modo
        Primera pieza y parar). Con la maquina detenida SI se permite salir
        aunque quede sesion 'Activa': se recupera al arrancar, mismo camino
        que un apagon.

        Aplica igual en simulacion (una sola conducta en toda la app): en
        dev basta detener la maquina simulada antes de salir.
        """
        if not self.controlador.maquina_detenida():
            QMessageBox.warning(
                self.controller,
                "No se puede cerrar",
                "La maquina esta EN MARCHA.\n\n"
                "Detenla con el boton PARO antes de cerrar el programa.",
            )
            log.warning("Salida de la app bloqueada: la maquina esta en "
                        "marcha.")
            return False
        return True

    def _apagar_maquina(self, autorizador_id=None) -> bool:
        """Cierra la sesion y detiene la maquina. Devuelve True si cerro.

        `autorizador_id` es el operador que autentico el cierre (si se pasa);
        por defecto se atribuye al dueno de la sesion, como en Primera pieza.
        """
        if self._seguro_paro_segundos() is not None:
            self._estado(
                "La maquina esta cortando: espera unos segundos para apagar.",
                "error",
            )
            log.info("Apagado bloqueado por seguro anti-corte")
            return False
        if not self.controlador.maquina_detenida():
            self.controlador.maquina_pausada()
        total = self.controlador.cortes_totales()
        if self.sesion_id is not None:
            self._finalizar_primera_pieza_si_activa(self.operador_id)
            self._cerrar_trabajo_por_cierre_sesion()
            # Paro normal o de recuperacion EN CURSO: cerrarlo junto con la
            # sesion para no dejar filas 'En curso' eternas sobre una sesion
            # ya Finalizada (Diagnostico 7.2.5). El paro nunca llego a
            # autorizarse, asi que queda SIN causa (la columna lo permite,
            # igual que _cerrar_primera_pieza cuando falta la causa).
            if self.paro_id is not None:
                autorizador = autorizador_id or self.operador_id
                try:
                    finalizar_paro(self.paro_id, None, autorizador)
                    log.info("Paro %s cerrado junto con la sesion "
                             "(autorizado por operador %s)",
                             self.paro_id, autorizador)
                except Exception:  # noqa: BLE001 - no debe frenar el cierre
                    log.warning("No se pudo cerrar el paro %s al cerrar la "
                                "sesion", self.paro_id, exc_info=True)
                self.paro_id = None
            cerrar_sesion(self.sesion_id, total)
        self.controlador.reset_conteo()
        self.sesion_id = None
        self.operador_id = None
        self.operador_nombre = None
        self.paro_id = None
        self._en_paro = False
        self._paro_idle_triggado = False
        self._primera_pieza = False
        self._primera_pieza_paro_id = None
        self._fijar_switch(False)
        self._refrescar_operador()
        self._refrescar_estado_maquina()
        self._estado(f"Maquina en espera. {total} cortes registrados.", "info")
        log.info("Sesion cerrada con %s cortes", total)
        return True

    # ------------------------------------------------------------------
    # Modal: huella para arrancar (abre sesion automaticamente)
    # ------------------------------------------------------------------

    def _abrir_huella_encendido(self):
        self._modal_abierto = True
        try:
            modal = HuellaModal(
                self.controller,
                self.biometrico,
                titulo="ARRANCAR MAQUINA",
                mensaje="Coloca tu huella. La sesion se abrira automaticamente.",
                on_autenticado=self._encendido_autenticado,
                on_cancelar=lambda: self._estado("Arranque cancelado.", "info"),
            )
            modal.exec()
        finally:
            self._modal_abierto = False

    def _encendido_autenticado(self, id_operador, nombre, causa_id=None):
        self.sesion_id = abrir_sesion(id_operador)
        self.operador_id = id_operador
        self.operador_nombre = nombre
        self.controlador.reset_conteo()
        self.controlador.maquina_lista()
        self._en_paro = False
        self._paro_idle_triggado = False
        self._refrescar_operador()
        self._estado(f"Maquina lista. Operador: {nombre}.", "exito")
        log.info("Sesion %s abierta para %s", self.sesion_id, nombre)
        # Flujo de trabajos: la sesion SIEMPRE arranca en modo Primera pieza
        # (setup/pruebas sin auto-paro) esperando que el operador escanee el
        # QR del trabajo cuando este listo.
        self._entrar_primera_pieza(nombre)
        self._abrir_modal_trabajo()

    # ------------------------------------------------------------------
    # Recuperacion de sesion/paro tras cierre abrupto
    # ------------------------------------------------------------------

    def _revisar_sesion_interrumpida(self):
        """Detecta una sesion 'Activa' heredada de un apagon y la recupera.

        Restaura operador, contador de cortes (ultimo checkpoint) y deja la
        maquina en EN PARO: el dueno o un rol autorizado debe autorizar la
        reanudacion, o cerrar formalmente la sesion. Mientras exista esta
        sesion no se puede iniciar una nueva (el boton de poder pasa a
        cerrar/recuperar, nunca a encender).
        """
        sesion = obtener_sesion_interrumpida()
        if not sesion:
            return
        self._recuperando = True
        self.sesion_id = sesion["id"]
        self.operador_id = sesion["operador_id"]
        self.operador_nombre = sesion["nombre"]
        self.controlador.establecer_conteo(sesion["total_cortes"] or 0)
        # Trabajo abierto de la sesion interrumpida: se retoma desde su
        # ultimo checkpoint. El baseline retrocede lo ya cortado para que el
        # conteo siga sumando AL MISMO trabajo al reanudar.
        trabajo = obtener_trabajo_abierto(self.sesion_id)
        if trabajo is not None:
            self._trabajo = trabajo
            self._baseline_trabajo = (
                (sesion["total_cortes"] or 0)
                - (trabajo["cantidad_cortada"] or 0)
            )
            log.info("Trabajo %s (%s) recuperado con %s/%s piezas",
                     trabajo["folio"], trabajo["num_part"],
                     trabajo["cantidad_cortada"], trabajo["cantidad_total"])
        self._en_paro = True
        self._paro_idle_triggado = True
        # Paro en curso de la sesion; si no existia, se formaliza la detencion.
        self.paro_id = paro_en_curso(self.sesion_id) or iniciar_paro(self.sesion_id)
        self._refrescar_operador()
        self._refrescar_estado_maquina()
        self._estado(
            "Sesion interrumpida detectada. Maquina EN PARO: autoriza para "
            "reanudar o pulsa poder para cerrar la sesion.",
            "procesando",
        )
        log.info("Sesion interrumpida %s recuperada (operador %s, cortes %s)",
                 self.sesion_id, self.operador_nombre, sesion["total_cortes"])
        QTimer.singleShot(
            600, lambda: self._abrir_paro_autorizacion(recuperacion=True)
        )

    def _abrir_huella_cierre(self):
        """Cierre de sesion: requiere autorizacion del operador de la sesion
        o de un rol con autoridad (admin/supervisor)."""
        self._modal_abierto = True
        try:
            modal = HuellaModal(
                self.controller,
                self.biometrico,
                titulo=(
                    "CERRAR SESION INTERRUMPIDA"
                    if self._recuperando else "CERRAR SESION"
                ),
                mensaje=(
                    "Sesion interrumpida. Coloca tu huella para cerrarla "
                    "sin reanudar." if self._recuperando else
                    "Coloca tu huella para cerrar la sesion."
                ),
                validador=self._validar_autorizacion_paro,
                on_autenticado=self._cierre_autenticado,
                on_cancelar=lambda: self._estado("Cierre cancelado.", "info"),
            )
            modal.exec()
        finally:
            self._modal_abierto = False

    def _cierre_autenticado(self, id_operador, nombre, causa_id=None):
        era_recuperacion = self._recuperando
        sesion_id = self.sesion_id
        self._recuperando = False
        if not self._apagar_maquina(autorizador_id=id_operador):
            return
        if era_recuperacion:
            self._estado(f"Sesion interrumpida cerrada por {nombre}.", "exito")
        log.info("Sesion %s cerrada por %s", sesion_id, nombre)

    # ------------------------------------------------------------------
    # Paro
    # ------------------------------------------------------------------

    def _boton_paro(self):
        if self.sesion_id is None:
            self._estado("Primero arranca la maquina.", "error")
            return
        if self._modal_abierto:
            return
        if self._primera_pieza:
            self._estado(
                "Modo Primera pieza activo: finaliza la Primera pieza para "
                "poder parar.",
                "info",
            )
            return
        if self._maquina_en_marcha():
            if self._seguro_paro_segundos() is not None:
                self._estado(
                    "La maquina esta cortando: espera unos segundos para parar.",
                    "error",
                )
                log.info("PARO bloqueado por seguro anti-corte")
                return
            self._pausar_maquina()
        else:
            # Maquina ya detenida: reabrir autorizacion del paro pendiente
            if self._en_paro:
                self._abrir_paro_autorizacion()

    def _pausar_maquina(self, motivo="manual"):
        self.controlador.maquina_pausada()
        self._en_paro = True
        self.paro_id = iniciar_paro(self.sesion_id)
        self._refrescar_estado_maquina()
        log.info("Paro %s registrado (%s)", self.paro_id, motivo)
        self._estado("Maquina en PARO. Indica el motivo y autoriza.", "procesando")
        self._abrir_paro_autorizacion()

    def _abrir_paro_autorizacion(self, recuperacion=False):
        causas = listar_causas_paro(activas_solo=True)
        if not causas:
            QMessageBox.warning(
                self.controller,
                "Sin causas",
                "No hay causas de paro configuradas. Ve a Administracion.",
            )
            self._estado("Sin causas de paro; maquina detenida.", "error")
            return

        if recuperacion:
            on_cancelar = lambda: self._estado(  # noqa: E731
                "Recuperacion cancelada. Autoriza para reanudar o pulsa "
                "poder para cerrar la sesion.", "info"
            )
        else:
            on_cancelar = lambda: self._estado(  # noqa: E731
                "Paro NO autorizado; maquina detenida.", "error"
            )

        self._modal_abierto = True
        try:
            modal = HuellaModal(
                self.controller,
                self.biometrico,
                titulo="AUTORIZAR REANUDACION",
                mensaje=(
                    "Sesion interrumpida. Maquina EN PARO. Coloca tu huella."
                    if recuperacion else
                    "Maquina en PARO. Coloca tu huella."
                ),
                # En recuperacion el modal se puede cancelar (para cerrar la
                # sesion); en un paro normal no, hasta autorizar.
                mostrar_cancelar=recuperacion,
                cerrable=recuperacion,
                pedir_causa=True,
                validador=self._validar_autorizacion_paro,
                on_autenticado=self._autorizado_autenticado,
                on_cancelar=on_cancelar,
            )
            modal.exec()
        finally:
            self._modal_abierto = False

    def _validar_autorizacion_paro(self, id_operador, nombre, causa_id=None):
        """Solo autoriza (reanudar paro o cerrar sesion) el dueno de la
        sesion o un rol con el permiso 'autorizar_paro' (gestionado en
        Administracion)."""
        if id_operador == self.operador_id:
            return True, None
        if rol_tiene_permiso_operador(id_operador, "autorizar_paro"):
            return True, None
        permitidos = " o ".join(roles_con_permiso("autorizar_paro")) or (
            "un rol autorizado"
        )
        rol = obtener_rol_operador(id_operador)
        operador_sesion = self.operador_nombre or "el operador de la sesion"
        return False, (
            f"No eres {operador_sesion}. Solo el operador de la sesion o "
            f"{permitidos} puede autorizar esta accion"
            + (f" (tu rol: {rol})." if rol else " (sin rol asignado).")
        )

    def _autorizado_autenticado(self, id_operador, nombre, causa_id=None):
        finalizar_paro(self.paro_id, causa_id, id_operador)
        self.controlador.reprisar_maquina()
        self._en_paro = False
        self._paro_idle_triggado = False
        self._recuperando = False
        self._refrescar_estado_maquina()
        self._estado(f"Paro autorizado por {nombre}. Maquina reanudada.", "exito")

    # ------------------------------------------------------------------
    # Inactividad -> auto paro
    # ------------------------------------------------------------------

    def _refrescar_contador(self):
        self._refrescar_labels_cortes()
        self._verificar_rafaga_arranque()
        self._verificar_meta_trabajo()
        self._refrescar_estado_maquina()
        self._refrescar_enlace_modbus()
        self._verificar_inactividad()
        QTimer.singleShot(config.REFRESCO_CONTADOR_MS, self._refrescar_contador)

    def _refrescar_labels_cortes(self):
        """Tablero: el LED grande es el contador del TRABAJO (piezas hechas
        de la orden, ancho fijo a 4 digitos); la etiqueta lleva folio y
        meta; el total de sesion y el setup van en la linea inferior."""
        total = self.controlador.cortes_totales()
        setup = self.controlador.cortes_excluidos()
        if self._trabajo is None:
            # Espera de trabajo: guiones en el display y totales abajo para
            # que el operador vea la actividad del modo Primera pieza.
            self.lbl_cortes.setText("SIN TRABAJO")
            self.display_trabajo.set_valor("----")
            self.lbl_cortes_trabajo.setText(
                f"TOTAL {total}  |  SETUP {setup}"
            )
            return
        # Nunca se muestra mas alla de la meta (aunque un delta tarde llegue
        # a pasarla, el trabajo ya se cerro en la verificacion de meta).
        hecho = min(self._cortes_trabajo(), self._trabajo["cantidad_total"])
        self.lbl_cortes.setText(
            f"TRABAJO {self._trabajo['folio']} - "
            f"{self._trabajo['num_part']}  |  META "
            f"{self._trabajo['cantidad_total']}"
        )
        self.display_trabajo.set_valor(f"{hecho:04d}")
        texto = f"TOTAL SESION {total}"
        if self._primera_pieza:
            # Trabajo CARGADO en espera: ademas se ven los cortes de setup
            # que se descartan al salir del modo.
            texto += f"  |  SETUP {setup}"
        self.lbl_cortes_trabajo.setText(texto)

    def _refrescar_enlace_modbus(self):
        """Alerta visual si el enlace Modbus se cae (sin crashear la UI).

        Solo aplica al controlador Modbus (configurado con MODBUS_HOST); en
        modo simulacion o con SimulacionController no hay alerta.
        """
        en_simulacion = getattr(self.controlador, "en_simulacion", lambda: True)()
        conectado = getattr(self.controlador, "conectado", None)
        if en_simulacion or conectado is None:
            self.lbl_detalle.setText("")
            aplicar_estado(self.lbl_detalle, "info")
        elif not conectado():
            self.lbl_detalle.setText(
                "Error de comunicacion con el modulo Modbus. Reintentando..."
            )
            aplicar_estado(self.lbl_detalle, "error")
        else:
            self.lbl_detalle.setText("")
            aplicar_estado(self.lbl_detalle, "info")

    def _checkpoint_cortes(self):
        """Guarda periodicamente el total de cortes de la sesion activa.

        Respaldos ante apagones: si se va la luz, la sesion conserva el
        ultimo conteo en la base de datos (ver config.CORTES_GUARDAR_INTERVALO_MS).
        """
        if self.sesion_id is not None:
            actualizar_cortes_sesion(self.sesion_id, self.controlador.cortes_totales())
        if self._trabajo is not None:
            actualizar_cantidad_cortada(
                self._trabajo["folio"], self._cortes_trabajo()
            )
        QTimer.singleShot(
            config.CORTES_GUARDAR_INTERVALO_MS, self._checkpoint_cortes
        )

    def _verificar_inactividad(self):
        timeout = config.PARO_IDLE_TIMEOUT_S
        if not timeout or timeout <= 0:
            return
        if (self.sesion_id is None or self._paro_idle_triggado
                or self._modal_abierto or self._en_paro
                or self._primera_pieza):
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
        if min(sin_corte, desde_arranque) >= timeout:
            self._paro_idle_triggado = True
            log.info("Sin cortes por %s s; abriendo paro automatico", timeout)
            self._pausar_maquina(motivo="automatico")

    def _maquina_en_marcha(self):
        return not self.controlador.maquina_detenida()

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

    # ------------------------------------------------------------------
    # Modo "Primera pieza"
    # ------------------------------------------------------------------

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
                f"Hay un trabajo abierto ({self._trabajo['folio']}); usa "
                "FINALIZAR TRABAJO para cambiar de modo.", "error"
            )
            return
        self._abrir_huella_primera_pieza(activo)

    def _fijar_switch(self, activo):
        self._ajustando_switch = True
        self.switch_primera_pieza.fijar(activo, animar=False)
        self._ajustando_switch = False

    def _abrir_huella_primera_pieza(self, inicio):
        if inicio and self._causa_primera_pieza_id() is None:
            self._fijar_switch(False)
            QMessageBox.warning(
                self.controller,
                "Causa faltante",
                "No existe la causa de paro 'Primera pieza'. Agregala en "
                "Administracion para usar este modo.",
            )
            self._estado("Sin causa 'Primera pieza'; modo no disponible.", "error")
            return
        self._modal_abierto = True
        try:
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
                validador=self._validar_autorizacion_paro,
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
            # del folio (los cortes de setup quedaron descartados).
            self._estado(
                f"Contando para el trabajo {self._trabajo['folio']} "
                f"({self._trabajo['num_part']}).", "exito"
            )
            log.info("Salida de Primera pieza por %s: inicia conteo del "
                     "trabajo %s", nombre, self._trabajo["folio"])
        else:
            self._estado(f"Primera pieza finalizada por {nombre}.", "exito")

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
        for causa in listar_causas_paro(activas_solo=True):
            if str(causa["descripcion"]).strip().lower() == "primera pieza":
                return causa["id"]
        return None

    # ------------------------------------------------------------------
    # Trabajos (QR folio|num_part|cantidad_total)
    # ------------------------------------------------------------------

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
        self._primera_pieza_paro_id = iniciar_paro(self.sesion_id)
        self._primera_pieza = True
        # Los cortes de este modo NO cuentan para la sesion ni para ningun
        # trabajo: se acumulan solo en memoria y se pierden al salir.
        self.controlador.suspender_conteo()
        self._fijar_switch(True)
        self._refrescar_estado_maquina()
        log.info("Primera pieza iniciada por %s (paro %s)",
                 nombre, self._primera_pieza_paro_id)

    def _abrir_modal_trabajo(self):
        """Modal QR + huella que CARGA el trabajo estando en Primera pieza.

        El QR trae los datos y la huella CONFIRMA la carga; el modal no
        arranca el conteo ni saca la maquina del modo: sigue en Primera
        pieza (cortes de setup excluidos, sin auto-paro) mostrando el
        folio/parte. La SALIDA del modo (switch + huella) es lo que empieza
        a contar para el folio.
        """
        if self.sesion_id is None:
            return
        self._modal_abierto = True
        try:
            modal = HuellaModal(
                self.controller,
                self.biometrico,
                titulo="TRABAJO NUEVO",
                mensaje=(
                    "Escanea el QR del trabajo "
                    "(folio|num_part|cantidad_total) y confirma con tu "
                    "huella. El conteo inicia al salir del modo Primera "
                    "pieza."
                ),
                validador=self._validar_autorizacion_paro,
                pedir_trabajo=True,
                mostrar_cancelar=True,
                cerrable=True,
                on_autenticado=self._trabajo_cargado,
                on_cancelar=lambda: self._estado(
                    "Escaneo cancelado: la maquina sigue en modo Primera "
                    "pieza, los cortes no cuentan.", "info"
                ),
            )
            modal.exec()
        finally:
            self._modal_abierto = False

    def _trabajo_cargado(self, id_operador, nombre, causa_id,
                         folio, num_part, cantidad_total):
        """QR + huella aceptados: registra/retoma el folio EN ESPERA.

        NO sale del modo Primera pieza: el conteo del trabajo arranca hasta
        que el operador autorice la salida del modo (switch + huella).
        """
        ok, res = abrir_trabajo(folio, self.sesion_id, num_part,
                                cantidad_total)
        if not ok:
            log.warning("Trabajo %s rechazado: %s", folio, res)
            QMessageBox.warning(self.controller, "Trabajo rechazado", res)
            self._abrir_modal_trabajo()
            return
        self._trabajo = res
        guardada = res["cantidad_cortada"] or 0
        # Baseline fijo desde la carga: los cortes de setup siguen
        # excluidos (total congelado), asi que `_cortes_trabajo()` muestra
        # lo ya hecho del folio y al salir del modo empieza a sumar.
        self._baseline_trabajo = self.controlador.cortes_totales() - guardada
        self._refrescar_labels_cortes()
        self._estado(
            f"Trabajo {res['folio']} ({res['num_part']}) cargado por "
            f"{nombre} ({guardada}/{res['cantidad_total']} ya hechas). Sal "
            "del modo Primera pieza con tu huella para empezar a contar.",
            "exito",
        )
        log.info("Trabajo %s (%s) cargado en espera por %s a la sesion %s "
                 "(retoma %s/%s)", res["folio"], res["num_part"], nombre,
                 self.sesion_id, guardada, res["cantidad_total"])

    def _cortes_trabajo(self):
        """Cortes hechos DENTRO del trabajo abierto (total - baseline)."""
        if self._trabajo is None:
            return 0
        return max(
            self.controlador.cortes_totales() - self._baseline_trabajo, 0
        )

    def _verificar_meta_trabajo(self):
        """Meta alcanzada: CIERRA el trabajo ('Cerrado') y pide el siguiente.

        Llamado desde `_refrescar_contador` (hilo principal). Solo aqui un
        trabajo pasa a 'Cerrado': guarda la cantidad REAL cortada aunque se
        haya pasado (p. ej. 202/200), suena la alarma, re-entra a Primera
        pieza y abre el modal del siguiente QR (cancelable: el operador
        puede seguir ajustando antes de escanear).
        """
        if self._trabajo is None or self._modal_abierto or self._en_paro:
            return
        if self._cortes_trabajo() < self._trabajo["cantidad_total"]:
            return
        folio = self._trabajo["folio"]
        meta = self._trabajo["cantidad_total"]
        real = self._cortes_trabajo()
        completar_trabajo(folio, real)
        self._trabajo = None
        self._baseline_trabajo = 0
        log.info("Trabajo %s COMPLETADO (Cerrado): %s/%s", folio, real, meta)
        self._sonar_alarma()
        self._entrar_primera_pieza("meta alcanzada")
        self._estado(f"Trabajo {folio} completado ({real}/{meta}). "
                     "Escanea el siguiente trabajo.", "procesando")
        self._abrir_modal_trabajo()

    def _boton_finalizar_trabajo(self):
        """FINALIZAR TRABAJO: guarda el conteo parcial y pasa al siguiente."""
        if self._modal_abierto or self.sesion_id is None:
            return
        if self._trabajo is None:
            self._estado("No hay trabajo abierto que finalizar.", "error")
            return
        modal = HuellaModal(
            self.controller,
            self.biometrico,
            titulo="FINALIZAR TRABAJO",
            mensaje=(
                f"Se guardara el trabajo {self._trabajo['folio']} "
                f"({self._trabajo['num_part']}) con "
                f"{self._cortes_trabajo()} piezas. Coloca tu huella."
            ),
            validador=self._validar_autorizacion_paro,
            on_autenticado=self._trabajo_finalizado_manual,
            on_cancelar=lambda: self._estado(
                "Finalizacion cancelada; el trabajo sigue abierto.", "info"
            ),
            mostrar_cancelar=True,
        )
        modal.exec()

    def _trabajo_finalizado_manual(self, id_operador, nombre, causa_id=None):
        """FINALIZAR TRABAJO: guarda el parcial SIN cerrar el trabajo.

        'Cerrado' es SOLO para trabajos que alcanzan su cantidad_total; un
        parcial queda 'Abierto' (con fecha_fin) y se retoma re-escaneando el
        mismo folio desde lo ya cortado.
        """
        folio = self._trabajo["folio"]
        real = self._cortes_trabajo()
        pausar_trabajo(folio, real)
        self._trabajo = None
        self._baseline_trabajo = 0
        log.info("Trabajo %s pausado por %s con %s piezas (sigue Abierto)",
                 folio, nombre, real)
        # De vuelta a Primera pieza esperando el siguiente QR.
        self._entrar_primera_pieza(nombre)
        self._estado(
            f"Trabajo {folio} guardado por {nombre} con {real} piezas "
            "(queda Abierto; re-escanear para continuar).",
            "exito",
        )
        self._abrir_modal_trabajo()

    def _boton_escanear_trabajo(self):
        """Reabre el modal QR + huella cuando no hay trabajo abierto."""
        if self._modal_abierto or self.sesion_id is None:
            return
        if self._trabajo is not None:
            self._estado(
                f"El trabajo {self._trabajo['folio']} sigue abierto; "
                "finalizalo antes de escanear otro.", "error"
            )
            return
        self._abrir_modal_trabajo()

    def _cerrar_trabajo_por_cierre_sesion(self):
        """Guarda el parcial del trabajo abierto al apagar/cerrar sesion.

        El trabajo NO se cierra (solo la meta lo cierra): queda 'Abierto'
        con su parcial y puede retomarse re-escaneando el folio en cualquier
        sesion futura.
        """
        if self._trabajo is None:
            return
        folio = self._trabajo["folio"]
        real = self._cortes_trabajo()
        pausar_trabajo(folio, real)
        self._trabajo = None
        self._baseline_trabajo = 0
        log.info("Trabajo %s con parcial guardado al cerrar la sesion "
                 "(%s piezas, sigue Abierto)", folio, real)

    # ------------------------------------------------------------------
    # Seguro anti-corrida durante "Primera pieza"
    # ------------------------------------------------------------------

    def _verificar_rafaga_arranque(self):
        """Detecta una corrida no autorizada en modo Primera pieza.

        Con el conteo suspendido, si dentro de SEGURO_RAFAGA_SEGUNDOS entran
        mas de SEGURO_RAFAGA_CORTES cortes excluidos, suena una alarma y
        pregunta al operador si la maquina ya empezo a correr; al confirmar
        y autorizar por huella, lo hecho durante el modo pasa al conteo.
        """
        ventana = config.SEGURO_RAFAGA_SEGUNDOS
        umbral = config.SEGURO_RAFAGA_CORTES
        if not ventana or ventana <= 0 or umbral <= 0:
            return
        if (not self._primera_pieza or self._en_paro
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
        log.warning("Rafaga en Primera pieza: %s cortes en %s s "
                    "(%s previos quedan como prueba)",
                    en_ventana, ventana, self._excluidos_previos_rafaga)
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
        self._modal_abierto = True
        try:
            caja = QMessageBox(self.controller)
            caja.setWindowTitle("Posible corrida sin conteo")
            caja.setIcon(QMessageBox.Warning)
            caja.setText(
                f"Se detectaron {n_cortes} cortes en los ultimos {ventana} "
                "segundos con el modo Primera pieza activo.\n\n"
                "¿Ya empezo a correr la maquina?"
            )
            btn_si = caja.addButton("Sí", QMessageBox.YesRole)
            caja.addButton("No", QMessageBox.NoRole)
            caja.exec()
            if caja.clickedButton() is btn_si:
                self._abrir_huella_corrida()
            else:
                log.info("Corrida descartada por el operador "
                         "(Primera pieza sigue activa)")
                self._estado(
                    "Corrida descartada: los cortes siguen fuera del conteo.",
                    "info",
                )
        finally:
            self._modal_abierto = False

    def _abrir_huella_corrida(self):
        """Autorizacion por huella para contar la corrida detectada."""
        modal = HuellaModal(
            self.controller,
            self.biometrico,
            titulo="CONFIRMAR CORRIDA",
            mensaje="Coloca tu huella para contar estos cortes como "
                    "produccion de la sesion.",
            validador=self._validar_autorizacion_paro,
            on_autenticado=self._corrida_confirmada,
            on_cancelar=lambda: self._estado(
                "Confirmacion cancelada; el modo Primera pieza sigue activo.",
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

    def _refrescar_estado_maquina(self):
        estilo = self.style()
        if self.sesion_id is None:
            self.lbl_estado_maquina.setText("Maquina: EN ESPERA")
            aplicar_estado(self.lbl_estado_maquina, "pendiente")
            self._icono_estado(estilo, QStyle.StandardPixmap.SP_MediaPause)
            self.btn_poder.setIcon(
                estilo.standardIcon(QStyle.StandardPixmap.SP_MediaPlay)
            )
            aplicar_estilo_boton(self.btn_poder, "PowerOn")
        elif self._en_paro:
            self.lbl_estado_maquina.setText("Maquina: EN PARO")
            aplicar_estado(self.lbl_estado_maquina, "procesando")
            self._icono_estado(estilo, QStyle.StandardPixmap.SP_MediaPause)
            self.btn_poder.setIcon(
                estilo.standardIcon(QStyle.StandardPixmap.SP_MediaStop)
            )
            aplicar_estilo_boton(self.btn_poder, "Power")
        elif self._primera_pieza:
            self.lbl_estado_maquina.setText("Maquina: ESPERA TRABAJO")
            aplicar_estado(self.lbl_estado_maquina, "procesando")
            self._icono_estado(estilo, QStyle.StandardPixmap.SP_MediaPlay)
            self.btn_poder.setIcon(
                estilo.standardIcon(QStyle.StandardPixmap.SP_MediaStop)
            )
            aplicar_estilo_boton(self.btn_poder, "Power")
        else:
            self.lbl_estado_maquina.setText("Maquina: LISTA")
            aplicar_estado(self.lbl_estado_maquina, "exito")
            self._icono_estado(estilo, QStyle.StandardPixmap.SP_MediaPlay)
            self.btn_poder.setIcon(
                estilo.standardIcon(QStyle.StandardPixmap.SP_MediaStop)
            )
            aplicar_estilo_boton(self.btn_poder, "Power")
        self._fila_switch.setVisible(
            self.sesion_id is not None and not self._en_paro
        )
        # Botones de trabajo: finalizar solo hay algo abierto; escanear solo
        # si no hay trabajo cargado. El switch manual queda habilitado con
        # sesion activa: apagarlo con un trabajo EN ESPERA es la salida del
        # modo (huella) que arranca el conteo.
        self.btn_finalizar_trabajo.setVisible(
            self.sesion_id is not None and self._trabajo is not None
        )
        self.btn_escanear.setVisible(
            self.sesion_id is not None and self._trabajo is None
        )
        self.switch_primera_pieza.setEnabled(self.sesion_id is not None)

    def _icono_estado(self, estilo, sp):
        self.icono_estado.setPixmap(estilo.standardIcon(sp).pixmap(22, 22))

    # ------------------------------------------------------------------
    # Helpers UI
    # ------------------------------------------------------------------

    def _refrescar_operador(self):
        texto = self.operador_nombre if self.operador_nombre else "Sin sesion"
        self.lbl_operador.setText(f"Operador: {texto}")

    def _estado(self, texto="", estado="info"):
        self.lbl_estado.setText(texto)
        aplicar_estado(self.lbl_estado, estado)

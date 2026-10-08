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

from PySide6.QtCore import Qt, QSize, QTimer, Signal
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSizePolicy,
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
    roles_con_permiso,
    rol_tiene_permiso_operador,
)
from src.gui.huella_modal import HuellaModal
from src.gui.modalidades_cierre import (
    MODALIDAD_FOLIO,
    ModalidadCierreDialog,
)
from src.gui.resplandor import Resplandor
from src.gui.style import aplicar_estado, aplicar_estilo_boton
from src.gui.switch import Switch

log = logging.getLogger(__name__)


class InicioView(QWidget):
    # (nombre, rol) al cambiar la sesion; nombre vacio = sin sesion. El
    # header de la App lo consume para pintar nombre + icono persona/engranaje.
    sesion_cambiada = Signal(str, str)

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
        self._primera_pieza = False
        self._primera_pieza_paro_id = None
        # Paro IMPLICITO "Esperando trabajo": cubre el tiempo con sesion
        # abierta, maquina detenida y SIN folio (tras un cierre hasta el
        # siguiente QR, o tras detener sin trabajo). Se abre/cierra solo,
        # sin huella extra: al escanear se atribuye a quien autentica el QR.
        self._espera_trabajo_paro_id = None
        # Timestamp de entrada al modo Primera pieza (para el timeout de
        # autorizacion del punto 2). Se conserva al re-entrar idempotente.
        self._primera_pieza_inicio = None
        self._aviso_timeout_primera_pieza_hecho = False
        self._ajustando_switch = False
        # Modo MANTENIMIENTO: la maquina SIGUE EN MARCHA con el conteo
        # suspendido (los cortes van a excluidos, como en Primera pieza).
        # El paro abierto (PARO) queda como paro del modo y se finaliza al
        # salir con la causa fija 'mantenimiento'. Requiere validacion DOBLE:
        # PRIMERO huella de mantenimiento y LUEGO la del operador.
        self._modo_mantenimiento = False
        self._mantenimiento_zona_id = None
        # Modo PARO: TODO paro autorizado (menos 'mantenimiento', que tiene su
        # propio modo) entra aqui. El paro queda ABIERTO y se cierra con un
        # SEGUNDO paso (SALIR DE PARO) al que se llega pulsando el boton PARO
        # o el central. La maquina queda DETENIDA salvo que la causa requiera
        # zona y esa zona tenga marcada 'maquina encendida': entonces SIGUE EN
        # MARCHA con el conteo suspendido (los cortes van a excluidos).
        self._modo_paro = False
        self._modo_paro_causa_id = None
        self._modo_paro_causa_desc = None
        self._modo_paro_zona_id = None
        self._modo_paro_maquina_encendida = False
        # Estado actual del boton PARO (PARO vs SALIR DE MANTENIMIENTO/
        # SALIR DE PARO en rojo).
        self._boton_paro_especial = False
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
        # baseline se ajusta para RETOMAR desde `cortes_detectados`.
        # `_detectados_al_cargar` son los detectados globales al cargar el
        # folio: restados del vivo dan lo cortado EN ESTA sesion (dialogo de
        # cierre y dialogos por sesion).
        self._trabajo = None
        self._baseline_trabajo = 0
        self._detectados_al_cargar = 0

        self._crear_interfaz()
        self._cerrar_sesion_interrumpida()
        self._refrescar_contador()
        self._checkpoint_cortes()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _crear_interfaz(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(8)

        # Espacio superior flexible
        layout.addStretch(1)

        # Tablero de contadores
        self.tablero = QFrame(self)
        self.tablero.setObjectName("Tablero")
        tab = QVBoxLayout(self.tablero)
        tab.setContentsMargins(16, 8, 16, 8)
        tab.setSpacing(3)

        # NUM PART arriba en AMARILLO (TableroInfo): sin trabajo muestra el
        # unico 'SIN TRABAJO'.
        self.lbl_cortes = QLabel("SIN TRABAJO", self.tablero)
        self.lbl_cortes.setObjectName("TableroInfo")
        self.lbl_cortes.setAlignment(Qt.AlignCenter)
        tab.addWidget(self.lbl_cortes)

        # FOLIO al centro en GRIS (TableroEtiqueta), como texto plano.
        self.display_trabajo = QLabel("", self.tablero)
        self.display_trabajo.setObjectName("TableroEtiqueta")
        self.display_trabajo.setAlignment(Qt.AlignCenter)
        tab.addWidget(self.display_trabajo)

        self.lbl_cortes_trabajo = QLabel("", self.tablero)
        self.lbl_cortes_trabajo.setObjectName("TableroInfo")
        self.lbl_cortes_trabajo.setAlignment(Qt.AlignCenter)
        tab.addWidget(self.lbl_cortes_trabajo)

        layout.addWidget(self.tablero, alignment=Qt.AlignHCenter)

        # Estado de máquina
        fila_estado = QWidget(self)
        h = QHBoxLayout(fila_estado)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(6)
        self.icono_estado = QLabel(fila_estado)
        self.icono_estado.setFixedSize(20, 20)
        h.addWidget(self.icono_estado)
        self.lbl_estado_maquina = QLabel("Maquina: EN ESPERA", fila_estado)
        aplicar_estado(self.lbl_estado_maquina, "pendiente")
        h.addWidget(self.lbl_estado_maquina)
        # Fondo transparente: el QSS global pinta `QWidget { background: @fondo@ }`
        # y esta fila opaca recortaria el resplandor justo antes de su borde.
        # Sin fondo, el glow pasa por detras (como con los botones).
        fila_estado.setStyleSheet("background: transparent;")
        layout.addWidget(fila_estado, alignment=Qt.AlignHCenter)

        # Mensaje de acciones
        self.lbl_estado = QLabel(
            "Inicia sesion para encender la maquina.", self
        )
        aplicar_estado(self.lbl_estado, "info")
        self.lbl_estado.setAlignment(Qt.AlignCenter)
        self.lbl_estado.setWordWrap(True)
        layout.addWidget(self.lbl_estado)

        # Botón MAQUINA
        # El resplandor es una CAPA de fondo que cubre toda la vista y va
        # DETRAS de los demas widgets: no ocupa espacio en el layout (no
        # desplaza al boton) y su glow no se corta al acercarse a los botones
        # de abajo (se funde tapado por ellos). El boton vive en el layout.
        self.resplandor_maquina = Resplandor(radio_extra=110, parent=self)
        self.resplandor_maquina.setGeometry(self.rect())
        self.resplandor_maquina.lower()

        self.btn_maquina = QPushButton(self)
        self.btn_maquina.setObjectName("PowerOn")
        self.btn_maquina.setIconSize(QSize(48, 48))
        self.btn_maquina.setFixedHeight(56)
        self.btn_maquina.clicked.connect(self._toggle_maquina)
        self.resplandor_maquina.add_widget(self.btn_maquina)
        layout.addWidget(self.btn_maquina, alignment=Qt.AlignHCenter)

        # Hueco limpio (espacio de LAYOUT, no del glow) entre el boton de la
        # maquina y PARO para que no queden pegados.
        layout.addSpacing(24)

        # Botones PARO y ESCANEAR
        self.btn_paro = QPushButton("PARO", self)
        self.btn_paro.setMinimumWidth(140)
        self.btn_paro.setFixedHeight(40)
        self.btn_paro.clicked.connect(self._boton_paro)
        layout.addWidget(self.btn_paro, alignment=Qt.AlignHCenter)

        self.btn_escanear = QPushButton("ESCANEAR TRABAJO", self)
        self.btn_escanear.setMinimumWidth(140)
        self.btn_escanear.setFixedHeight(40)
        self.btn_escanear.clicked.connect(self._boton_escanear_trabajo)
        layout.addWidget(self.btn_escanear, alignment=Qt.AlignHCenter)
        self.btn_escanear.setVisible(False)

        # Switch Primera pieza
        self._fila_switch = QWidget(self)
        fila_h = QHBoxLayout(self._fila_switch)
        fila_h.setContentsMargins(0, 0, 0, 0)
        fila_h.setSpacing(8)
        self.switch_primera_pieza = Switch(self._fila_switch)
        self.switch_primera_pieza.toggled.connect(self._switch_primera_pieza)
        fila_h.addWidget(self.switch_primera_pieza)
        lbl_switch = QLabel("Primera pieza", self._fila_switch)
        fila_h.addWidget(lbl_switch)
        # Fondo transparente: sin esto la fila opaca recorta el resplandor
        # justo antes del switch.
        self._fila_switch.setStyleSheet("background: transparent;")
        self._fila_switch.setVisible(False)
        layout.addWidget(self._fila_switch, alignment=Qt.AlignHCenter)

        # Espacio flexible
        layout.addStretch(1)

        # Resumen (abajo)
        self.lbl_resumen = QLabel("", self)
        self.lbl_resumen.setObjectName("ResumenEstado")
        self.lbl_resumen.setAlignment(Qt.AlignCenter)
        self.lbl_resumen.setWordWrap(True)
        layout.addWidget(self.lbl_resumen)

        # Configuración de escalado de fuentes
        self._base_font_size = 9  # Tamaño base de la app (QFont base)
        self._base_window_height = 720  # Altura de referencia
        self._widgets_fuente = [
            (self.lbl_cortes, 16),      # TableroEtiqueta
            (self.lbl_cortes_trabajo, 20),  # TableroInfo
            (self.lbl_estado_maquina, 14),  # Estado maquina
            (self.lbl_estado, 14),       # Mensaje acciones
            (self.lbl_resumen, 11),      # ResumenEstado
            (self.btn_maquina, 15),      # Botones principales
            (self.btn_paro, 15),
            (self.btn_escanear, 15),
        ]

        # Aplicar escala inicial
        self._aplicar_escala_fuente()

    def resizeEvent(self, event):
        """Ajusta tamaños y fuentes al redimensionar la ventana."""
        super().resizeEvent(event)
        # Mantener la capa de resplandor cubriendo toda la vista y detras.
        if getattr(self, "resplandor_maquina", None) is not None:
            self.resplandor_maquina.setGeometry(self.rect())
            self.resplandor_maquina.lower()
        self._actualizar_escalado()

    def _actualizar_escalado(self):
        """Recalcula tamaños y fuentes proporcionales al tamaño de la ventana."""
        h = self.height()
        factor = max(0.6, min(1.5, h / 720.0))
        self._aplicar_escala_fuente(factor)

    def _aplicar_escala_fuente(self, factor=1.0):
        """Aplica escala a fuentes de widgets registrados."""
        from PySide6.QtGui import QFont
        from src.gui import style
        for widget, base_size in self._widgets_fuente:
            if widget is None:
                continue
            new_size = max(8, int(base_size * factor))
            widget.setFont(QFont(style.FAMILIA_FUENTE, new_size))

    # ------------------------------------------------------------------
    # Sesion (boton del header): identidad + TOTALES
    # ------------------------------------------------------------------

    def toggle_sesion(self):
        """Accion del boton de sesion del header (delegada desde la App).

        Sin sesion abre el modal de huella de inicio; con sesion la cierra,
        PERO solo con la maquina detenida: una maquina encendida siempre
        vive dentro de una sesion (al encender entra a Primera pieza y pide
        trabajo), asi que cerrarla en marcha dejaria cortes sin dueno.
        """
        if self._modal_abierto:
            return
        if self.sesion_id is None:
            self._abrir_huella_sesion()
            return
        if not self.controlador.maquina_detenida():
            caja = QMessageBox(self.controller)
            caja.setWindowTitle("No se puede cerrar la sesion")
            caja.setText("La maquina esta EN MARCHA.\n\nDetenla con el boton de maquina antes de cerrar la sesion.")
            caja.setIcon(QMessageBox.Warning)
            caja.addButton("Aceptar", QMessageBox.AcceptRole)
            caja.exec()
            log.warning("Cierre de sesion bloqueado: la maquina esta en "
                        "marcha")
            return
        self._abrir_huella_cierre()

    def _abrir_huella_sesion(self):
        """Modal de huella para INICIAR sesion (cualquier operador registrado).

        Solo identidad: aqui NO se toca el relevo ni el modo Primera pieza;
        eso lo hace el boton de maquina al encender.
        """
        self._modal_abierto = True
        try:
            modal = HuellaModal(
                self.controller,
                self.biometrico,
                titulo="INICIAR SESION",
                mensaje="Coloca tu huella para iniciar la sesion.",
                on_autenticado=self._sesion_abierta,
                on_cancelar=lambda: self._estado(
                    "Inicio de sesion cancelado.", "info"
                ),
                mostrar_dev=config.MODO_DEV,
                on_dev=self._sesion_dev,
            )
            modal.exec()
        finally:
            self._modal_abierto = False

    def _sesion_dev(self):
        """Inicia sesion con el operador temporal de desarrollo (sin lector)."""
        from src.database import obtener_operador_temporal
        id_op, nombre = obtener_operador_temporal()
        self._sesion_abierta(id_op, nombre)
        self._estado(f"Acceso DEV sin lector como '{nombre}'.", "exito")
        log.info("Acceso DEV sin lector iniciado como %s (%s)", nombre, id_op)

    def _sesion_abierta(self, id_operador, nombre, causa_id=None):
        """Sesion abierta: reinicia el contador (el TOTAL es por sesion).

        La maquina NO arranca aqui: queda DETENIDA hasta que el operador
        pulse el boton de maquina.
        """
        self.sesion_id = abrir_sesion(id_operador)
        self.operador_id = id_operador
        self.operador_nombre = nombre
        self.controlador.reset_conteo()
        self._en_paro = False
        self._paro_idle_triggado = False
        self._refrescar_operador()
        self._refrescar_estado_maquina()
        self._estado(
            f"Sesion iniciada por {nombre}. Enciende la maquina para "
            "comenzar.", "exito",
        )
        log.info("Sesion %s abierta para %s", self.sesion_id, nombre)
        # Desde el login corre la espera implicita hasta PLAY o el primer QR.
        self._abrir_espera_trabajo()

    def _apagar_maquina(self, autorizador_id=None) -> bool:
        """Cierra la sesion (solo con la maquina ya detenida). Devuelve True
        si cerro.

        `autorizador_id` es el operador que autentico el cierre (si se pasa);
        por defecto se atribuye al dueno de la sesion, como en Primera pieza.
        El reset del contador vive en la APERTURA de sesion (`_sesion_abierta`),
        no aqui: encender/apagar la maquina ya no toca el acumulado.
        """
        if self._seguro_paro_segundos() is not None:
            self._estado(
                "La maquina esta cortando: espera unos segundos para apagar.",
                "error",
            )
            log.info("Apagado bloqueado por seguro anti-corte")
            return False
        if not self.controlador.maquina_detenida():
            # Camino defensivo: el guard de toggle_sesion deberia haber
            # bloqueado este caso con la maquina en marcha.
            self.controlador.maquina_pausada()
        total = self.controlador.cortes_totales()
        if self.sesion_id is not None:
            self._finalizar_primera_pieza_si_activa(self.operador_id)
            self._cerrar_trabajo_por_cierre_sesion()
            # Paro EN CURSO: cerrarlo junto con la sesion para no dejar filas
            # 'En curso' eternas sobre una sesion ya Finalizada (Diagnostico
            # 7.2.5). En el MODO PARO se cierra con la causa/zona ya elegidas
            # (el operador no llego a pulsar SALIR DE PARO); en un paro aun no
            # autorizado queda SIN causa (la columna lo permite, igual que
            # _cerrar_primera_pieza cuando falta la causa).
            if self.paro_id is not None:
                autorizador = autorizador_id or self.operador_id
                if self._modo_paro:
                    causa_cierre = self._modo_paro_causa_id
                    zona_cierre = self._modo_paro_zona_id
                else:
                    causa_cierre = zona_cierre = None
                try:
                    finalizar_paro(self.paro_id, causa_cierre, autorizador,
                                   zona_cierre)
                    log.info("Paro %s cerrado junto con la sesion "
                             "(autorizado por operador %s, causa %s)",
                             self.paro_id, autorizador, causa_cierre)
                except Exception:  # noqa: BLE001 - no debe frenar el cierre
                    log.warning("No se pudo cerrar el paro %s al cerrar la "
                                "sesion", self.paro_id, exc_info=True)
                self.paro_id = None
            # Espera implicita abierta: se cierra con su causa, atribuida a
            # quien autentico el cierre (o al dueno de la sesion).
            self._cerrar_espera_trabajo(autorizador_id or self.operador_id)
            cerrar_sesion(self.sesion_id, total)
        self.sesion_id = None
        self.operador_id = None
        self.operador_nombre = None
        self.paro_id = None
        self._en_paro = False
        self._paro_idle_triggado = False
        self._primera_pieza = False
        self._primera_pieza_paro_id = None
        self._primera_pieza_inicio = None
        self._espera_trabajo_paro_id = None
        self._modo_mantenimiento = False
        self._mantenimiento_zona_id = None
        self._modo_paro = False
        self._modo_paro_causa_id = None
        self._modo_paro_causa_desc = None
        self._modo_paro_zona_id = None
        self._modo_paro_maquina_encendida = False
        self._fijar_switch(False)
        self._refrescar_operador()
        self._refrescar_estado_maquina()
        self._estado(f"Maquina en espera. {total} cortes registrados.", "info")
        log.info("Sesion cerrada con %s cortes", total)
        return True

    # ------------------------------------------------------------------
    # Boton de MAQUINA (centro): relevo dentro de la sesion
    # ------------------------------------------------------------------

    def _toggle_maquina(self):
        if self._modal_abierto:
            return
        if self.sesion_id is None:
            self._estado(
                "Inicia sesion antes de encender la maquina.", "error"
            )
            return
        if self._en_paro and not self._modo_paro:
            # Paro aun NO autorizado (el del boton PARO no ha pasado el
            # modal): el boton de maquina queda deshabilitado; la salida es
            # autorizando por el boton PARO. En el MODO PARO ya autorizado el
            # boton central sale del modo con huella y deja la maquina
            # encendida, nunca apaga.
            return
        if self._modo_mantenimiento:
            # El boton central (glow ambar) tambien sale del modo con la
            # doble validacion; nunca apaga ni desprotege la maquina.
            self._salir_modo_mantenimiento()
            return
        if self._modo_paro:
            self._salir_modo_paro()
            return
        if self._maquina_en_marcha():
            if self._seguro_paro_segundos() is not None:
                self._estado(
                    "La maquina esta cortando: espera unos segundos para "
                    "apagar.", "error",
                )
                log.info("APAGADO bloqueado por seguro anti-corte")
                return
            self._apagar_maquina_en_marcha()
        else:
            self._encender_maquina()

    def _encender_maquina(self):
        """Entra a espera de trabajo (Primera pieza) DENTRO de la sesion.

        La maquina fisicamente queda APAGADA (punto 3): solo se enciende al
        CARGAR un trabajo (`_trabajo_cargado` -> `maquina_lista()`), para
        hacer los cortes de setup. Asi nunca queda energizada sin trabajo
        cargado. Abre el pedido de trabajo (modal QR).
        """
        self._entrar_primera_pieza(self.operador_nombre)
        self._refrescar_estado_maquina()
        self._estado(
            "En espera de trabajo: escanea un trabajo para encender la "
            "maquina y hacer el setup.", "exito",
        )
        log.info("Espera de trabajo por %s (sesion %s): la maquina queda "
                 "apagada hasta cargar un trabajo.", self.operador_nombre,
                 self.sesion_id)
        self._abrir_modal_trabajo()

    def _apagar_maquina_en_marcha(self):
        """Apaga la maquina manteniendo la sesion abierta.

        Con un trabajo cargado hace el CIERRE COMPLETO (#5): confirma la
        cantidad detectada en un input editable (o modifica el folio), guarda
        la cantidad y detiene el relevo, quedando en espera de trabajo. Sin
        trabajo detiene directo (saliendo del modo Primera
        pieza si estuviera activo). La sesion sigue abierta: solo se cierra
        desde el header con la maquina ya detenida.
        """
        if self._trabajo is not None:
            self._abrir_cierre_con_modalidad(por_meta=False)
            return
        # Detener PRIMERO el relevo y despues salir del modo: cualquier
        # delta en vuelo cae a los excluidos y se descarta con el modo.
        self.controlador.maquina_pausada()
        self._finalizar_primera_pieza_si_activa(self.operador_id)
        self._fijar_switch(False)
        self._refrescar_estado_maquina()
        self._refrescar_labels_cortes()
        self._estado(
            "Maquina detenida. La sesion sigue abierta.", "info"
        )
        log.info("Maquina apagada por %s (sesion %s continua)",
                 self.operador_nombre, self.sesion_id)
        # Sin folio cargado empieza la espera implicita hasta el siguiente QR.
        self._abrir_espera_trabajo()

    def _abrir_cierre_con_modalidad(self, por_meta=False):
        """CIERRE COMPLETO (#5) con cantidad confirmada, comun al apagado
        manual (boton de maquina) y al alcanzar la meta.

        `por_meta=True` indica que la maquina ya llego a la cantidad_total
        (cierre automatico por timer). El flujo es 1) dialogo de cierre (input
        editable + folio modificado) y 2) guardar y DETENER la maquina: la
        confirmacion de la cantidad ES la autorizacion, no se pide huella
        (el operador de la sesion ya esta autenticado al abrirla).
        """
        if self._trabajo is None or self._modal_abierto or self._en_paro:
            return
        # Todo el flujo (dialogo de modalidad) corre con `_modal_abierto`
        # para que el timer de refresco no reabra otro modal en el entretanto.
        self._modal_abierto = True
        try:
            folio = self._trabajo["folio"]
            num_part = self._trabajo["num_part"]
            # Pre-carga con lo cortado EN ESTA SESION (no el acumulado del
            # folio): lo confirmado se suma al global, nunca lo reemplaza.
            cortado = self._cortes_sesion_trabajo()
            meta = self._trabajo["cantidad_total"]
            # 1) Cierre (#5): input con la cantidad detectada (editable) +
            # Folio modificado. Por meta NO se puede cancelar: el operador
            # debe confirmar (no queda un trabajo Abierto con la meta cumplida).
            dlg = ModalidadCierreDialog(
                self, folio, num_part, cortado, meta, cancelable=not por_meta,
            )
            if dlg.exec() != QDialog.Accepted:
                self._estado(
                    "Apagado cancelado; el trabajo sigue abierto.", "info",
                )
                return
            modalidad = dlg.resultado_modalidad
            cantidad_final = dlg.resultado_cantidad
            nuevo_total = dlg.resultado_nuevo_total
            # 2) Sin huella: confirmar la cantidad ya autoriza el cierre.
            self._cerrar_trabajo_confirmado(
                self.operador_id, self.operador_nombre, modalidad,
                cantidad_final, nuevo_total, por_meta=por_meta,
            )
        finally:
            self._modal_abierto = False

    def _cerrar_trabajo_confirmado(self, id_operador, nombre,
                                   modalidad, cantidad_final,
                                   nuevo_total=None, causa_id=None,
                                   por_meta=False):
        """Cierre completo (#5): guarda la cantidad del dialogo y DETIENE la
        maquina.

        `cantidad_final` es AUTORITATIVA (viene del input del dialogo,
        pre-cargado con el conteo detectado y corregible); la capa de BD
        decide el estado del trabajo: alcanza la meta -> 'Cerrado', no ->
        'Abierto' (retomable re-escaneando el folio). La sesion sigue abierta
        con la maquina detenida.
        """
        folio = self._trabajo["folio"]
        meta = self._trabajo["cantidad_total"]
        # Detectados vivos al cerrar (antes de detener): van a
        # `cortes_detectados`; la del dialogo va a `cortes_confirmados`.
        detectados = self._cortes_trabajo()
        self.controlador.maquina_pausada()
        self._finalizar_primera_pieza_si_activa(id_operador)
        self._fijar_switch(False)
        ok, estado, cantidad_final = cerrar_trabajo_modalidad(
            folio, cantidad_final, meta, nuevo_total, modalidad,
            detectados=detectados,
        )
        self._trabajo = None
        self._baseline_trabajo = 0
        self._detectados_al_cargar = 0
        self._refrescar_estado_maquina()
        self._refrescar_labels_cortes()
        if not ok:
            self._estado(
                f"No se pudo guardar el trabajo {folio}: {estado}.",
                "error",
            )
            return
        if por_meta:
            self._sonar_alarma()
            self._estado(
                f"Trabajo {folio} completado ({cantidad_final}/{meta}) "
                f"y maquina detenida. Pulsa PLAY para cargar el siguiente.",
                "procesando",
            )
        else:
            # Mensaje claro segun cierre
            if modalidad == MODALIDAD_FOLIO:
                # nuevo_total es el nuevo total del folio
                self._estado(
                    f"Trabajo {folio} guardado por {nombre}: "
                    f"{cantidad_final} piezas (Folio modificado a {nuevo_total}), "
                    f"maquina detenida.", "exito",
                )
            else:
                self._estado(
                    f"Trabajo {folio} guardado por {nombre} con {cantidad_final} "
                    f"piezas ({estado}) y maquina detenida.", "exito",
                )
        log.info("Trabajo %s guardado (modalidad %s, %s piezas, estado %s) "
                 "y maquina apagada por %s (sesion %s continua%s)", folio,
                 modalidad, cantidad_final, estado, nombre, self.sesion_id,
                 ", por_meta" if por_meta else "")
        # Sin folio cargado empieza la espera implicita hasta el siguiente QR.
        self._abrir_espera_trabajo()

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
            caja = QMessageBox(self.controller)
            caja.setWindowTitle("No se puede cerrar")
            caja.setText("La maquina esta EN MARCHA.\n\nDetenla con el boton PARO antes de cerrar el programa.")
            caja.setIcon(QMessageBox.Warning)
            caja.addButton("Aceptar", QMessageBox.AcceptRole)
            caja.exec()
            log.warning("Salida de la app bloqueada: la maquina esta en "
                        "marcha.")
            return False
        return True

    # ------------------------------------------------------------------
    # Cierre de la sesion que quedo 'Activa' tras un apagon
    # ------------------------------------------------------------------

    def _cerrar_sesion_interrumpida(self):
        """Cierra la sesion 'Activa' heredada de un apagon. NO la recupera.

        Los datos YA estan guardados: el checkpoint de 30 s
        (`_checkpoint_cortes`, `config.CORTES_GUARDAR_INTERVALO_MS`) dejo
        `sesiones_produccion.total_cortes` y `trabajos.cortes_detectados` en
        la BD, asi que tras un corte de luz no hay nada que reconstruir ni que
        pedir autorizacion. Aqui solo se hace la limpieza para que el
        operador entre con una sesion NUEVA:

        1. El trabajo en curso se CONFIRMA con lo detectado (se paso tal cual:
           aqui no hay conteo vivo todavia). Las piezas ya se cortaron y no
           habra quien las vuelva a contar, asi que no se dejan solo como
           detectadas; si el folio llega a la meta queda 'Cerrado', si no
           'Abierto' con su parcial y su segmento cerrado. Se retoma
           escaneando su QR, que lo reactiva desde `cortes_confirmados`.
        2. El paro en curso se cierra con la causa implicita "Computadora
           apagada": se fue la luz y nadie autorizo nada, pero el reporte no
           debe mostrar un paro "(sin causa registrada)".
        3. La sesion pasa a 'Finalizada' con el total del checkpoint.

        La vista queda deliberadamente SIN sesion (`sesion_id=None`): el
        header pide huella de inicio y el operador abre un folio desde cero,
        con su conteo arrancando en 0. El latch PAUSE inicial del HAL
        (`ModbusController._aplicar_paro_inicial`) ya deja la maquina
        fisicamente detenida.
        """
        sesion = obtener_sesion_interrumpida()
        if not sesion:
            return
        sesion_id = sesion["id"]
        operador_id = sesion["operador_id"]
        nombre = sesion["nombre"]
        total = sesion["total_cortes"] or 0
        # 1) Parcial del trabajo: se re-pasa el valor del checkpoint (aun no
        # hay contador vivo que lo supere) y se CONFIRMA, no solo se pausa.
        trabajo = None
        estado_trabajo = None
        confirmados = 0
        # El folio se guarda ANTES de cerrar el trabajo: `confirmar_trabajo_
        # por_apagon` le pone `fecha_fin`, asi que despues
        # `obtener_trabajo_abierto` ya no lo devolveria y el paro del corte de
        # luz saldria sin trabajo aunque la maquina cortara con el cargado.
        folio_en_curso = None
        try:
            trabajo = obtener_trabajo_abierto(sesion_id)
            if trabajo is not None:
                folio_en_curso = trabajo["folio"]
                detectados = trabajo["cortes_detectados"] or 0
                ok, estado_trabajo, confirmados = confirmar_trabajo_por_apagon(
                    trabajo["folio"], detectados
                )
                if not ok:
                    raise RuntimeError(estado_trabajo)
                log.info("Trabajo %s queda %s con %s/%s piezas (sesion %s "
                         "interrumpida: corte de luz)", trabajo["folio"],
                         estado_trabajo, confirmados,
                         trabajo["cantidad_total"], sesion_id)
        except Exception:  # noqa: BLE001 - la limpieza no debe tumbar el arranque
            log.warning("No se pudo cerrar el trabajo de la sesion %s",
                        sesion_id, exc_info=True)
            estado_trabajo = None
        # 2) Paro en curso (Primera pieza, 'Esperando trabajo' o el del boton
        # PARO): se cierra con la causa implicita del corte de luz para no
        # dejar filas 'En curso' ni "(sin causa registrada)" sobre una sesion
        # ya Finalizada.
        try:
            paro = paro_en_curso(sesion_id)
            if paro is not None:
                causa_id = self._causa_id("Computadora apagada")
                if causa_id is None:
                    log.warning("Causa 'Computadora apagada' inactiva o "
                                "inexistente; paro %s sin causa", paro)
                finalizar_paro(paro, causa_id, operador_id)
                log.info("Paro %s cerrado por corte de luz (sesion %s, causa "
                         "%s)", paro, sesion_id, causa_id)
            else:
                # La maquina CORRIA cuando se fue la luz: no habria fila en
                # curso que cerrar, pero el hueco quedaria sin medir. Se
                # escribe el paro entero desde el ultimo corte/arranque
                # conocido hasta el reinicio.
                self._reconstruir_paro_apagon(
                    sesion_id, operador_id, sesion["ultimo_corte"],
                    folio=folio_en_curso,
                )
        except Exception:  # noqa: BLE001 - idem
            log.warning("No se pudo cerrar el paro en curso de la sesion %s",
                        sesion_id, exc_info=True)
        # 3) La sesion queda cerrada con el total del checkpoint.
        try:
            cerrar_sesion(sesion_id, total)
        except Exception:  # noqa: BLE001 - idem
            log.warning("No se pudo cerrar la sesion %s", sesion_id,
                        exc_info=True)
        self._refrescar_operador()
        self._refrescar_estado_maquina()
        if trabajo is not None and estado_trabajo == ESTADO_CERRADO:
            self._estado(
                f"Corte de luz: la sesion de {nombre} se cerro con {total} "
                f"cortes. El trabajo {trabajo['folio']} completo la meta y se "
                f"cerro con {confirmados}/{trabajo['cantidad_total']} piezas "
                "confirmadas. Inicia sesion para el siguiente.",
                "procesando",
            )
        elif trabajo is not None:
            self._estado(
                f"Corte de luz: la sesion de {nombre} se cerro con {total} "
                f"cortes. El trabajo {trabajo['folio']} sigue abierto con "
                f"{confirmados}/{trabajo['cantidad_total']} piezas "
                "confirmadas: inicia sesion y escanea su QR para continuar.",
                "procesando",
            )
        else:
            self._estado(
                f"Corte de luz: la sesion de {nombre} se cerro con {total} "
                "cortes. Inicia sesion para empezar de nuevo.",
                "procesando",
            )
        log.info("Sesion %s interrumpida cerrada por corte de luz (operador "
                 "%s, %s cortes)", sesion_id, nombre, total)

    def _reconstruir_paro_apagon(self, sesion_id, operador_id, ultimo_corte,
                                  folio=None):
        """Escribe el paro del corte de luz cuando la maquina CORRIA.

        Cubre el caso que `paro_en_curso` no alcanza: si no habia ninguna fila
        en curso, la maquina estaba EN MARCHA (contando) y no en paro. Sin
        esto, el tiempo desde el ultimo corte hasta el reinicio no aparece en
        ningun lado y el reporte sale como si la maquina hubiera producido
        todo ese tiempo sin interrupcion.

        El INTERVALO va del ultimo corte (o arranque) conocido al reinicio, no
        del reinicio: medir desde el reinicio daria un paro de cero. `fin` es
        el instante en que se detecto el apagon, para que el hueco no se
        alargue con las horas que el equipo estuvo apagado.

        `folio` lo pasa el llamador y es el trabajo que estaba ABIERTO al
        cortarse la luz. No se vuelve a consultar `obtener_trabajo_abierto`
        porque para este punto ese trabajo ya fue cerrado por
        `confirmar_trabajo_por_apagon` y la consulta exigiria `fecha_fin` nula,
        de ahi que antes saliera 'sin trabajo'. Sin folio, el paro queda sin
        trabajo asociado.
        """
        if not ultimo_corte:
            # Sin ancla no hay intervalo honesto: se cae a `fin` (paro de un
            # instante) en vez de medir desde el inicio de la sesion, que
            # inventaria horas de paro que el operador no hizo.
            log.warning("Sesion %s sin 'ultimo_corte' registrado; el paro del "
                        "corte de luz se registra de duracion cero", sesion_id)
        fin = ahora_local()
        try:
            causa_id = self._causa_id("Computadora apagada")
            paro_id = crear_paro_por_apagon(
                sesion_id, folio, ultimo_corte, operador_id, causa_id, fin=fin,
            )
            log.info("Paro %s reconstruido por corte de luz (sesion %s, folio "
                     "%s, desde %s hasta %s)", paro_id, sesion_id, folio,
                     ultimo_corte, fin)
            return paro_id
        except Exception:  # noqa: BLE001 - la limpieza no debe tumbar el arranque
            log.warning("No se pudo reconstruir el paro del corte de luz de "
                        "la sesion %s", sesion_id, exc_info=True)
            return None

    def _abrir_huella_cierre(self):
        """Cierre de sesion: requiere autorizacion del operador de la sesion
        o de un rol con autoridad (admin/supervisor)."""
        self._modal_abierto = True
        try:
            modal = HuellaModal(
                self.controller,
                self.biometrico,
                titulo="CERRAR SESION",
                mensaje="Coloca tu huella para cerrar la sesion.",
                validador=self._validar_autorizacion_paro,
                on_autenticado=self._cierre_autenticado,
                on_cancelar=lambda: self._estado("Cierre cancelado.", "info"),
            )
            modal.exec()
        finally:
            self._modal_abierto = False

    def _cierre_autenticado(self, id_operador, nombre, causa_id=None):
        sesion_id = self.sesion_id
        if not self._apagar_maquina(autorizador_id=id_operador):
            return
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
        if self._modo_mantenimiento:
            # El boton PARO pasa a SALIR DE MANTENIMIENTO (rojo).
            self._salir_modo_mantenimiento()
            return
        if self._modo_paro:
            # Modo PARO: el boton sirve para SALIR del modo (segunda huella),
            # que cierra el paro y deja la maquina ENCENDIDA. Nunca enciende
            # ni apaga aqui.
            self._salir_modo_paro()
            return
        if self._primera_pieza:
            if self._maquina_en_marcha():
                if self._seguro_paro_segundos() is not None:
                    self._estado(
                        "La maquina esta cortando: espera unos segundos "
                        "para parar.",
                        "error",
                    )
                    log.info("PARO en Primera pieza bloqueado por seguro "
                             "anti-corte")
                    return
                self._pausar_maquina()
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

    def _salir_modo_paro(self):
        """SEGUNDO paso del modo paro: pide la huella del operador que cierra
        el paro. Segun la zona, la maquina sigue en marcha (conteo suspendido)
        o se ENCIENDE aqui mismo; en ambos casos el conteo vuelve a la sesion
        (o a Primera pieza si estaba activa)."""
        if self._modal_abierto:
            return
        causa_id = self._modo_paro_causa_id
        zona_id = self._modo_paro_zona_id
        en_marcha = self._modo_paro_maquina_encendida
        mensaje = (
            "Paro finalizado. Coloca tu huella (operador) para reanudar "
            "la produccion. La maquina sigue en marcha."
            if en_marcha else
            "Paro finalizado. Coloca tu huella (operador) para cerrar el "
            "paro y encender la maquina."
        )
        self._pedir_huella_reanudacion(
            causa_id, zona_id,
            titulo="SALIR DE PARO",
            mensaje=mensaje,
            on_autorizado=lambda id_op, nop, causa=None:
                self._modo_paro_finalizado(id_op, nop),
        )

    def _modo_paro_finalizado(self, id_operador, nombre_operador):
        """Cierra el paro del modo PARO: finaliza el paro con su causa y zona,
        reanuda el conteo (o lo deja suspendido si aun hay Primera pieza
        activa) y ENCIENDE la maquina si estaba detenida.

        El encendido va DESPUES de resolver el conteo, para que el primer
        corte tras reanudar cuente de verdad (y no caiga en excluidos por el
        `suspender_conteo` de Primera pieza)."""
        causa_id = self._modo_paro_causa_id
        zona_id = self._modo_paro_zona_id
        en_marcha = self._modo_paro_maquina_encendida
        finalizar_paro(self.paro_id, causa_id, id_operador, zona_id)
        self.paro_id = None
        self._modo_paro = False
        self._modo_paro_causa_id = None
        self._modo_paro_causa_desc = None
        self._modo_paro_zona_id = None
        self._modo_paro_maquina_encendida = False
        self._en_paro = False
        self._paro_idle_triggado = False
        if self._primera_pieza:
            # El conteo sigue suspendido por el propio modo Primera pieza.
            self.controlador.suspender_conteo()
        else:
            self.controlador.retomar_conteo()
        # Salir del paro ENCIENDE la maquina: si la zona la dejo detenida,
        # el operador no tiene que volver a pulsar el boton central.
        if not en_marcha and self.sesion_id is not None:
            self.controlador.reprisar_maquina()
        self.controlador.reiniciar_gracia_inactividad()
        self._refrescar_estado_maquina()
        self._estado(
            f"Fin de paro autorizado por {nombre_operador}. "
            + ("La maquina sigue en marcha." if en_marcha
               else "Maquina encendida."),
            "exito",
        )
        log.info("Salida del modo paro por %s (sesion %s, maquina %s)",
                 nombre_operador, self.sesion_id,
                 "en marcha" if en_marcha else "encendida")

    def _folio_activo(self):
        """Folio del trabajo en curso de la sesion (o None si no hay folio
        cargado: Primera pieza sin trabajo con permiso o espera de QR)."""
        if self.sesion_id is None:
            return None
        try:
            trabajo = obtener_trabajo_abierto(self.sesion_id)
        except Exception:  # noqa: BLE001 - un paro nunca debe fallar por esto
            log.warning("No se pudo leer el trabajo activo", exc_info=True)
            return None
        return trabajo["folio"] if trabajo is not None else None

    def _pausar_maquina(self, motivo="manual", inicio_hace_s=None):
        self.controlador.maquina_pausada()
        self._en_paro = True
        self.paro_id = iniciar_paro(self.sesion_id, self._folio_activo(),
                                    inicio_hace_s=inicio_hace_s)
        self._refrescar_estado_maquina()
        log.info("Paro %s registrado (%s)", self.paro_id, motivo)
        self._estado("Maquina en PARO. Indica el motivo y autoriza.", "procesando")
        self._abrir_paro_autorizacion()

    def _abrir_paro_autorizacion(self):
        causas = listar_causas_paro(activas_solo=True)
        if not causas:
            caja = QMessageBox(self.controller)
            caja.setWindowTitle("Sin causas")
            caja.setText("No hay causas de paro configuradas. Ve a Administracion.")
            caja.setIcon(QMessageBox.Warning)
            caja.addButton("Aceptar", QMessageBox.AcceptRole)
            caja.exec()
            self._estado("Sin causas de paro; maquina detenida.", "error")
            return

        # Flujo de 2 modales (decision de diseno): PRIMERO se elige causa (+
        # zona si la requiere) en un selector; al CONFIRMAR se abre el SEGUNDO
        # modal que pide la huella de reanudacion/autorizacion.
        def _on_confirmado(causa_id, causa_desc, zona_id, zona_nombre,
                           zona_maquina=False):
            if self._es_causa_mantenimiento(causa_id):
                # Flujo Mantenimiento: PRIMERO huella del personal de
                # mantenimiento y LUEGO la reanudacion del operador.
                self._pedir_huella_mantenimiento(
                    lambda id_mant, nombre_mant, causa=None:
                        self._mantenimiento_entrada_paso_operador(
                            id_mant, nombre_mant, causa_id, zona_id,
                            causa_desc, zona_nombre
                        )
                )
            else:
                # Los DOS modales del paro llevan SIEMPRE el mismo titulo,
                # haya zona o no: 1) 'AUTORIZACION DEL PARO' (elegir causa y
                # zona), 2) 'AUTORIZACION' (la huella que autoriza). Antes
                # el 2º decia 'REANUDACION' con zona y 'AUTORIZAR
                # REANUDACION' sin ella, que no describian lo que hace.
                self._pedir_huella_reanudacion(
                    causa_id, zona_id, causa_desc, zona_nombre,
                    titulo="AUTORIZACION", zona_maquina=zona_maquina,
                )

        self._modal_abierto = True
        try:
            modal = HuellaModal(
                self.controller,
                self.biometrico,
                titulo="AUTORIZACION DEL PARO",
                mensaje="Maquina en PARO. Indica la causa del paro (y la zona).",
                # Un paro normal NO se puede cancelar hasta confirmar la
                # causa: quien paro, autoriza o sale de ahi.
                mostrar_cancelar=False,
                cerrable=False,
                pedir_causa=True,
                on_confirmado=_on_confirmado,
                on_cancelar=lambda: self._estado(
                    "Paro NO autorizado; maquina detenida.", "error"
                ),
            )
            modal.exec()
        finally:
            self._modal_abierto = False

    def _pedir_huella_reanudacion(self, causa_id=None, zona_id=None,
                                  causa_desc=None, zona_nombre=None,
                                  titulo="AUTORIZACION", mensaje=None,
                                  on_autorizado=None, zona_maquina=False):
        """SEGUNDO modal del flujo de paro: pide la huella que AUTORIZA el
        paro, ya con la causa (+ zona) elegida en el primer modal
        ('AUTORIZACION DEL PARO').

        En el flujo de Mantenimiento es el paso del OPERADOR (el personal de
        mantenimiento ya se valido primero): `on_autorizado` recibe el
        id/nombre del operador y `titulo`/`mensaje` van personalizados.
        """
        if mensaje is None:
            detalle = causa_desc or "(sin causa)"
            if zona_nombre:
                detalle += f" - {zona_nombre}"
            mensaje = f"Maquina en PARO. Causa: {detalle}. Coloca tu huella."

        # La causa/zona ya elegidas se pasan como `causa_id`/`zona_id` al
        # autorizador; el validador (permiso) no necesita la causa.
        def _autorizado(id_operador, nombre, causa=None):
            if on_autorizado is not None:
                on_autorizado(id_operador, nombre, causa)
            else:
                self._autorizado_autenticado(
                    id_operador, nombre, causa_id, zona_id, zona_maquina,
                    zona_nombre, causa_desc
                )

        self._modal_abierto = True
        try:
            modal = HuellaModal(
                self.controller,
                self.biometrico,
                titulo=titulo,
                mensaje=mensaje,
                # Un paro normal NO se puede cancelar hasta autorizar.
                mostrar_cancelar=False,
                cerrable=False,
                validador=self._validar_autorizacion_paro,
                on_autenticado=_autorizado,
                on_cancelar=lambda: self._estado(
                    "Paro NO autorizado; maquina detenida.", "error"
                ),
            )
            modal.exec()
        finally:
            self._modal_abierto = False

    def _validar_autorizacion_paro(self, id_operador, nombre, causa_id=None):
        """Solo autoriza (reanudar paro, cerrar sesion o reanudar la
        produccion tras mantenimiento) el dueno de la sesion o un rol con el
        permiso 'autorizar_supervision' (Supervisor/Admin; gestionado en
        Administracion). Mantenimiento NO autoriza este modal."""
        if id_operador == self.operador_id:
            return True, None
        if rol_tiene_permiso_operador(id_operador, "autorizar_supervision"):
            return True, None
        return False, (
            "Solo el operador de la sesión, Supervisor o Admin "
            "puede autorizar esta acción"
        )

    def _autorizado_autenticado(self, id_operador, nombre, causa_id=None,
                                zona_id=None, zona_maquina=False,
                                zona_nombre=None, causa_desc=None):
        """Paro autorizado: entra al MODO PARO (unico, para toda causa salvo
        'mantenimiento', que tiene su propio modo).

        El paro queda ABIERTO en BD y se cierra en un SEGUNDO paso
        ('SALIR DE PARO', con huella del operador). Lo unico que depende de la
        zona es la maquina:

        - `zona_maquina=True` (la causa requiere zona y la zona tiene marcada
          'maquina encendida'): la maquina REPRENDE con el conteo suspendido
          (los cortes van a excluidos, como en Mantenimiento).
        - `zona_maquina=False` (zona normal o causa que no requiere zona): la
          maquina se queda DETENIDA donde la paro `_pausar_maquina` la dejo.
        """
        self._modo_paro = True
        self._modo_paro_causa_id = causa_id
        self._modo_paro_causa_desc = (
            causa_desc or self._causa_descripcion(causa_id) or "(sin causa)"
        )
        self._modo_paro_zona_id = zona_id
        self._modo_paro_maquina_encendida = bool(zona_maquina)
        self._en_paro = True
        self._paro_idle_triggado = False
        if zona_maquina:
            self.controlador.reprisar_maquina()
            self.controlador.suspender_conteo()
        self._refrescar_estado_maquina()
        zona_nom = zona_nombre or (str(zona_id) if zona_id is not None else None)
        if zona_maquina:
            self._estado(
                f"Paro autorizado por {nombre}. Zona '{zona_nom}' deja la "
                "maquina en marcha; los cortes NO cuentan. Pulsa SALIR DE "
                "PARO al terminar.",
                "procesando",
            )
        else:
            self._estado(
                f"Paro autorizado por {nombre}. Maquina detenida. Pulsa "
                "SALIR DE PARO al terminar.",
                "procesando",
            )
        log.info("Paro %s autorizado por %s en la sesion %s (causa %s, zona "
                 "%s, maquina %s)", self.paro_id, nombre, self.sesion_id,
                 causa_id, zona_id, "en marcha" if zona_maquina else "detenida")

    def _es_causa_mantenimiento(self, causa_id) -> bool:
        return (causa_id is not None
                and causa_id == self._causa_mantenimiento_id())

    def _causa_mantenimiento_id(self):
        return self._causa_id("mantenimiento")

    def _causa_id(self, descripcion):
        """Id de una causa por su descripcion (comparacion tolerante a
        mayusculas/espacios). None si no existe o esta inactiva: la columna
        `causa_id` de `paros_produccion` es nullable y el reporte muestra
        "(sin causa registrada)". Las llama el sistema, nunca el operador."""
        objetivo = str(descripcion).strip().lower()
        for causa in listar_causas_paro(activas_solo=True):
            if str(causa["descripcion"]).strip().lower() == objetivo:
                return causa["id"]
        return None

    def _causa_descripcion(self, causa_id):
        """Descripcion de una causa por su id, o None si no existe. Se consulta
        SIN filtrar por activo: una causa puede desactivarse mientras el paro
        sigue abierto y el estado del modo PARO debe seguir mostrandola."""
        if causa_id is None:
            return None
        for causa in listar_causas_paro(activas_solo=False):
            if causa["id"] == causa_id:
                return str(causa["descripcion"])
        return None

    def _validar_mantenimiento(self, id_operador, nombre, causa_id=None):
        """Solo personal de mantenimiento autorizado valida la entrada, la
        salida y la confirmacion de corrida del modo."""
        if rol_tiene_permiso_operador(id_operador, "autorizar_mantenimiento"):
            return True, None
        return False, (
            "Solo el personal de mantenimiento puede validar esta acción"
        )

    def _pedir_huella_mantenimiento(self, on_autenticado, titulo="AUTORIZACION MANTENIMIENTO"):
        """PRIMER modal del flujo de Mantenimiento: huella del personal
        autorizado. El `on_autenticado` recibe (id_mant, nombre_mant,
        causa_id)."""
        self._modal_abierto = True
        try:
            modal = HuellaModal(
                self.controller,
                self.biometrico,
                titulo=titulo,
                mensaje=(
                    "Coloca la huella de PERSONAL DE MANTENIMIENTO "
                    "para validar."
                ),
                validador=self._validar_mantenimiento,
                on_autenticado=on_autenticado,
                on_cancelar=lambda: self._estado(
                    "Autorizacion de mantenimiento cancelada.", "info"
                ),
                mostrar_cancelar=True,
            )
            modal.exec()
        finally:
            self._modal_abierto = False

    def _mantenimiento_entrada_paso_operador(self, id_mant, nombre_mant,
                                             causa_id, zona_id, causa_desc,
                                             zona_nombre):
        """Tras la huella de mantenimiento: la del OPERADOR REANUDA el paro y
        arranca el modo Mantenimiento (la maquina sigue en marcha)."""
        self._pedir_huella_reanudacion(
            causa_id, zona_id, causa_desc, zona_nombre,
            titulo="AUTORIZACION OPERADOR",
            mensaje=(
                "Mantenimiento autorizado. Coloca tu huella "
                "(operador) para reanudar y entrar en Mantenimiento."
            ),
            on_autorizado=lambda id_op, nop, causa=None:
                self._modo_mantenimiento_iniciado(
                    id_op, nop, id_mant, nombre_mant, causa_id, zona_id
                )
        )

    def _modo_mantenimiento_iniciado(self, id_operador, nombre_operador,
                                     id_mant, nombre_mant, causa_id, zona_id):
        """Entra al modo Mantenimiento.

        El paro abierto (PARO) queda ABIERTO como paro del modo y se
        finaliza al salir con la causa fija 'mantenimiento'. La maquina se
        REACTIVA (sigue en marcha) y el conteo se suspende: los cortes van a
        excluidos (solo memoria), como en Primera pieza.
        """
        self.controlador.reprisar_maquina()
        self.controlador.suspender_conteo()
        self._mantenimiento_zona_id = zona_id
        self._en_paro = False
        self._paro_idle_triggado = False
        self._modo_mantenimiento = True
        self._fijar_switch(False)
        # Baseline nuevo del seguro anti-corrida (descarta muestras de un
        # modo anterior).
        self._muestras_rafaga.clear()
        self._ultimo_excluidos = self.controlador.cortes_excluidos()
        self._refrescar_estado_maquina()
        self._estado(
            f"Modo Mantenimiento autorizado por {nombre_operador} y "
            f"{nombre_mant}. La maquina sigue en marcha; los cortes NO "
            "cuentan. Pulsa SALIR DE MANTENIMIENTO al terminar.",
            "procesando",
        )
        log.info("Modo Mantenimiento iniciado (paro %s) validado por %s y %s "
                 "en la sesion %s", self.paro_id, nombre_operador, nombre_mant,
                 self.sesion_id)

    def _salir_modo_mantenimiento(self):
        """Salida del modo: doble validacion con PRIMERO la huella del
        personal de mantenimiento y LUEGO la del operador que reanuda. La
        maquina SIGUE EN MARCHA; solo se cierra el paro del modo y el conteo
        vuelve a la sesion.
        """
        if self._modal_abierto:
            return
        self._pedir_huella_mantenimiento(
            self._salir_mantenimiento_paso_operador,
            titulo="REANUDACION MANTENIMIENTO"
        )

    def _salir_mantenimiento_paso_operador(self, id_mant, nombre_mant,
                                           causa_id=None):
        """2da huella de la salida: el OPERADOR reanuda la produccion."""
        self._pedir_huella_reanudacion(
            titulo="REANUDACION OPERADOR",
            mensaje=(
                "Mantenimiento finalizado. Coloca tu huella (operador) "
                "para reanudar la produccion."
            ),
            on_autorizado=lambda id_op, nop, causa=None:
                self._mantenimiento_finalizado(
                    id_mant, nombre_mant, id_op, nop
                )
        )

    def _mantenimiento_finalizado(self, id_mant, nombre_mant,
                                  id_operador, nombre_operador):
        """Salida del modo Mantenimiento: cierra el paro con causa fija y
        REANUDA el conteo; la maquina sigue en marcha produciendo."""
        self._finalizar_modo_mantenimiento(id_operador, id_mant,
                                           incorporar=False)
        self._refrescar_estado_maquina()
        self._refrescar_labels_cortes()
        self._estado(
            f"Fin de Mantenimiento autorizado por {nombre_mant} y "
            f"{nombre_operador}. La maquina sigue en marcha.",
            "exito",
        )
        log.info("Salida de Mantenimiento por %s y %s (sesion %s)",
                 nombre_mant, nombre_operador, self.sesion_id)

    def _finalizar_modo_mantenimiento(self, id_operador, id_mant,
                                      incorporar=False, cantidad=None):
        """Cierra el paro del modo Mantenimiento (causa fija + autorizador de
        mantenimiento).

        Con `incorporar=False` los cortes del modo se descartan y el conteo
        normal se REANUDA. Con `incorporar=True` se confirman como
        produccion de la sesion. Devuelve cuantos cortes se incorporaron.
        """
        if not self._modo_mantenimiento:
            return 0
        causa_id = self._causa_mantenimiento_id()
        if causa_id is None:
            log.warning("Causa 'mantenimiento' inactiva; paro %s sin causa",
                        self.paro_id)
        excluidos = self.controlador.cortes_excluidos() if incorporar else 0
        finalizar_paro(self.paro_id, causa_id, id_mant,
                       self._mantenimiento_zona_id)
        self.paro_id = None
        self._modo_mantenimiento = False
        self._mantenimiento_zona_id = None
        if incorporar:
            self.controlador.incorporar_excluidos(cantidad)
            incorporados = (
                excluidos if cantidad is None
                else min(max(int(cantidad), 0), excluidos)
            )
        else:
            incorporados = 0
            self.controlador.retomar_conteo()
        self.controlador.reiniciar_gracia_inactividad()
        # El switch de Primera pieza refleja el estado REAL del modo al salir
        # de Mantenimiento: si se entro estando en Primera pieza, el sistema
        # sigue en Primera pieza y el switch debe volver a quedarse ENCENDIDO.
        self._fijar_switch(self._primera_pieza)
        return incorporados

    # ------------------------------------------------------------------
    # Inactividad -> auto paro
    # ------------------------------------------------------------------

    def _refrescar_contador(self):
        self._refrescar_labels_cortes()
        self._verificar_rafaga_arranque()
        # Auto-finalizacion por meta INHABILITADA: al alcanzar la
        # cantidad_total ya NO se abre solo el dialogo de cierre; el cierre
        # es manual (boton de MAQUINA). El metodo se conserva intacto para
        # reactivarlo descomentando esta linea.
        # self._verificar_meta_trabajo()
        self._refrescar_estado_maquina()
        self._verificar_inactividad()
        self._verificar_timeout_primera_pieza()
        QTimer.singleShot(config.REFRESCO_CONTADOR_MS, self._refrescar_contador)

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

    def _refrescar_labels_cortes(self):
        """Tablero simplificado: NUMERO DE PARTE arriba (amarillo), el FOLIO
        al centro (gris) y CANTIDAD/META abajo. Sin trabajo solo el 'SIN
        TRABAJO' amarillo de arriba. El resto de los datos (sesion, ciclos
        totales, setup) vive en la linea de resumen inferior
        (`_refrescar_resumen`)."""
        if self._trabajo is None:
            self.lbl_cortes.setText("SIN TRABAJO")
            self.display_trabajo.setText("")
            self.lbl_cortes_trabajo.setText("CANTIDAD: ----")
            self._refrescar_resumen()
            return
        # Num part arriba (amarillo) y el FOLIO al centro (gris).
        self.lbl_cortes.setText(str(self._trabajo["num_part"]))
        self.display_trabajo.setText(f"{int(self._trabajo['folio'])}")
        # Debajo de los digitos SOLO la meta del folio con su etiqueta
        # ("CANTIDAD: 200").
        self.lbl_cortes_trabajo.setText(
            f"CANTIDAD: {self._trabajo['cantidad_total']}"
        )
        self._refrescar_resumen()

    def _refrescar_resumen(self):
        """Linea inferior de ESTADO: sesion, folio, numero de parte,
        cantidad CONFIRMADA global del folio, meta, ciclos totales de la
        sesion y piezas de setup (excluidas). Sin trabajo los campos del
        folio van en guion; los ciclos y el setup siempre son visibles."""
        t = self._trabajo
        try:
            conf_global = (t["cortes_confirmados"] or 0) if t else 0
        except (KeyError, IndexError, TypeError):
            conf_global = 0
        partes = [
            f"SESION {self.operador_nombre or '-'}",
            f"FOLIO {t['folio'] if t else '-'}",
            f"PARTE {t['num_part'] if t else '-'}",
            f"CANTIDAD {conf_global}" if t else "CANTIDAD -",
            f"META {t['cantidad_total'] if t else '-'}",
            f"CICLOS TOTALES {self.controlador.cortes_totales()}",
            f"SETUP {self.controlador.cortes_excluidos()}",
        ]
        self.lbl_resumen.setText("  |  ".join(partes))

    def _checkpoint_cortes(self):
        """Guarda periodicamente el total de cortes de la sesion activa.

        Respaldos ante apagones: si se va la luz, la sesion conserva el
        ultimo conteo en la base de datos (ver config.CORTES_GUARDAR_INTERVALO_MS).

        Ademas persiste `ultimo_corte`: el HAL lo lleva en memoria, asi que
        sin esto, al reiniciar tras un corte de luz no habria forma de saber
        desde que momento medir el paro con la maquina en marcha (quedaria
        en cero). El ancla es el ULTIMO ARRANQUE: la corrida que se corta
        empezo ahi, no en el corte anterior. Tomar el min con el ultimo corte
        alargaba el paro hacia atras (hasta el corte previo, que pudovenir de
        una corrida ya cerrada); por eso el corte solo es RESPALDO: si el HAL
        no expone arranque, o si la maquina esta DETENIDA (el HAL devuelve
        inf y no hay arranque nuevo que anclar) se conserva el ultimo corte
        conocido.

        El cuerpo va en try/finally: una excepcion NO debe romper la cadena
        de `QTimer.singleShot`, o los respaldos ante apagones se detendrian
        en silencio hasta reiniciar la app.
        """
        try:
            if self.sesion_id is not None:
                actualizar_cortes_sesion(self.sesion_id,
                                         self.controlador.cortes_totales())
                ancla = (self._momento_ultimo_arranque()
                         or self._momento_ultimo_corte())
                if ancla:
                    registrar_ultimo_corte(self.sesion_id, ancla)
            if self._trabajo is not None:
                actualizar_detectados(
                    self._trabajo["folio"], self._cortes_trabajo()
                )
        except Exception:  # noqa: BLE001 - el proximo checkpoint debe llegar
            log.warning("Fallo el checkpoint de cortes (sesion %s)",
                        self.sesion_id, exc_info=True)
        finally:
            QTimer.singleShot(
                config.CORTES_GUARDAR_INTERVALO_MS, self._checkpoint_cortes
            )

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
        sin_trabajo = self._tiene_permiso_iniciar_primera_pieza()
        mensaje = (
            "Escanea el QR del trabajo "
            "(folio|num_part|cantidad_total) y confirma con tu huella. "
            "El conteo inicia al salir del modo Primera pieza."
        )
        if sin_trabajo:
            mensaje += (
                " Si dejas el campo vacio y pones tu huella, entras a "
                "Primera pieza SIN trabajo (permiso concedido)."
            )
        self._modal_abierto = True
        try:
            modal = HuellaModal(
                self.controller,
                self.biometrico,
                titulo="TRABAJO NUEVO",
                mensaje=mensaje,
                validador=self._validar_autorizacion_paro,
                pedir_trabajo=True,
                permitir_sin_trabajo=sin_trabajo,
                mostrar_cancelar=True,
                cerrable=True,
                on_autenticado=self._trabajo_cargado,
                on_cancelar=self._cancelar_modal_trabajo,
            )
            modal.exec()
        finally:
            self._modal_abierto = False

    def _tiene_permiso_iniciar_primera_pieza(self) -> bool:
        """Permiso `iniciar_primera_pieza` del operador de la sesion (punto 4)."""
        if self.operador_id is None:
            return False
        return rol_tiene_permiso_operador(
            self.operador_id, "iniciar_primera_pieza"
        )

    def _cancelar_modal_trabajo(self):
        """QR cancelado/vaCio (punto 4): permanecer en Primera pieza SIN
        trabajo solo si el operador de la sesion tiene el permiso
        `iniciar_primera_pieza` (mantenimiento/admin). Si no, el modo se
        cierra y la maquina queda detenida (espera de trabajo sin permiso
        no se mantiene)."""
        if self._tiene_permiso_iniciar_primera_pieza():
            self._estado(
                "Primera pieza sin trabajo aprobada (rol autorizado): los "
                "cortes no cuentan.", "info",
            )
            log.info("Primera pieza sin trabajo mantenida por %s (permiso "
                     "iniciar_primera_pieza)", self.operador_nombre)
            return
        self._finalizar_primera_pieza_si_activa(self.operador_id)
        self._fijar_switch(False)
        self._refrescar_estado_maquina()
        self._refrescar_labels_cortes()
        permitidos = " o ".join(roles_con_permiso("iniciar_primera_pieza")) or (
            "un rol autorizado"
        )
        self._estado(
            f"Sin trabajo y sin permiso para Primera pieza: la maquina se "
            f"detuvo. Solo {permitidos} puede iniciarla sin trabajo.",
            "error",
        )
        log.warning("Primera pieza sin trabajo cancelada para %s: "
                    "no tiene el permiso iniciar_primera_pieza",
                    self.operador_nombre)
        # Maquina detenida sin folio ni modo: empieza la espera implicita.
        self._abrir_espera_trabajo()

    def _trabajo_cargado(self, id_operador, nombre, causa_id,
                         folio, num_part, cantidad_total):
        """QR + huella aceptados: registra/retoma el folio EN ESPERA o, si la
        huella llego SIN QR (permitir_sin_trabajo), entra a Primera pieza
        SIN trabajo con la maquina ENCENDIDA (exige permiso).

        En ningun caso sale del modo Primera pieza: el conteo del trabajo
        arranca hasta que el operador autorice la salida del modo (switch
        + huella).
        """
        if folio is None:
            self._entrar_primera_pieza_sin_trabajo(
                id_operador, nombre
            )
            return
        # Fin de la espera: el QR trae su propia huella, que autoriza el
        # cierre del paro implicito.
        self._cerrar_espera_trabajo(id_operador)
        ok, res = abrir_trabajo(folio, self.sesion_id, num_part,
                                cantidad_total)
        if not ok:
            log.warning("Trabajo %s rechazado: %s", folio, res)
            caja = QMessageBox(self.controller)
            caja.setWindowTitle("Trabajo rechazado")
            caja.setText(str(res))
            caja.setIcon(QMessageBox.Warning)
            caja.addButton("Aceptar", QMessageBox.AcceptRole)
            caja.exec()
            self._abrir_modal_trabajo()
            return
        self._trabajo = res
        guardada = res["cortes_detectados"] or 0
        self._detectados_al_cargar = guardada
        # Al cargar un trabajo la maquina ENCIENDE para los cortes de setup
        # (punto 3): estando en espera de trabajo con el relevo apagado,
        # el arranque real ocurre aqui, no al pulsar PLAY.
        if self.controlador.maquina_detenida():
            self.controlador.maquina_lista()
            log.info("Maquina encendida (setup) al cargar el trabajo %s",
                     folio)
        # Baseline fijo desde la carga: los cortes de setup siguen
        # excluidos (total congelado), asi que `_cortes_trabajo()` muestra
        # lo ya hecho del folio y al salir del modo empieza a sumar.
        self._baseline_trabajo = self.controlador.cortes_totales() - guardada
        self._refrescar_labels_cortes()
        confirmados = res["cortes_confirmados"] or 0
        self._estado(
            f"Trabajo {res['folio']} ({res['num_part']}) cargado por "
            f"{nombre} ({confirmados}/{res['cantidad_total']}). Sal del modo "
            "Primera pieza con tu huella para empezar.", "exito",
        )
        log.info("Trabajo %s (%s) cargado en espera por %s a la sesion %s "
                 "(retoma %s/%s)", res["folio"], res["num_part"], nombre,
                 self.sesion_id, guardada, res["cantidad_total"])

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

    def _cortes_trabajo(self):
        """Cortes hechos DENTRO del trabajo abierto (total - baseline).

        Es el acumulado GLOBAL del folio en vivo (retoma desde lo ya
        cortado): alimenta el label, la meta y el checkpoint."""
        if self._trabajo is None:
            return 0
        return max(
            self.controlador.cortes_totales() - self._baseline_trabajo, 0
        )

    def _cortes_sesion_trabajo(self):
        """Cortes del folio hechos EN ESTA sesion (vivo - al cargar).

        Es lo que pre-carga el dialogo de cierre: en una sesion retomada
        sin cortes muestra 0 aunque el folio traiga acumulado.
        """
        if self._trabajo is None:
            return 0
        return max(self._cortes_trabajo() - self._detectados_al_cargar, 0)

    def _confirmable_trabajo(self):
        """Piezas con las que se podria completar el folio YA: confirmados
        globales acumulados + lo cortado en ESTA sesion.

        Dispara el auto-cierre por meta (no el vivo global: con
        sobreproduccion el vivo supera la meta pero quiza falten confirmadas,
        y en una retomada sin cortes no debe naggear).
        """
        if self._trabajo is None:
            return 0
        try:
            previos = self._trabajo["cortes_confirmados"] or 0
        except (KeyError, IndexError, TypeError):
            previos = 0
        return previos + self._cortes_sesion_trabajo()

    def _verificar_meta_trabajo(self):
        """Meta alcanzable: abre el cierre con cantidad a confirmar sin detener
        la maquina.

        AUTO-FINALIZACION INHABILITADA: la llamada desde
        `_refrescar_contador` quedo comentada, asi que este metodo NO se
        invoca (el cierre al llegar a la meta es manual, boton de MAQUINA).
        Se conserva intacto para reactivarlo.

        Llamado desde `_refrescar_contador` (hilo principal). Cuando lo
        confirmado global mas lo cortado en ESTA sesion alcanza la
        cantidad_total se abre el mismo cierre con input editable que el boton
        de MAQUINA (#5) — el operador confirma/corrige la cantidad (o modifica
        el folio); esa confirmacion autoriza el cierre, sin huella. La
        maquina SIGUE EN MARCHA y contando mientras se resuelve el cierre
        (el operador la detiene al confirmar); lo que se guarda es el numero
        confirmado, no el conteo en vivo. Un
        trabajo solo pasa a 'Cerrado' al alcanzarse la meta (hoy: solo en el
        cierre manual).
        """
        if self._trabajo is None or self._modal_abierto or self._en_paro:
            return
        if self._confirmable_trabajo() < self._trabajo["cantidad_total"]:
            return
        # No se detiene la maquina: mientras el modal de cierre esta abierto
        # sigue contando; `_cerrar_trabajo_confirmado` la detiene al
        # confirmar el cierre.
        self._abrir_cierre_con_modalidad(por_meta=True)

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
        self._detectados_al_cargar = 0
        log.info("Trabajo %s con parcial guardado al cerrar la sesion "
                 "(%s piezas, sigue Abierto)", folio, real)

    # ------------------------------------------------------------------
    # Seguro anti-corrida durante "Primera pieza"
    # ------------------------------------------------------------------

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

    def _corrida_mantenimiento_paso_operador(self, id_mant, nombre_mant,
                                             causa_id=None):
        """Tras la huella de mantenimiento: el OPERADOR confirma la corrida."""
        self._pedir_huella_reanudacion(
            titulo="REANUDACION OPERADOR",
            mensaje=(
                "Mantenimiento autorizado. Coloca tu huella (operador) para "
                "contar los cortes como produccion de la sesion."
            ),
            on_autorizado=lambda id_op, nop, causa=None:
                self._corrida_confirmada_mantenimiento(
                    id_mant, nombre_mant, id_op, nop
                )
        )

    def _corrida_confirmada_mantenimiento(self, id_mant, nombre_mant,
                                          id_operador, nombre):
        """Corrida confirmada en Mantenimiento: incorpora SOLO los cortes de
        la ventana detectada y posteriores (los previos de setup quedan
        descartados) y FINALIZA el modo; la maquina sigue en marcha."""
        a_incorporar = max(
            self.controlador.cortes_excluidos() - self._excluidos_previos_rafaga,
            0,
        )
        n = self._finalizar_modo_mantenimiento(
            id_operador, id_mant, incorporar=True, cantidad=a_incorporar
        )
        self._refrescar_estado_maquina()
        self._refrescar_labels_cortes()
        self._estado(
            f"Corrida confirmada por {nombre_mant} y {nombre}: {n} cortes "
            "incorporados al conteo. Fin de Mantenimiento.",
            "exito",
        )
        log.info("Corrida en Mantenimiento confirmada por %s y %s: %s cortes "
                 "incorporados (%s previos descartados como prueba)",
                 nombre_mant, nombre, n, self._excluidos_previos_rafaga)

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

    def _estado_actual(self):
        """Fuente UNICA del estado sesion/maquina.

        Devuelve un dict con: clave, texto y badge del indicador, iconos
        (tablero y boton de maquina), estilo del boton y si esta habilitado.
        Los consumidores (`_refrescar_estado_maquina`, futuros badges)
        leen de aqui; nunca derivan el estado por su cuenta.

        Estados: sin_sesion / en_paro / detenida (sesion activa, relevo
        apagado) / espera_trabajo (en marcha, modo Primera pieza) / lista
        (en marcha, produccion).
        """
        sp = QStyle.StandardPixmap
        if self.sesion_id is None:
            return dict(
                clave="sin_sesion", texto="Maquina: EN ESPERA",
                badge="pendiente", icono=sp.SP_MediaPause,
                btn_icono=sp.SP_MediaPlay, btn_estilo="PowerOn", btn_on=False,
                tooltip="Inicia sesion para encender la maquina",
            )
        # MODO PARO (paro autorizado): el paro sigue ABIERTO y se cierra con
        # 'SALIR DE PARO' (boton central o PARO rojo). La maquina esta EN
        # MARCHA solo si la zona lo requiere; si no, sigue DETENIDA. Va ANTES
        # del chequeo generico de `_en_paro` para que no lo oculte.
        if self._modo_paro:
            en_marcha = self._modo_paro_maquina_encendida
            causa_txt = self._modo_paro_causa_desc or "(sin causa)"
            return dict(
                clave="modo_paro" if en_marcha else "modo_paro_detenida",
                texto=f"Maquina: PARO ({causa_txt})",
                badge="procesando", icono=sp.SP_MediaStop,
                btn_icono=sp.SP_MediaStop, btn_estilo="Power",
                btn_on=en_marcha,
                tooltip=("Salir del paro (la maquina sigue en marcha)"
                         if en_marcha
                         else "Salir del paro (la maquina sigue detenida)"),
            )
        if self._en_paro:
            return dict(
                clave="en_paro", texto="Maquina: EN PARO",
                badge="procesando", icono=sp.SP_MediaPause,
                btn_icono=sp.SP_MediaStop, btn_estilo="Power", btn_on=False,
                tooltip="Resuelve el paro para habilitar la maquina",
            )
        # Mantenimiento: la maquina SIGUE EN MARCHA con el conteo suspendido.
        # Salir del modo (boton central o PARO rojo) pide la doble validacion.
        if self._modo_mantenimiento:
            return dict(
                clave="mantenimiento", texto="Maquina: MANTENIMIENTO",
                badge="procesando", icono=sp.SP_MediaStop,
                btn_icono=sp.SP_MediaStop, btn_estilo="Power", btn_on=True,
                tooltip="Salir del modo Mantenimiento",
            )
        # Espera de trabajo / Primera pieza: PRIORIDAD antes del chequeo de
        # marcha, porque puede darse con la maquina APAGADA (aun sin trabajo
        # cargado, punto 3) o ENCENDIDA (cortes de setup).
        if self._primera_pieza:
            if self._maquina_en_marcha():
                return dict(
                    clave="espera_trabajo", texto="Maquina: PRIMERA PIEZA",
                    badge="procesando", icono=sp.SP_MediaPlay,
                    btn_icono=sp.SP_MediaStop, btn_estilo="Power",
                    btn_on=True,
                    tooltip="Apagar maquina (detiene el setup de Primera pieza)",
                )
            return dict(
                clave="espera_trabajo", texto="Maquina: ESPERA TRABAJO",
                badge="procesando", icono=sp.SP_MediaPause,
                btn_icono=sp.SP_MediaPlay, btn_estilo="PowerOn", btn_on=True,
                tooltip="Cargar un trabajo (QR+huella) para encender la maquina",
            )
        if not self._maquina_en_marcha():
            return dict(
                clave="detenida", texto="Maquina: DETENIDA",
                badge="info", icono=sp.SP_MediaPause,
                btn_icono=sp.SP_MediaPlay, btn_estilo="PowerOn", btn_on=True,
                tooltip="Encender maquina",
            )
        return dict(
            clave="lista", texto="Maquina: LISTA",
            badge="exito", icono=sp.SP_MediaPlay,
            btn_icono=sp.SP_MediaStop, btn_estilo="Power", btn_on=True,
            tooltip="Apagar maquina (con trabajo: lo guarda y detiene)",
        )

    def _refrescar_estado_maquina(self):
        """Pinta el estado desde `_estado_actual` (fuente unica) y
        actualiza los resplandores y el boton PARO."""
        e = self._estado_actual()
        estilo = self.style()
        self.lbl_estado_maquina.setText(e["texto"])
        aplicar_estado(self.lbl_estado_maquina, e["badge"])
        self._icono_estado(estilo, e["icono"])
        self.btn_maquina.setIcon(estilo.standardIcon(e["btn_icono"]))
        aplicar_estilo_boton(self.btn_maquina, e["btn_estilo"])
        self.btn_maquina.setEnabled(e["btn_on"])
        self.btn_maquina.setToolTip(e["tooltip"])
        # Resplandores en el boton CENTRAL (grande e intenso): AMARILLO en
        # Primera pieza, AMBAR en Mantenimiento y en el PARO con la maquina
        # EN MARCHA, y VERDE al producir. El modo PARO con la maquina
        # DETENIDA no resplandece (esta apagada, como un paro normal).
        if self._modo_mantenimiento or (self._modo_paro
                                        and self._modo_paro_maquina_encendida):
            self.resplandor_maquina.set_resplandor("mantenimiento")
        elif self._primera_pieza:
            self.resplandor_maquina.set_resplandor("amarillo")
        elif e["clave"] == "lista":
            self.resplandor_maquina.set_resplandor("exito")
        else:
            self.resplandor_maquina.detener_resplandor()
        self._fila_switch.setVisible(
            self.sesion_id is not None
            and not self._en_paro
            and not self._modo_mantenimiento
            and not self._modo_paro
            and (self._maquina_en_marcha() or self._primera_pieza)
        )
        # ESCANEAR TRABAJO visible en espera de trabajo sin trabajo cargado
        # (con la maquina apagada o ya encendida en setup). Oculto durante
        # Mantenimiento y el modo PARO.
        self.btn_escanear.setVisible(
            self.sesion_id is not None
            and self._trabajo is None
            and not self._modo_mantenimiento
            and not self._modo_paro
            and (self._maquina_en_marcha() or self._primera_pieza)
        )
        self.switch_primera_pieza.setEnabled(
            self.sesion_id is not None
            and not self._modo_mantenimiento
            and not self._modo_paro
        )
        self._actualizar_boton_paro()

    def _actualizar_boton_paro(self):
        """PARO pasa a 'SALIR DE MANTENIMIENTO'/'SALIR DE PARO' en rojo
        durante esos modos."""
        en_paro_especial = self._modo_mantenimiento or self._modo_paro
        if en_paro_especial == self._boton_paro_especial:
            return
        self._boton_paro_especial = en_paro_especial
        if self._modo_mantenimiento:
            self.btn_paro.setText("SALIR DE MANTENIMIENTO")
            aplicar_estilo_boton(self.btn_paro, "Danger")
        elif self._modo_paro:
            self.btn_paro.setText("SALIR DE PARO")
            aplicar_estilo_boton(self.btn_paro, "Danger")
        else:
            self.btn_paro.setText("PARO")
            aplicar_estilo_boton(self.btn_paro, "")

    def _icono_estado(self, estilo, sp):
        self.icono_estado.setPixmap(estilo.standardIcon(sp).pixmap(22, 22))

    # ------------------------------------------------------------------
    # Helpers UI
    # ------------------------------------------------------------------

    def _refrescar_operador(self):
        """Publica la identidad en el header (nombre + icono segun rol).

        Emite `sesion_cambiada(nombre, rol)`: nombre vacio = sin sesion. La
        App pinta el nombre junto al boton y elige persona (rol operador o
        sin rol) o engranaje (cualquier otro rol).
        """
        nombre = self.operador_nombre or ""
        rol = ""
        if self.operador_id is not None:
            try:
                rol = obtener_rol_operador(self.operador_id) or ""
            except Exception:  # noqa: BLE001 - el header no debe fallar
                log.warning("No se pudo consultar el rol del operador %s",
                            self.operador_id, exc_info=True)
                rol = ""
        self.sesion_cambiada.emit(nombre, rol)

    def _estado(self, texto="", estado="info"):
        self.lbl_estado.setText(texto)
        aplicar_estado(self.lbl_estado, estado)

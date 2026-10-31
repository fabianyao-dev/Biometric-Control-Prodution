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
from .componentes.selector_causas import SelectorCausaZona
from .componentes.modalidades_cierre import (
    MODALIDAD_FOLIO,
    ModalidadCierreDialog,
)
from src.gui.componentes.resplandor import Resplandor
from src.gui.componentes.switch import Switch
from src.gui.style import aplicar_estado, aplicar_estilo_boton
from .inicio.sesion_mixin import SesionMixin
from .inicio.maquina_mixin import MaquinaMixin
from .inicio.paro_mixin import ParoMixin
from .inicio.mantenimiento_mixin import MantenimientoMixin
from .inicio.primera_pieza_mixin import PrimeraPiezaMixin
from .inicio.trabajo_mixin import TrabajoMixin
from .inicio.seguridad_mixin import SeguridadMixin

log = logging.getLogger(__name__)
class InicioView(
    QWidget,
    SesionMixin,
    MaquinaMixin,
    ParoMixin,
    MantenimientoMixin,
    PrimeraPiezaMixin,
    TrabajoMixin,
    SeguridadMixin,
):
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
        # Torre de luces: momento en que empezo el paro actual (para pasar de
        # ambar a rojo al vencer PARO_IDLE_TIMEOUT_S) y ultimo color aplicado
        # (para disparar la alarma solo al ENTRAR en rojo).
        self._paro_inicio_momento = None
        self._ultimo_color_rojo = None
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

    def puede_cambiar_modulo(self):
        """Indica si se puede cambiar de modulo sin perder trabajo."""
        if getattr(self, "_modal_abierto", False):
            return False, "Hay un modal abierto."
        if getattr(self, "_trabajo", None) is not None:
            return False, "Hay un trabajo cargado."
        try:
            if not self.controlador.maquina_detenida():
                return False, "La maquina esta en marcha."
        except Exception:  # noqa: BLE001
            pass
        return True, ""

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
        self._actualizar_tolerancia_paro()
        self._refrescar_estado_maquina()
        self._verificar_inactividad()
        self._verificar_timeout_primera_pieza()
        QTimer.singleShot(config.REFRESCO_CONTADOR_MS, self._refrescar_contador)

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

    def _tiene_permiso_iniciar_primera_pieza(self) -> bool:
        """Permiso `iniciar_primera_pieza` del operador de la sesion (punto 4)."""
        if self.operador_id is None:
            return False
        return rol_tiene_permiso_operador(
            self.operador_id, "iniciar_primera_pieza"
        )


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

MODULO_INFO = {
    "clave": "corte",
    "nombre": "Corte",
    "icono": "mdi6.scissors",
    "orden": 0,
    "permiso": None,
    "predeterminado": True,
}


def crear_vista(contexto):
    return InicioView(
        contexto.content, contexto.content, contexto.biometrico, contexto.controlador
    )


def admin_tabs(contexto):
    return []

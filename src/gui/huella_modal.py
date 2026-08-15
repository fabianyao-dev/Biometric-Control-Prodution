"""
huella_modal.py - Ventana modal reutilizable de autenticacion por huella.

Al abrirse, EMPIEZA a pedir la huella de inmediato (sin botones extras).
Se usa para:
    - Arranque de maquina (validar operador antes de encender).
    - Autorizacion de paro (elegir causa + confirmar con el dedo).

Con `pedir_causa=True` muestra el SelectorCausas: cuadricula con las causas
mas usadas y un boton para buscar. Al autenticar con exito invoca
`on_autenticado(operador_id, nombre, causa_id)`.

Con `validador=(operador_id, nombre, causa_id) -> (bool, mensaje)` se puede
restringir quien puede autenticarse: si el validador devuelve (False, msg),
el modal NO se cierra, muestra `msg` como error y vuelve a pedir la huella
(se usa para que solo el operador de la sesion o un rol autorizado pueda
autorizar la reanudacion de un paro).

El tamano de la ventana se calcula en funcion del contenido (vease
`centrar_y_ajustar`), asi el modal crece o encoge segun la causa. Se abre en
bloqueo con `exec()`; los hilos secundarios solo escriben a `queue.Queue()`
que se drena con un QTimer en el hilo principal.
"""

import logging
import queue
import threading
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QDialog, QLabel, QPushButton, QVBoxLayout, QWidget

from src.gui.selector_causas import SelectorCausas
from src.gui.style import (
    COLOR_BORDE,
    COLOR_EXITO,
    COLOR_SUPERFICIE_ELEVADA,
    COLOR_TEXTO,
    aplicar_estado,
)
from src.gui.util import centrar_y_ajustar

log = logging.getLogger(__name__)

# Icono "fingerprint" de Material Symbols (path oficial, repositorio de
# google/material-design-icons). El trazo engrosa las crestas para que se
# lean bien a tamano de insignia. Rellenado/contorneado con {color}.
SVG_HUELLA = """\
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 -960 960 960" \
width="24" height="24"><path fill="{color}" stroke="{color}" \
stroke-width="28" stroke-linejoin="round" d="M481-781q106 0 200 45.5T838-604\
q7 9 4.5 16t-8.5 12q-6 5-14 4.5t-14-8.5q-55-78-141.5-119.5T481-741q-97 0-182 \
41.5T158-580q-6 9-14 10t-14-4q-7-5-8.5-12.5T126-602q62-85 155.5-132T481-781\
Zm0 94q135 0 232 90t97 223q0 50-35.5 83.5T688-257q-51 0-87.5-33.5T564-374q0-33 \
-24.5-55.5T481-452q-34 0-58.5 22.5T398-374q0 97 57.5 162T604-121q9 3 12 10t1 \
15q-2 7-8 12t-15 3q-104-26-170-103.5T358-374q0-50 36-84t87-34q51 0 87 34t36 84\
q0 33 25 55.5t59 22.5q34 0 58-22.5t24-55.5q0-116-85-195t-203-79q-118 0-203 79\
t-85 194q0 24 4.5 60t21.5 84q3 9-.5 16T208-205q-8 3-15.5-.5T182-217q-15-39 \
-21.5-77.5T154-374q0-133 96.5-223T481-687Zm0-192q64 0 125 15.5T724-819q9 5 \
10.5 12t-1.5 14q-3 7-10 11t-17-1q-53-27-109.5-41.5T481-839q-58 0-114 13.5T260-\
783q-8 5-16 2.5T232-791q-4-8-2-14.5t10-11.5q56-30 117-46t124-16Zm0 289q93 0 \
160 62.5T708-374q0 9-5.5 14.5T688-354q-8 0-14-5.5t-6-14.5q0-75-55.5-125.5T481-\
550q-76 0-130.5 50.5T296-374q0 81 28 137.5T406-123q6 6 6 14t-6 14q-6 6-14 6t-\
14-6q-59-62-90.5-126.5T256-374q0-91 66-153.5T481-590Zm-1 196q9 0 14.5 6t5.5 14\
q0 75 54 123t126 48q6 0 17-1t23-3q9-2 15.5 2.5T744-191q2 8-3 14t-13 8q-18 5 \
-31.5 5.5t-16.5.5q-89 0-154.5-60T460-374q0-8 5.5-14t14.5-6Z"/></svg>
"""


class HuellaWidget(QWidget):
    """Insignia circular con el icono de huella (Material Symbols, SVG).

    Fondo circular en superficie elevada + icono centrado, recolorizado
    segun el estado (verde esperando, blanco al autenticar).
    """

    def __init__(self, parent=None, ancho=96, alto=96):
        super().__init__(parent)
        self.setFixedSize(ancho, alto)
        self._autenticado = False
        self._renderer = QSvgRenderer()

    def set_autenticado(self, valor):
        self._autenticado = valor
        self.update()

    def _svg_con_color(self):
        tono = COLOR_TEXTO if self._autenticado else COLOR_EXITO
        return SVG_HUELLA.replace("{color}", tono)

    def paintEvent(self, _evento):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        # Fondo circular (insignia).
        p.setPen(QPen(QColor(COLOR_BORDE), 2))
        if self._autenticado:
            fondo = QColor(COLOR_EXITO)
            fondo.setAlpha(30)
        else:
            fondo = QColor(COLOR_SUPERFICIE_ELEVADA)
        p.setBrush(fondo)
        p.drawEllipse(0, 0, self.width() - 1, self.height() - 1)

        # Icono centrado con margen.
        margen = 14
        rect = self.rect().adjusted(margen, margen, -margen, -margen)
        if self._renderer.load(self._svg_con_color().encode("utf-8")):
            self._renderer.render(p, rect)
            return

        # Respaldo por si QtSvg no pudiera cargar el icono.
        p.setPen(QPen(QColor(COLOR_EXITO), 3, Qt.SolidLine, Qt.RoundCap))
        p.drawEllipse(rect)


class HuellaModal(QDialog):
    def __init__(self, parent, biometrico, titulo, mensaje,
                 on_autenticado=None, on_cancelar=None,
                 mostrar_cancelar=True, cerrable=True, pedir_causa=False,
                 validador=None):
        super().__init__(parent)
        self.biometrico = biometrico
        self.titulo = titulo
        self.mensaje = mensaje
        self.on_autenticado = on_autenticado
        self.on_cancelar = on_cancelar
        self.mostrar_cancelar = mostrar_cancelar
        self.cerrable = cerrable
        self.validador = validador

        self._autenticado = False
        self._abierto = True
        self.cola = queue.Queue()
        self.selector_causas = None

        self.setWindowTitle(titulo)
        self.setModal(True)
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)

        self._crear_interfaz(pedir_causa)
        centrar_y_ajustar(self, parent)

        self._timer_cola = QTimer(self)
        self._timer_cola.setInterval(60)
        self._timer_cola.timeout.connect(self._revisar_cola)
        self._timer_cola.start()
        self._empezar()

    # ------------------------------------------------------------------
    # Cierre (X / ESC)
    # ------------------------------------------------------------------

    def closeEvent(self, evento):
        # La ventana de paro NO puede cerrarse (X/ESC) hasta autenticar.
        if not self._autenticado:
            self._estado("No se puede cerrar. Identifica tu huella.", "error")
            evento.ignore()
            return
        super().closeEvent(evento)

    def reject(self):
        if not self.cerrable and not self._autenticado:
            self._estado("No se puede cerrar. Identifica tu huella.", "error")
            return
        super().reject()

    def done(self, result):
        self._abierto = False
        try:
            self._timer_cola.stop()
        except Exception:  # noqa: BLE001
            pass
        super().done(result)

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _crear_interfaz(self, pedir_causa):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 18, 24, 18)
        layout.setSpacing(12)

        lbl_titulo = QLabel(self.titulo, self)
        lbl_titulo.setObjectName("Title")
        lbl_titulo.setAlignment(Qt.AlignCenter)
        layout.addWidget(lbl_titulo)

        self.huella = HuellaWidget(self)
        layout.addWidget(self.huella, alignment=Qt.AlignHCenter)

        lbl_mensaje = QLabel(self.mensaje, self)
        lbl_mensaje.setObjectName("EstadoInfo")
        lbl_mensaje.setAlignment(Qt.AlignCenter)
        lbl_mensaje.setWordWrap(True)
        layout.addWidget(lbl_mensaje)

        if pedir_causa:
            self.selector_causas = SelectorCausas(self)
            layout.addWidget(self.selector_causas)

        self.lbl_estado = QLabel("Coloca tu huella...", self)
        self.lbl_estado.setObjectName("EstadoInfo")
        self.lbl_estado.setAlignment(Qt.AlignCenter)
        self.lbl_estado.setWordWrap(True)
        layout.addWidget(self.lbl_estado)

        if self.mostrar_cancelar:
            btn_cancelar = QPushButton("Cancelar", self)
            btn_cancelar.clicked.connect(self._cancelar)
            layout.addWidget(btn_cancelar)

    # ------------------------------------------------------------------
    # Captura automatica
    # ------------------------------------------------------------------

    def _empezar(self):
        threading.Thread(target=self._escanea, daemon=True).start()

    def _escanea(self):
        if not getattr(self.biometrico, "disponible", True):
            self.cola.put(
                ("ERROR", "Biometria no disponible en este equipo (driver de DigitalPersona no instalado).")
            )
            return
        try:
            resultado = self.biometrico.autenticar_operador(
                on_progress=self._progreso
            )
            self.cola.put(("RESULTADO", resultado))
        except Exception as e:  # noqa: BLE001
            log.error("Autenticacion fallo: %s", e, exc_info=True)
            self.cola.put(("ERROR", str(e)))

    def _progreso(self, mensaje):
        self.cola.put(("PROGRESO", mensaje))

    # ------------------------------------------------------------------
    # Cola (hilo principal)
    # ------------------------------------------------------------------

    def _revisar_cola(self):
        if not self._abierto:
            return
        try:
            while True:
                ev, data = self.cola.get_nowait()
                try:
                    if ev == "PROGRESO":
                        self._estado(data or "Coloca tu huella...", "procesando")
                    elif ev == "RESULTADO":
                        self._procesar_resultado(data)
                    elif ev == "ERROR":
                        self._estado(f"Intenta de nuevo: {data}", "error")
                        if "no disponible" not in str(data):
                            QTimer.singleShot(2500, self._reintentar)
                except Exception as e:  # noqa: BLE001
                    # Un fallo puntual no debe apagar el bucle de mensajes.
                    log.error("Error procesando evento %s: %s", ev, e, exc_info=True)
        except queue.Empty:
            pass

    def _procesar_resultado(self, resultado):
        if resultado:
            op_id, nombre = resultado
            causa_id = None
            if self.selector_causas is not None:
                causa_id = self.selector_causas.seleccion_id
            if self.validador is not None:
                valido, mensaje = self.validador(op_id, nombre, causa_id)
                if not valido:
                    log.warning(
                        "Huella %s (%s) SIN autorizacion: %s", op_id, nombre, mensaje
                    )
                    self._estado(mensaje or "Sin autorizacion para reanudar.", "error")
                    QTimer.singleShot(2500, self._reintentar)
                    return
            self._autenticado = True
            self.huella.set_autenticado(True)
            self._estado(f"\u2713 {nombre} autenticado.", "exito")
            if self.on_autenticado:
                self.on_autenticado(op_id, nombre, causa_id)
            QTimer.singleShot(300, self.accept)
        else:
            log.warning("Huella no reconocida; reintentando.")
            self._estado("Huella NO reconocida. Intenta de nuevo.", "error")
            QTimer.singleShot(2500, self._reintentar)

    def _reintentar(self):
        if not self._autenticado and self._abierto:
            threading.Thread(target=self._escanea, daemon=True).start()

    def _cancelar(self):
        if self.on_cancelar and not self._autenticado:
            self.on_cancelar()
        self.reject()

    def _estado(self, texto, estado):
        self.lbl_estado.setText(texto)
        aplicar_estado(self.lbl_estado, estado)
        self._reajustar()

    def _reajustar(self):
        """Si el mensaje de estado crecio, reajusta el modal para que nada se
        solape con la huella (la ventana queda fija con resize())."""
        hint = self.sizeHint()
        if hint.width() > self.width() + 2 or hint.height() > self.height() + 2:
            centrar_y_ajustar(self, self.parent())

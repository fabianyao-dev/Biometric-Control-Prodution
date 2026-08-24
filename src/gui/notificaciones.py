"""
notificaciones.py - Indicador de advertencias del sistema (header del kiosco).

Boton permanente en el header que avisa del estado operativo del kiosco:
    - Biometria no disponible (driver/SDK de DigitalPersona ausente).
    - Lector biometrico no detectado (driver OK pero sin lector USB conectado).
    - Controlador HAL en modo simulacion (Modbus sin MODBUS_HOST / simulacion).
    - Enlace Modbus caido (configurado pero sin respuesta).
    - Sin operadores reales registrados (acceso automatico "Operador Temporal").

Al pulsarlo despliega un panel flotante (Qt.Popup) superpuesto al contenido
(no empuja el layout como el sidebar), solo informativo. Se cierra al hacer
clic fuera o con ESC (comportamiento nativo de Qt.Popup).
"""

import logging

from PySide6.QtCore import QPoint, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.gui import style
from src.gui.style import aplicar_estilo_boton
from src.gui.util import icono_svg

log = logging.getLogger(__name__)

# Icono "warning" de Material Symbols (path oficial, google/material-design-icons).
# Triangulo con signo de admiracion, rellenado con {color}.
SVG_ADVERTENCIA = """\
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="22" height="22">\
<path fill="{color}" d="M1 21h22L12 2 1 21zm12-3h-2v-2h2v2zm0-4h-2v-4h2v4z"/></svg>
"""

# Icono "check" de Material Symbols (path oficial) para el estado sin avisos.
SVG_OK = """\
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="22" height="22">\
<path fill="{color}" d="M9 16.17 4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41L9 16.17z"/></svg>
"""

# Aviso "todo en orden" cuando el panel se abre sin advertencias.
AVISO_VACIO = "Todos los sistemas en orden."


class _IconoAdvertencia(QWidget):
    """Triangulo de advertencia (Material Symbols) en un color dado."""

    def __init__(self, color, parent=None, ancho=22, alto=22):
        super().__init__(parent)
        self.setFixedSize(ancho, alto)
        self._color = color
        self._renderer = QSvgRenderer()

    def paintEvent(self, _evento):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        svg = SVG_ADVERTENCIA.replace("{color}", self._color)
        if self._renderer.load(svg.encode("utf-8")):
            self._renderer.render(p, self.rect())
            return
        # Respaldo por si QtSvg no pudiera cargar el icono.
        p.setPen(QPen(QColor(self._color), 2, Qt.SolidLine, Qt.RoundCap))
        cx = self.width() // 2
        p.drawLine(cx, 4, cx, self.height() - 7)
        p.drawPoint(cx, self.height() - 3)


class PanelAdvertencias(QFrame):
    """Panel flotante (Qt.Popup) con la lista de advertencias. Solo informativo."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("PanelAvisos")
        self.setWindowFlag(Qt.Popup)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(16, 14, 16, 14)
        self._layout.setSpacing(10)

    def fijar_avisos(self, avisos):
        """Rellena el panel. `avisos` es una lista de (titulo, detalle)."""
        while self._layout.count():
            item = self._layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        if not avisos:
            lbl = QLabel(AVISO_VACIO, self)
            lbl.setObjectName("EstadoInfo")
            lbl.setWordWrap(True)
            self._layout.addWidget(lbl)
            return
        for titulo, detalle in avisos:
            self._layout.addWidget(self._fila(titulo, detalle))

    def _fila(self, titulo, detalle):
        fila = QWidget(self)
        lay = QHBoxLayout(fila)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)
        lay.addWidget(_IconoAdvertencia(style.color("advertencia"), fila),
                      alignment=Qt.AlignTop)

        caja = QVBoxLayout()
        caja.setContentsMargins(0, 0, 0, 0)
        caja.setSpacing(2)
        lbl_titulo = QLabel(titulo, fila)
        lbl_titulo.setObjectName("HeaderLabel")
        lbl_titulo.setWordWrap(True)
        caja.addWidget(lbl_titulo)
        if detalle:
            lbl_detalle = QLabel(detalle, fila)
            lbl_detalle.setObjectName("EstadoInfo")
            lbl_detalle.setWordWrap(True)
            caja.addWidget(lbl_detalle)
        lay.addLayout(caja, stretch=1)
        return fila


class IndicadorAdvertencias(QPushButton):
    """Boton del header: icono de check cuando todo OK, icono de advertencia
    ambar + contador cuando hay avisos.

    Al pulsarlo alterna un PanelAdvertencias anclado bajo el boton.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._avisos = []
        self._panel = None
        self.setFixedWidth(58)
        self.setIconSize(QSize(20, 20))
        self.clicked.connect(self._alternar_panel)
        self.set_advertencias([])

    def set_advertencias(self, avisos):
        self._avisos = list(avisos)
        if self._avisos:
            # Colores del tema ACTIVO (consultados aqui para que el cambio
            # de tema regenere los iconos en el siguiente refresco).
            self.setIcon(icono_svg(SVG_ADVERTENCIA,
                                    style.color("sobre_advertencia")))
            self.setText(f" {len(self._avisos)}")
            aplicar_estilo_boton(self, "AvisoActivo")
        else:
            self.setIcon(icono_svg(SVG_OK, style.color("texto_sec")))
            self.setText("")
            aplicar_estilo_boton(self, "Aviso")
        if self._panel is not None and self._panel.isVisible():
            self._panel.fijar_avisos(self._avisos)

    def _alternar_panel(self):
        if self._panel is not None and self._panel.isVisible():
            self._panel.hide()
            return
        if self._panel is None:
            self._panel = PanelAdvertencias(self.window())
        self._panel.fijar_avisos(self._avisos)
        self._panel.adjustSize()
        self._posicionar_panel()
        self._panel.show()

    def _posicionar_panel(self):
        """Ancla el panel bajo el boton, alineado a su borde derecho y
        mantenido dentro de la pantalla (kiosco a pantalla completa)."""
        ancho = self._panel.width()
        alto = self._panel.height()
        punto = self.mapToGlobal(self.rect().bottomRight())
        x = punto.x() - ancho
        y = punto.y() + 4
        pantalla = self.screen().availableGeometry()
        x = max(pantalla.left(), min(x, pantalla.right() - ancho))
        y = min(y, pantalla.bottom() - alto - 8)
        self._panel.move(QPoint(x, y))
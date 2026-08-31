"""
resplandor.py - Halos pulsantes (glow) detras de widgets.

Envuelve un widget hijo (boton de poder, switch de primera pieza) y dibuja
detras un halo radial difuminado con pulso tipo latido: ataque rapido, caida
lenta y un breve reposo, en bucle. El color se toma de style.color() DENTRO
de paintEvent para que el cambio de tema EN CALIENTE le afecte sin guardar el
valor al construir; set_resplandor() es idempotente (no reinicia el pulso si
el color no cambia).
"""

from PySide6.QtCore import QTimer
from PySide6.QtGui import QColor, QPainter, QRadialGradient
from PySide6.QtWidgets import QHBoxLayout, QWidget

from src.gui import style

# Fases del pulso como fracciones del ciclo (suman <= 1; el resto es reposo).
_ATAQUE_HASTA = 0.16  # subida rapida 0 -> 1
_CAIDA_HASTA = 0.68   # caida lenta 1 -> 0

# El halo nunca se apaga del todo y alcanza su maximo en el latido.
_ALFA_BASE = 120
_ALFA_PICO = 210


class Resplandor(QWidget):
    """Contenedor que pinta un halo pulsante detras de su primer widget hijo.

    Attributes:
        radio_extra: margen interior (px) reservado alrededor del hijo para
            que el halo tenga espacio que difuminar.
    """

    def __init__(self, radio_extra=20, parent=None):
        super().__init__(parent)
        self._radio_extra = max(4, radio_extra)
        self._clave = None  # clave de color activo; None = sin halo
        self._fase = 0.0    # posicion en el ciclo [0, 1)
        self._timer = QTimer(self)
        self._timer.setInterval(30)
        self._timer.timeout.connect(self._latido)
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(self._radio_extra, self._radio_extra,
                                        self._radio_extra, self._radio_extra)
        self._layout.addStretch(1)

    def set_resplandor(self, clave):
        """Activa (o desactiva con None) el halo con el color de `clave`.

        Idempotente: si ya brilla del mismo color mantiene la fase del pulso
        en curso en vez de reiniciarlo.
        """
        if clave == self._clave:
            return
        self._clave = clave
        if clave is not None:
            self._fase = 0.0
            if not self._timer.isActive():
                self._timer.start()
        else:
            self._timer.stop()
            self.update()

    def detener_resplandor(self):
        self.set_resplandor(None)

    def add_widget(self, widget):
        self._layout.addWidget(widget)
        self._layout.addStretch(1)

    def _latido(self):
        self._fase = (self._fase + 0.028) % 1.0
        self.update()

    def _intensidad(self):
        f = self._fase
        if f < _ATAQUE_HASTA:
            p = f / _ATAQUE_HASTA
            return 1.0 - (1.0 - p) * (1.0 - p)
        if f < _CAIDA_HASTA:
            p = (f - _ATAQUE_HASTA) / max(1e-6, _CAIDA_HASTA - _ATAQUE_HASTA)
            return (1.0 - p) * (1.0 - p)
        return 0.0

    def paintEvent(self, event):
        super().paintEvent(event)
        if self._clave is None:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = QColor(style.color(self._clave))
        cx = max(1, self.width() // 2)
        cy = max(1, self.height() // 2)
        radio = max(cx, cy)
        grad = QRadialGradient(cx, cy, radio)
        intensidad = self._intensidad()
        alfa = round(_ALFA_BASE + _ALFA_PICO * intensidad)
        for stop, fraccion in ((0.0, 1.0), (0.45, 0.72), (0.8, 0.32)):
            c = QColor(color)
            c.setAlpha(round(alfa * fraccion))
            grad.setColorAt(stop, c)
        borde = QColor(color)
        borde.setAlpha(0)
        grad.setColorAt(1.0, borde)
        p.fillRect(self.rect(), grad)
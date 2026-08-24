"""
switch.py - Interruptor (switch) estilo iOS para la GUI en PySide6.

Pinta una pista redondeada y una perilla (knob) que se desliza al alternar.
Es un QAbstractButton checkable: el clic en cualquier punto lo alterna y
emite `toggled(bool)` (igual que un QCheckBox). La perilla se mueve con una
animacion corta; `fijar()` permite cambiarlo por codigo sin disparar
handlers extra (quien lo usa maneja el guard propio).
"""

from PySide6.QtCore import Property, QPropertyAnimation, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QAbstractButton

from src.gui import style


class Switch(QAbstractButton):
    """Switch on/off con perilla deslizante. Emite `toggled(bool)`."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(56, 28)
        self._progreso = 0.0
        self._anim = QPropertyAnimation(self, b"progreso", self)
        self._anim.setDuration(120)

    def nextCheckState(self):
        """Clic: alterna y anima la perilla. `setChecked` emite `toggled`."""
        self.fijar(not self.isChecked())

    def fijar(self, activo, animar=True):
        """Pone el switch en `activo` (emite `toggled` si cambia de estado)."""
        if self.isChecked() != activo:
            self.setChecked(activo)
        destino = 1.0 if activo else 0.0
        if animar and abs(self._progreso - destino) > 0.001:
            self._anim.stop()
            self._anim.setStartValue(self._progreso)
            self._anim.setEndValue(destino)
            self._anim.start()
        else:
            self.set_progreso(destino)

    # Posicion de la perilla como 0..1 (animable por QPropertyAnimation).
    def get_progreso(self):
        return self._progreso

    def set_progreso(self, valor):
        self._progreso = valor
        self.update()

    progreso = Property(float, get_progreso, set_progreso)

    def paintEvent(self, _evento):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        w, h = self.width(), self.height()

        # Pista (track) redondeada. Colores del tema ACTIVO (consultados
        # aqui para que el cambio de tema repinte sin reiniciar).
        p.setPen(QPen(QColor(style.color("borde")), 1))
        if self.isChecked():
            p.setBrush(QColor(style.color("accento")))
        else:
            p.setBrush(QColor(style.color("deshabilitado_bg")))
        p.drawRoundedRect(QRectF(1, 1, w - 2, h - 2), h / 2.0, h / 2.0)

        # Perilla (knob) blanca que se desliza.
        margen = 2
        diam = h - 2 * margen
        x = margen + self._progreso * (w - diam - 2 * margen)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(style.color("texto")))
        p.drawEllipse(QRectF(x, margen, diam, diam))

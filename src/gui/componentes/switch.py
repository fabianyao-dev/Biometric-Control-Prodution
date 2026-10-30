"""
switch.py - Interruptor (switch) estilo iOS para la GUI en PySide6.

Pinta una pista redondeada y una perilla (knob) que se desliza al alternar.
Es un QAbstractButton checkable: el clic en cualquier punto lo alterna y
emite `toggled(bool)` (igual que un QCheckBox). La perilla se mueve con una
animacion corta; `fijar()` permite cambiarlo por codigo sin disparar
handlers extra (quien lo usa maneja el guard propio).
"""

from PySide6.QtCore import (
    Property,
    QAbstractAnimation,
    QPropertyAnimation,
    QRectF,
    Qt,
)
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
            # Si hay una animacion en curso (p. ej. la del toggled del
            # usuario) hay que detenerla, o seguira sobrescribiendo
            # `_progreso` hacia el valor viejo aunque el estado ya sea el
            # nuevo (la perilla volveria al lado equivocado).
            self._anim.stop()
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
        deshabilitado = not self.isEnabled()
        checked = self.isChecked()

        # Colores del tema consultados AQUI (convencion del proyecto) para
        # que el repintado por tema no requiera reconstruir el widget.
        if deshabilitado:
            color_track = QColor(style.color("deshabilitado_bg"))
            color_knob = QColor(style.color("deshabilitado_texto"))
        elif checked:
            if self.isDown():
                color_track = QColor(style.color("accento_pressed"))
            elif self.underMouse():
                color_track = QColor(style.color("accento_hover"))
            else:
                color_track = QColor(style.color("accento"))
            color_knob = QColor(style.color("texto"))
        else:
            if self.isDown():
                color_track = QColor(style.color("deshabilitado_bg")).darker(110)
            elif self.underMouse():
                color_track = QColor(style.color("deshabilitado_bg")).lighter(108)
            else:
                color_track = QColor(style.color("deshabilitado_bg"))
            color_knob = QColor(style.color("texto"))

        # Pista (track) redondeada.
        p.setPen(QPen(QColor(style.color("borde")), 1))
        p.setBrush(color_track)
        p.drawRoundedRect(QRectF(1, 1, w - 2, h - 2), h / 2.0, h / 2.0)

        # Perilla (knob). Se le anade un borde sutil del color del tema para
        # que destaque (contraste) tanto sobre la pista clara como sobre la
        # azul del modo encendido, en ambos temas.
        margen = 2
        diam = h - 2 * margen
        rango = w - diam - 2 * margen
        if self._anim.state() == QAbstractAnimation.Running:
            x = margen + self._progreso * rango
        else:
            # Sin animacion en curso la bolita coincide con el estado real
            # (`checked`), aunque `_progreso` haya quedado desincronizado
            # (p. ej. al cancelar la salida del modo). Asi nunca queda a la
            # izquierda estando encendida.
            x = margen + (1.0 if checked else 0.0) * rango
        p.setPen(Qt.NoPen)
        p.setBrush(color_knob)
        p.drawEllipse(QRectF(x, margen, diam, diam))
        p.setPen(QPen(QColor(style.color("borde")), 1))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QRectF(x, margen, diam, diam))

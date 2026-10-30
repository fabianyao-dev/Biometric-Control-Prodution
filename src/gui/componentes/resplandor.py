"""
resplandor.py - Halos pulsantes (glow) detras de widgets.

Capa de pintado (overlay) que dibuja un halo radial difuminado DETRAS de un
widget objetivo (el boton de poder) y con pulso tipo latido: ataque rapido,
caida lenta y un breve reposo, en bucle.

A diferencia del enfoque anterior (envolver al boton con margenes `radio_extra`
en un layout), esta capa NO participa del layout del padre: se redimensiona
para cubrir toda la vista y va detras de todo (`lower()`), asi el glow:
  - NO desplaza el boton (no reserva espacio), y
  - NO se corta al acercarse a los widgets de abajo (gira en fondo completo y
    se funde de forma natural, tapado por los widgets colocados encima).

El color se toma de style.color() DENTRO de paintEvent para que el cambio de
tema EN CALIENTE le afecte sin guardar el valor al construir;
set_resplandor() es idempotente (no reinicia el pulso si el color no cambia).
"""

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QRadialGradient
from PySide6.QtWidgets import QWidget

from src.gui import style

# Fases del pulso como fracciones del ciclo (suman <= 1; el resto es reposo).
_ATAQUE_HASTA = 0.16  # subida rapida 0 -> 1
_CAIDA_HASTA = 0.68   # caida lenta 1 -> 0

# El halo nunca se apaga del todo y alcanza su maximo en el latido.
# Se satura a 255 en el pico para que el gradiente nunca exceda el rango
# valido de QColor.setAlpha (0..255).
_ALFA_BASE = 120
_ALFA_PICO = 130

# Cuanto GRANDE se dibuja el halo por fuera de la mitad del widget objetivo.
_RADIO_MARGEN = 12


class Resplandor(QWidget):
    """Capa de fondo que pinta un halo pulsante centrado en `_widget`.

    No tiene layout propio ni ocupa espacio en el del padre: se usa como un
    overlay que cubre toda la vista y va detras de los demas widgets.
    """

    def __init__(self, radio_extra=20, parent=None):
        # `radio_extra` se conserva por compatibilidad: era el margen del
        # wrapper y ahora actua como radio minimo del halo.
        super().__init__(parent)
        self._radio_extra = max(4, radio_extra)
        self._clave = None  # clave de color activo; None = sin halo
        self._fase = 0.0    # posicion en el ciclo [0, 1)
        self._widget = None # widget objetivo (el halo se centra en el)
        self._timer = QTimer(self)
        self._timer.setInterval(30)
        self._timer.timeout.connect(self._latido)
        # Capa de pintado transparente: no intercepta clics ni eventos del
        # raton, no pinta fondo propio.
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)

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
        """Define el widget objetivo: el halo se centra en su centro."""
        self._widget = widget

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

    def _centro(self):
        """Centro del widget objetivo en coordenadas de esta capa."""
        if self._widget is not None and self._widget.isVisible():
            punto = self._widget.rect().center()
            global_ = self._widget.mapToGlobal(punto)
            local = self.mapFromGlobal(global_)
            return local.x(), local.y()
        # Sin objetivo: centrar en esta capa como fallback.
        return self.width() // 2, self.height() // 2

    def paintEvent(self, event):
        super().paintEvent(event)
        if self._clave is None:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = QColor(style.color(self._clave))
        cx, cy = self._centro()
        cx = max(1, int(cx))
        cy = max(1, int(cy))
        # Radio: al menos el minimo configurado y lo bastante grande para que
        # el halo SOBRESALGA del widget objetivo por todos los lados. La capa
        # cubre toda la vista, asi el glow se funde sin cortarse a los lados.
        mitad_mayor = 1
        if self._widget is not None:
            mitad_mayor = max(self._widget.width(), self._widget.height()) / 2
        radio = max(self._radio_extra, int(mitad_mayor + _RADIO_MARGEN))
        radio = max(1, radio)
        grad = QRadialGradient(cx, cy, radio)
        intensidad = self._intensidad()
        alfa = min(255, _ALFA_BASE + _ALFA_PICO * intensidad)
        for stop, fraccion in ((0.0, 1.0), (0.45, 0.72), (0.8, 0.32)):
            c = QColor(color)
            c.setAlpha(round(alfa * fraccion))
            grad.setColorAt(stop, c)
        borde = QColor(color)
        borde.setAlpha(0)
        grad.setColorAt(1.0, borde)
        p.fillRect(self.rect(), grad)
        p.end()

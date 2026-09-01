"""
marcador.py - Display de 7 segmentos estilo LED (tablero de planta).

Widget pintado a mano que simula el contador LED de 7 segmentos de los
marcadores fisicos de produccion: pantalla negra con digitos rojos, brillo
en los segmentos encendidos y "fantasmas" apenas visibles en los apagados.
Los colores salen del tema ACTIVO via style.color() consultados DENTRO de
paintEvent (compatible claro/oscuro); nada se cachea al construir.
"""

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPen, QTransform
from PySide6.QtWidgets import QWidget

from src.gui import style

# Segmentos encendidos por caracter (a=superior, b=superior-derecho,
# c=inferior-derecho, d=inferior, e=inferior-izquierdo, f=superior-izquierdo,
# g=central).
SEGMENTOS = {
    "0": "abcdef",
    "1": "bc",
    "2": "abdeg",
    "3": "abcdg",
    "4": "bcfg",
    "5": "acdfg",
    "6": "acdefg",
    "7": "abc",
    "8": "abcdefg",
    "9": "abcdfg",
    "-": "g",
    " ": "",
}


class DisplaySieteSegmentos(QWidget):
    """Contador LED de N digitos. `set_valor(str)` acepta 0-9, '-' y ' '."""

    def __init__(self, parent=None, alto=64, digitos=4):
        super().__init__(parent)
        self._texto = "0000"
        self._alto_digito = float(alto)
        # Numero de digitos para el que se reserva espacio FIJO: el display
        # no cambia de tamano al variar el contenido (evita que el tablero
        # se desajuste cuando un contador pasa de 9999 a 5+ digitos).
        self._digitos = max(1, int(digitos))
        self._texto = " " * self._digitos
        self.set_valor("0" * self._digitos)

    # ------------------------------------------------------------------
    # API publica
    # ------------------------------------------------------------------

    def set_valor(self, texto):
        """Fija el contenido del display (solo caracteres de SEGMENTOS).
        Rellena a la izquierda con espacios para ocupar siempre _digitos posiciones.
        """
        limpio = "".join(c if c in SEGMENTOS else " " for c in str(texto))
        # Rellenar a la izquierda para que siempre ocupe _digitos posiciones
        if len(limpio) < self._digitos:
            limpio = limpio.rjust(self._digitos)
        elif len(limpio) > self._digitos:
            limpio = limpio[:self._digitos]
        if limpio != self._texto:
            self._texto = limpio
            self.updateGeometry()
            self.update()

    # ------------------------------------------------------------------
    # Geometria
    # ------------------------------------------------------------------

    def _medidas(self):
        """(ancho_digito, grosor_segmento, separacion) a partir del alto."""
        h = self._alto_digito
        w = h * 0.56
        t = max(4.0, h * 0.11)  # grosor del segmento
        sep = w * 0.42          # aire entre digitos
        return w, t, sep

    def _tamano_contenido(self):
        w, _t, sep = self._medidas()
        pad_x = self._alto_digito * 0.30
        inclinacion = self._alto_digito * 0.10
        n = self._digitos
        ancho = n * w + (n - 1) * sep + 2 * pad_x + inclinacion
        alto = self._alto_digito * 1.36
        return ancho, alto

    def sizeHint(self):
        ancho, alto = self._tamano_contenido()
        return QSize(int(ancho), int(alto)).expandedTo(self.minimumSizeHint())

    def minimumSizeHint(self):
        ancho, alto = self._tamano_contenido()
        return QSize(int(ancho), int(alto))

    # ------------------------------------------------------------------
    # Pintado
    # ------------------------------------------------------------------

    def paintEvent(self, _evento):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        # Pantalla negra del modulo (como el tablero fisico), igual en
        # ambos temas.
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(style.color("tablero_pantalla")))
        p.drawRoundedRect(QRectF(self.rect()), 10, 10)

        w, t, sep = self._medidas()
        h = self._alto_digito
        n = self._digitos
        total = n * w + (n - 1) * sep
        x0 = (self.width() - total) / 2.0
        y0 = (self.height() - h) / 2.0

        # Inclinacion tipica del display (cursiva): cizalla suave.
        slant = 0.08
        tr = QTransform()
        tr.translate(x0 + slant * h, y0)
        tr.shear(-slant, 0.0)
        p.setTransform(tr)

        encendido = QColor(style.color("tablero_segmento_on"))
        fantasma = QColor(style.color("tablero_segmento_off"))
        for caracter in self._texto:
            self._pintar_digito(p, w, h, t,
                                SEGMENTOS.get(caracter, ""),
                                encendido, fantasma)
            p.translate(w + sep, 0)
        p.resetTransform()

    def _pintar_digito(self, p, w, h, t, activos, encendido, fantasma):
        medio_t = t / 2.0
        xa = t * 0.55
        xb = w - t * 0.55
        ya = medio_t
        ym = h / 2.0
        yd = h - medio_t
        holgura = t * 0.45  # separacion visible entre segmentos

        lineas = {
            "a": (xa, ya, xb, ya),
            "g": (xa, ym, xb, ym),
            "d": (xa, yd, xb, yd),
            "f": (xa, ya + holgura, xa, ym - holgura),
            "b": (xb, ya + holgura, xb, ym - holgura),
            "e": (xa, ym + holgura, xa, yd - holgura),
            "c": (xb, ym + holgura, xb, yd - holgura),
        }

        for nombre, (x1, y1, x2, y2) in lineas.items():
            if nombre in ("a", "g", "d"):
                x1 += holgura
                x2 -= holgura
            esta_on = nombre in activos
            if esta_on:
                # Halo: pasada translucida mas gruesa bajo el segmento.
                halo = QColor(encendido)
                halo.setAlpha(70)
                pen_halo = QPen(halo, t * 1.9)
                pen_halo.setCapStyle(Qt.RoundCap)
                p.setPen(pen_halo)
                p.drawLine(QPointF(x1, y1), QPointF(x2, y2))
                pen_solido = QPen(encendido.lighter(115), t * 0.72)
                pen_solido.setCapStyle(Qt.RoundCap)
                p.setPen(pen_solido)
            else:
                pen = QPen(fantasma, t * 0.72)
                pen.setCapStyle(Qt.RoundCap)
                p.setPen(pen)
            p.drawLine(QPointF(x1, y1), QPointF(x2, y2))

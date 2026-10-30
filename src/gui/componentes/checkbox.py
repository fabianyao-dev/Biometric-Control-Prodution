"""
checkbox.py - CheckBox pintado a mano, acorde al tema.

Fusion + el QSS de la app eliminan el indicador nativo de QCheckBox (el
cuadrito queda INVISIBLE sobre el fondo oscuro: solo se ve el texto). Este
widget pinta el cuadro redondeado + palomita con `style.color()` dentro del
`paintEvent` (tema oscuro/claro en caliente), igual que el delegate de
permisos y el switch. API identica a QCheckBox: `isChecked()`, `setChecked()`
y la senal `toggled(bool)`.
"""

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QAbstractButton

from src.gui import style

RADIO = 5          # radio del cuadro redondeado
LADO = 20          # lado del cuadro
MARGE = 6          # margen izquierdo/derecho del widget


class CheckBox(QAbstractButton):
    def __init__(self, texto="", parent=None):
        super().__init__(parent)
        self.setText(texto)
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)

    # ------------------------------------------------------------------
    # Tamano (el texto define el ancho; el alto se adapta a la fuente)
    # ------------------------------------------------------------------

    def sizeHint(self):
        fm = self.fontMetrics()
        texto = max(self.text(), "")
        ancho = MARGE + LADO + 8 + fm.horizontalAdvance(texto) + MARGE
        return QSize(max(ancho, 40), max(26, fm.height() + 8))

    def minimumSizeHint(self):
        return self.sizeHint()

    # ------------------------------------------------------------------
    # Pintado (colores consultados dentro del paintEvent: tema en caliente)
    # ------------------------------------------------------------------

    def paintEvent(self, _evento):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        habilitado = self.isEnabled()
        marcado = self.isChecked()
        alto = self.height()
        cb = QRectF(MARGE, (alto - LADO) / 2.0, LADO, LADO)

        if habilitado:
            borde = QColor(style.color("deshabilitado_texto"))
            fondo = QColor(style.color("elevada"))
            relleno = QColor(style.color("accento"))
            palomita = QColor(style.color("blanco"))
        else:
            borde = QColor(style.color("deshabilitado_bg"))
            fondo = QColor(style.color("lista_disabled_bg"))
            relleno = QColor(style.color("deshabilitado_bg"))
            palomita = QColor(style.color("deshabilitado_texto"))

        p.setPen(QPen(relleno if marcado else borde, 2))
        p.setBrush(relleno if marcado else fondo)
        p.drawRoundedRect(cb, RADIO, RADIO)
        if marcado:
            pen = QPen(palomita, 2.2)
            pen.setCapStyle(Qt.RoundCap)
            p.setPen(pen)
            p.drawPolyline(
                QPolygonF(
                    [
                        QPointF(cb.x() + 4.5, cb.y() + LADO * 0.525),
                        QPointF(cb.x() + 9.0, cb.y() + LADO * 0.75),
                        QPointF(cb.x() + 16.0, cb.y() + LADO * 0.275),
                    ]
                )
            )

        tr = QRectF(cb.right() + 8, 0, self.width() - cb.right() - 8 - MARGE, alto)
        p.setPen(QColor(style.color(
            "deshabilitado_texto" if not habilitado else "texto"
        )))
        p.drawText(
            tr,
            int(Qt.AlignVCenter | Qt.AlignLeft),
            p.fontMetrics().elidedText(self.text(), Qt.ElideRight,
                                       int(tr.width())),
        )
        p.end()
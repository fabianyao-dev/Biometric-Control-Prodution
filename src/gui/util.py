"""
util.py - Utilidades de GUI reutilizables (PySide6/Qt).

Funciones de apoyo para ventanas emergentes: ajustar el dialogo a su
contenido (tamano dinamico), centrarlo sobre su ventana padre, un dialogo
generico para pedir texto (usado por el CRUD de roles) y conversion de SVG
monocolor a QIcon (iconos nítidos, nunca emojis).
"""

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QInputDialog


def icono_svg(plantilla, color, tamano=20):
    """Convierte un SVG monocolor ({color} = placeholder) en un QIcon."""
    renderer = QSvgRenderer(plantilla.replace("{color}", color).encode("utf-8"))
    pixmap = QPixmap(tamano, tamano)
    pixmap.fill(Qt.transparent)
    p = QPainter(pixmap)
    p.setRenderHint(QPainter.Antialiasing)
    renderer.render(p, QRect(0, 0, tamano, tamano))
    p.end()
    icono = QIcon()
    icono.addPixmap(pixmap)
    return icono


def centrar_y_ajustar(ventana, parent=None, margen=20,
                      max_ancho=None, max_alto=None):
    """Ajusta un QDialog a su contenido y lo centra sobre `parent`.

    El tamano final se limita a la pantalla menos `margen` en cada borde,
    de modo que las ventanas crezcan/encogan segun el contenido (modales
    con muchas causas vs. sin causas) sin salirse de la pantalla.
    """
    ventana.adjustSize()
    ancho = ventana.sizeHint().width()
    alto = ventana.sizeHint().height()

    pantalla = ventana.screen().availableGeometry()

    if max_ancho is None:
        max_ancho = pantalla.width() - 2 * margen
    if max_alto is None:
        max_alto = pantalla.height() - 2 * margen

    ancho = min(ancho, max_ancho)
    alto = min(alto, max_alto)

    # Nunca encoger por debajo del minimo del layout: si no, los widgets se
    # comprimen y sus geometrias se solapan (labels que cruzan al simbolo).
    minimo = ventana.minimumSizeHint()
    ancho = max(ancho, minimo.width())
    alto = max(alto, minimo.height())
    ventana.setMinimumSize(minimo)

    ventana_ancho = pantalla.width()
    ventana_alto = pantalla.height()
    if parent is not None:
        try:
            win = parent.window()
            x0, y0 = win.x(), win.y()
            pw, ph = win.width(), win.height()
            x = x0 + (pw - ancho) // 2
            y = y0 + (ph - alto) // 2
        except Exception:  # noqa: BLE001
            x = (ventana_ancho - ancho) // 2
            y = (ventana_alto - alto) // 2
    else:
        x = (pantalla.width() - ancho) // 2
        y = (pantalla.height() - alto) // 2

    x = max(margen, min(x, pantalla.width() - ancho - margen))
    y = max(margen, min(y, pantalla.height() - alto - margen))
    ventana.resize(ancho, alto)
    ventana.move(x, y)


def preguntar_texto(parent, titulo, etiqueta, valor_inicial=""):
    """Dialogo modal que pide un texto. Devuelve el texto o None al cancelar."""
    texto, aceptado = QInputDialog.getText(
        parent, titulo, etiqueta, text=valor_inicial
    )
    if not aceptado:
        return None
    return texto.strip()

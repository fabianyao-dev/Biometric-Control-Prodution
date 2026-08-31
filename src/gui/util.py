"""
util.py - Utilidades de GUI reutilizables (PySide6/Qt).

Funciones de apoyo para ventanas emergentes: ajustar el dialogo a su
contenido (tamano dinamico), centrarlo sobre su ventana padre, un dialogo
generico para pedir texto (usado por el CRUD de roles) y conversion de SVG
monocolor a QIcon (iconos nítidos, nunca emojis).
"""

from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QAbstractScrollArea,
    QHeaderView,
    QInputDialog,
    QScroller,
    QScrollerProperties,
)


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

    El tamano final se limita al area de la ventana padre (menos `margen` en
    cada borde): los modales se abren AL CENTRO de donde este la ventana y en
    modo ventana NO desbordan su ancho. Si no hay ventana visible se usa la
    pantalla.
    """
    ventana.adjustSize()
    ancho = ventana.sizeHint().width()
    alto = ventana.sizeHint().height()

    pantalla = ventana.screen().availableGeometry()

    # Area de referencia: la ventana que contiene a `parent`. En modo ventana
    # es mas pequena que la pantalla, asi el modal cabe dentro (no la
    # desborda ni se centra en la pantalla); en kiosco coincide con la
    # pantalla.
    area = pantalla
    if parent is not None:
        try:
            win = parent.window()
            if win is not None and win.isVisible():
                area = QRect(win.mapToGlobal(QPoint(0, 0)), win.size())
                area = area.intersected(pantalla)
                if area.isEmpty():
                    area = pantalla
        except Exception:  # noqa: BLE001
            area = pantalla

    if max_ancho is None:
        max_ancho = area.width() - 2 * margen
    if max_alto is None:
        max_alto = area.height() - 2 * margen

    ancho = min(ancho, max_ancho)
    alto = min(alto, max_alto)

    # Nunca encoger por debajo del minimo del layout: si no, los widgets se
    # comprimen y sus geometrias se solapan (labels que cruzan al simbolo).
    minimo = ventana.minimumSizeHint()
    # Respetar tambien un minimo EXPLICITO (p. ej. el modal de causa/zona:
    # `setMinimumSize` para darle ancho al croquis aunque su contenido pida
    # menos).
    minimo_expl = ventana.minimumSize()
    if minimo_expl.width() > 0 or minimo_expl.height() > 0:
        minimo = QSize(
            max(minimo.width(), minimo_expl.width()),
            max(minimo.height(), minimo_expl.height()),
        )
    # Recortar a `area` ANTES de aplicar cualquier restriccion: si el minimo
    # explicito es mayor que el espacio disponible, la ventana se ajusta a
    # `max_*` en vez de desbordar la ventana padre (modo ventana) ni salirse
    # de la pantalla (un `setMinimumSize` enorme anularia el resize).
    ancho = min(max(ancho, minimo.width()), max_ancho)
    alto = min(max(alto, minimo.height()), max_alto)
    ventana.setMinimumSize(ancho, alto)

    x = area.x() + (area.width() - ancho) // 2
    y = area.y() + (area.height() - alto) // 2

    # Mantener el modal dentro del area (y de la pantalla) si no cabe centrado.
    x = max(area.x() + margen,
            min(x, area.x() + area.width() - ancho - margen))
    y = max(area.y() + margen,
            min(y, area.y() + area.height() - alto - margen))
    ventana.resize(ancho, alto)
    ventana.move(x, y)


def desplazamiento_tactil(raiz):
    """Habilita el scroll con el dedo (gesto tactil) en TODO `raiz`.

    En Qt6/Windows los scrollareas NO consumen el arrastre tactil por
    defecto: sin esto, arrastrar el dedo sobre una tabla no hace scroll y el
    gesto se va a la ventana nativa (se arrastra/redimensiona e inunda el
    log de ``QWindowsWindow::setGeometry`` cuando el minimo del layout
    supera la pantalla touch, p. ej. la vertical 1080px). `QScroller` captura
    el gesto a nivel de widget: el dedo desplaza la tabla y Windows no ve
    nada.
    """
    for sa in raiz.findChildren(QAbstractScrollArea):
        if isinstance(sa, QHeaderView):
            # Nada de gesto en las cabeceras de tabla: el dedo sobre ellas
            # (o el raton) sigue reordenando/ajustando columnas.
            continue
        vp = sa.viewport()
        vp.setAttribute(Qt.WA_AcceptTouchEvents, True)
        QScroller.grabGesture(vp, QScroller.TouchGesture)
        props = QScroller.scroller(vp).scrollerProperties()
        # Sensibilidad de pantallas touch grandes (no confundir arrastre
        # corto con scroll): arrastre minimo antes de desplazar.
        props.setScrollMetric(
            QScrollerProperties.HorizontalOvershootPolicy,
            QScrollerProperties.OvershootAlwaysOff,
        )
        props.setScrollMetric(
            QScrollerProperties.VerticalOvershootPolicy,
            QScrollerProperties.OvershootAlwaysOff,
        )


def preguntar_texto(parent, titulo, etiqueta, valor_inicial=""):
    """Dialogo modal que pide un texto. Devuelve el texto o None al cancelar."""
    texto, aceptado = QInputDialog.getText(
        parent, titulo, etiqueta, text=valor_inicial
    )
    if not aceptado:
        return None
    return texto.strip()

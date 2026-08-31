"""
croquis_zonas.py - Croquis de zonas de la maquina con POSICION y TAMANO libres.

Cada zona guarda en BD su geometria como FRACCION 0..1 del lienzo (`x`,`y`,
`w`,`h`) y el tamano de su icono como `icono_frac` (fraccion del boton).
El lienzo escala esas fracciones a su tamano real manteniendo la PROPORCION
de referencia (16:9) centrada, asi el mismo croquis se ve igual en
Administracion -> Zonas (editable) y en el modal de paro (operador).

Modo edicion (Admin):
    - ARRASTRAR el cuerpo del boton lo mueve libremente.
    - ARRASTRAR la manija de la esquina inferior-derecha lo redimensiona.
    - Al soltar se persiste la geometria (on_geometria -> guardar_zona).

Modo operador (modal de paro):
    - clic selecciona la zona (on_seleccion -> resalta y actualiza la causa).
"""

import logging
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QFrame, QWidget

import qtawesome as qta

from src.database import listar_zonas_maquina
from src.gui import style

log = logging.getLogger(__name__)

MIN_FRAC = 0.10          # tamano minimo del boton (fraccion del lienzo)
TAMANIO_MANJA = 16       # px del area sensible de la manija de resize
RADIO = 10               # radio de las esquinas redondeadas
# Proporcion (alto/ancho) DE REFERENCIA del croquis. El lienzo encuadra sus
# zonas dentro de una region con ESTA proporcion, centrada en el widget. Asi
# un boton tiene la MISMA anchura/proporcion en Administracion y en el modal
# de paro, aunque el tamaño del lienzo cambie (a 16:9 en ambos contextos).
PROPORCION_REF = 9.0 / 16.0


def _pixmap_icono(nombre, px, _cache=None):
    if _cache is None:
        _cache = {}
    color = style.color("accento")
    clave = (nombre, px, color)
    if clave not in _cache:
        try:
            _cache[clave] = qta.icon(nombre, color=color).pixmap(px, px)
        except Exception:  # noqa: BLE001  (icono invalido -> placeholder)
            _cache[clave] = qta.icon(
                "mdi6.help-circle", color=color
            ).pixmap(px, px)
    return _cache[clave]


class ZonaBoton(QWidget):
    """Boton de una zona del croquis.

    En modo edicion soporta arrastre libre (mover) y redimension con la
    manija de la esquina inferior-derecha; ambas se persisten al soltar.
    En modo operador solo selecciona al hacer clic.
    """

    def __init__(self, zona, editable=False, on_seleccion=None,
                 on_geometria=None):
        super().__init__()
        self.zona = zona
        self.zona_id = zona["id"]
        self.editable = editable
        self._on_seleccion = on_seleccion
        self._on_geometria = on_geometria
        self._seleccionada = False
        self._modo = None
        self._inicio = None
        self._orig = None
        self.setToolTip(
            zona["nombre"] + ("\nArrastra para mover; usa la esquina para"
                              " redimensionar." if editable else "")
        )
        self.setCursor(Qt.OpenHandCursor if editable else Qt.PointingHandCursor)
        self.setMouseTracking(True)

    # ------------------------------------------------------------------
    # Geometria (fracciones) en relacion al lienzo
    # ------------------------------------------------------------------

    def cw_ch(self):
        """Ancho/alto de la REGION del croquis (no del widget): los deltas del
        arrastre se miden en las mismas unidades que la geometria guardada."""
        lienzo = self.parent()
        if lienzo is None:
            return max(1, self.width()), max(1, self.height())
        _ox, _oy, cw, ch = lienzo._region_croquis()
        return max(1, cw), max(1, ch)

    def _manija(self):
        return QRectF(
            self.width() - TAMANIO_MANJA,
            self.height() - TAMANIO_MANJA,
            TAMANIO_MANJA,
            TAMANIO_MANJA,
        )

    # ------------------------------------------------------------------
    # Letra PROPORCIONAL al tamano del boton (el croquis agranda los botones)
    # ------------------------------------------------------------------

    def _banda_texto(self):
        """Altura (px) de la banda inferior que reserva la etiqueta."""
        return max(16, min(int(self.height() * 0.30), 42))

    def _px_fuente(self):
        """Tamano de letra de la etiqueta: crece con el tamano del boton."""
        if self.zona.get("icono"):
            return max(10, min(self._banda_texto() - 3, 20))
        return max(10, min(int(self.height() * 0.32), 22))

    # ------------------------------------------------------------------
    # Pintado (style.color consultado dentro del paintEvent: tema en caliente)
    # ------------------------------------------------------------------

    def paintEvent(self, _evento):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        sel = self._seleccionada
        fondo = QColor(style.color("exito" if sel else "elevada"))
        borde = QColor(style.color("accento" if sel else "borde"))
        texto = QColor(style.color("sobre_exito" if sel else "texto"))

        p.setPen(QPen(borde, 2 if sel else 1))
        p.setBrush(fondo)
        p.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5),
                          RADIO, RADIO)

        icono_px = max(
            8,
            int(float(self.zona["icono_frac"] or 0.5)
                * min(self.width(), self.height())),
        )
        nombre_icono = self.zona["icono"] or ""
        tam = self.size()
        margen_texto = self._banda_texto()

        p.setPen(texto)
        f = self.font()
        f.setBold(sel)
        if nombre_icono:
            ic = _pixmap_icono(nombre_icono, icono_px)
            x_ic = (tam.width() - ic.width()) / 2
            y_ic = max(2.0, (tam.height() - margen_texto - ic.height()) / 2)
            p.drawPixmap(int(x_ic), int(y_ic), ic)
            f.setPixelSize(self._px_fuente())
            p.setFont(f)
            ancho_txt = tam.width() - 12
            tr = QRectF(6, tam.height() - margen_texto + 1, ancho_txt,
                        margen_texto - 2)
        else:
            # Sin icono: la etiqueta ocupa todo el boton (mas legible).
            f.setPixelSize(self._px_fuente())
            p.setFont(f)
            ancho_txt = tam.width() - 12
            tr = QRectF(6, 0, ancho_txt, tam.height())
        p.drawText(
            tr,
            int(Qt.AlignHCenter | Qt.AlignVCenter),
            p.fontMetrics().elidedText(
                self.zona["nombre"], Qt.ElideRight, int(ancho_txt)
            ),
        )

        if self.editable and sel:
            manija = self._manija()
            p.setPen(QPen(QColor(style.color("accento")), 2))
            ext = QPointF(manija.right() - 3, manija.bottom() - 3)
            p.drawLine(
                QPointF(manija.right() - 3, manija.top() + 3), ext
            )
            p.drawLine(
                QPointF(manija.left() + 3, manija.bottom() - 3), ext
            )
        p.end()

    # ------------------------------------------------------------------
    # Raton (modo edicion: mover / redimensionar / hover de la manija)
    # ------------------------------------------------------------------

    def mousePressEvent(self, e):
        if not self.editable:
            if e.button() == Qt.LeftButton and self._on_seleccion:
                self._on_seleccion(self.zona_id)
            e.accept()
            return
        if e.button() != Qt.LeftButton:
            e.accept()
            return
        if self._manija().contains(e.position()):
            self._modo = "resize"
            self._inicio = e.globalPosition()
            self._orig = (float(self.zona["w"]), float(self.zona["h"]))
        else:
            self._modo = "move"
            self._inicio = e.globalPosition()
            self._orig = (float(self.zona["x"]), float(self.zona["y"]))
            if self._on_seleccion:
                self._on_seleccion(self.zona_id)
        e.accept()

    def mouseMoveEvent(self, e):
        if not self.editable:
            super().mouseMoveEvent(e)
            return
        if self._modo is None:
            self.setCursor(Qt.SizeFDiagCursor if self._manija().contains(
                e.position()) else Qt.OpenHandCursor)
            super().mouseMoveEvent(e)
            return
        cw, ch = self.cw_ch()
        delta = e.globalPosition() - QPointF(self._inicio)
        if self._modo == "move":
            nx = max(0.0, min(1.0 - float(self.zona["w"]),
                              self._orig[0] + delta.x() / cw))
            ny = max(0.0, min(1.0 - float(self.zona["h"]),
                              self._orig[1] + delta.y() / ch))
            self.zona["x"], self.zona["y"] = nx, ny
        else:
            nw = max(MIN_FRAC, min(1.0 - float(self.zona["x"]),
                                   self._orig[0] + delta.x() / cw))
            nh = max(MIN_FRAC, min(1.0 - float(self.zona["y"]),
                                   self._orig[1] + delta.y() / ch))
            self.zona["w"], self.zona["h"] = nw, nh
        if self.parent() is not None:
            self.parent()._aplicar_geometria(self)
        e.accept()

    def mouseReleaseEvent(self, e):
        if self.editable and self._modo is not None:
            z = self.zona
            if self._on_geometria is not None:
                self._on_geometria(
                    z["id"], float(z["x"]), float(z["y"]),
                    float(z["w"]), float(z["h"]), float(z["icono_frac"]),
                )
            self._modo = None
            self._inicio = None
            self._orig = None
            self.setCursor(Qt.OpenHandCursor)
            e.accept()
            return
        super().mouseReleaseEvent(e)


class ZonaCanvas(QFrame):
    """Lienzo del croquis: coloca los botones-zona con geometria absoluta
    escalada desde sus fracciones. Reacomoda en cada `resizeEvent`, asi el
    croquis se adapta al espacio disponible sin perder las proporciones."""

    def __init__(self, parent=None, editable=False, on_seleccion=None,
                 on_geometria=None, preseleccionar=True):
        super().__init__(parent)
        self._editable = editable
        self._on_seleccion = on_seleccion
        self._on_geometria = on_geometria
        # Con `preseleccionar=False` (modal de paro) al cargar NO se elige la
        # primera zona: el operador empieza con nada seleccionado.
        self._preseleccionar = bool(preseleccionar)
        self._seleccionado_id = None
        self._botones = {}
        self._zonas = []
        self.setMinimumSize(220, 150)
        self.cargar()

    # ------------------------------------------------------------------
    # Datos y geometrias
    # ------------------------------------------------------------------

    def cargar(self):
        prev = self._seleccionado_id
        for b in list(self._botones.values()):
            b.deleteLater()
        self._botones = {}
        self._zonas = [
            dict(z) for z in listar_zonas_maquina(activas_solo=True)
        ]
        for z in self._zonas:
            b = ZonaBoton(
                z,
                editable=self._editable,
                on_seleccion=self._seleccionar,
                on_geometria=self._on_geometria,
            )
            b.setParent(self)
            b.show()  # el padre ya estaba visible: sin show() quedan ocultos
            self._botones[z["id"]] = b
        self._aplicar_geometria()
        if self._zonas and self._preseleccionar:
            self._seleccionar(
                prev if prev in self._botones else self._zonas[0]["id"]
            )
        else:
            self._seleccionar(None)

    def _aplicar_geometria(self, boton=None):
        ox, oy, cw, ch = self._region_croquis()
        if cw <= 0 or ch <= 0:
            return
        objetivos = (
            [boton] if boton is not None else list(self._botones.values())
        )
        for b in objetivos:
            z = b.zona
            b.setGeometry(
                int(ox + float(z["x"]) * cw),
                int(oy + float(z["y"]) * ch),
                max(1, int(float(z["w"]) * cw)),
                max(1, int(float(z["h"]) * ch)),
            )

    def _region_croquis(self):
        """Region real del croquis: la proporcion de referencia, centrada en
        el lienzo. Con esto los botones conservan en TODOS los contextos la
        misma proporcion (y posicion relativa) que al disenarlos."""
        ancho, alto = self.width(), self.height()
        if ancho <= 0 or alto <= 0:
            return 0, 0, 0, 0
        if ancho * PROPORCION_REF <= alto:
            cw, ch = ancho, ancho * PROPORCION_REF
        else:
            ch, cw = alto, alto / PROPORCION_REF
        ox = (ancho - cw) / 2.0
        oy = (alto - ch) / 2.0
        return ox, oy, cw, ch

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._aplicar_geometria()

    # ------------------------------------------------------------------
    # Seleccion / habilitado
    # ------------------------------------------------------------------

    def _seleccionar(self, zona_id):
        self._seleccionado_id = zona_id
        for cid, b in self._botones.items():
            b._seleccionada = (cid == zona_id)
            b.update()
        if zona_id is not None and self._on_seleccion is not None:
            self._on_seleccion(zona_id)

    def set_enabled(self, habilitado):
        self.setEnabled(bool(habilitado))
        self._seleccionar(None)

    def zona_por_id(self, zona_id):
        b = self._botones.get(zona_id)
        return b.zona if b is not None else None
"""
admin_view.py - Panel de administracion (CRUD).

Tres pestanas:
    - Operadores: registro con rol (captura de minimo 2 huellas distintas),
      cambio de rol, eliminacion (soft) y gestion de huellas del operador
      seleccionado (agregar / reemplazar / eliminar).
    - Causas de paro: agregar / eliminar motivos (soft).
    - Roles: agregar, renombrar y desactivar roles.

El trabajo de captura de huella para registrar operadores corre en un hilo
secundario; los resultados se drenan por `queue.Queue()` (QTimer) en el hilo
principal.
"""

import logging
import queue
import re
import sys
import threading

import qtawesome as qta
from PySide6.QtCore import (
    QPointF,
    QRectF,
    QSize,
    QSortFilterProxyModel,
    QStringListModel,
    Qt,
    QTimer,
)
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSlider,
    QSpinBox,
    QSplitter,
    QStyle,
    QStyledItemDelegate,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from src import config
from src import update as actualizaciones
from src.database import (
    actualizar_permisos_rol,
    actualizar_rol_operador,
    agregar_causa_paro,
    agregar_huella,
    agregar_rol,
    eliminar_causa_paro,
    eliminar_huella,
    eliminar_operador,
    eliminar_rol,
    guardar_causa_paro,
    guardar_operador,
    guardar_zona,
    listar_causas_paro,
    listar_huellas_operador,
    listar_operadores_admin,
    listar_permisos,
    listar_roles,
    permisos_de_rol,
    reemplazar_huella,
    renombrar_rol,
    roles_con_permiso,
    sesion_activa_actual,
)
from src.gui import style
from src.gui.componentes.checkbox import CheckBox
from src.gui.componentes.util import centrar_y_ajustar, desplazamiento_tactil, preguntar_texto
from src.gui.modulos.corte.componentes.croquis_zonas import ZonaCanvas
from src.gui.style import COLOR_ACCENTE, aplicar_estado

try:
    from src.domain.easy import validar_rutina
    from src.gui.admin.rutinas_easy import repo as repo_easy
    from src.gui.admin.rutinas_easy.editor_pasos import EditorPasosEasy
except Exception:  # noqa: BLE001
    repo_easy = None
    EditorPasosEasy = None
    validar_rutina = None

log = logging.getLogger(__name__)



class CheckboxListWidget(QListWidget):
    """QListWidget cuyos items checkables alternan su estado al hacer clic en
    cualquier parte de la fila.

    El delegate pinta el checkbox custom, pero el QListView no reconoce esa
    zona como indicador, asi que el clic no alternaba nada; esta subclase
    alterna el check sobre toda la fila.
    """

    def mouseReleaseEvent(self, evento):
        item = self.itemAt(evento.position().toPoint())
        if item is not None:
            banderas = item.flags()
            if banderas & Qt.ItemIsUserCheckable and banderas & Qt.ItemIsEnabled:
                estado = item.checkState()
                item.setCheckState(
                    Qt.Unchecked if estado == Qt.Checked else Qt.Checked
                )
                # No llamar a super(): la vista tambien alterna al pulsar sobre
                # el indicador, y eso haria doble toggle (parece que el checkbox
                # "no funciona" porque cambia dos veces en el mismo clic).
                return
        super().mouseReleaseEvent(evento)


class CheckboxListDelegate(QStyledItemDelegate):
    """Delegate para listas con items checkables.

    Fusion + QSS no dibuja el indicador de los items checkables de un
    QListWidget (queda invisible sobre el fondo oscuro); este delegate pinta
    un checkbox propio (cuadro redondeado + palomita) acorde al tema.
    """

    def __init__(self, parent=None):
        super().__init__(parent)

    def sizeHint(self, option, index):
        s = super().sizeHint(option, index)
        return QSize(s.width() + 38, max(s.height(), 26))

    def paint(self, painter, option, index):
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        rect = option.rect
        habilitado = bool(option.state & QStyle.State_Enabled)

        # Fondo de la fila: seleccion o neutro. Colores del tema ACTIVO.
        if habilitado and option.state & QStyle.State_Selected:
            painter.fillRect(rect, QColor(COLOR_ACCENTE))
        else:
            painter.fillRect(rect, QColor(style.color("superficie")))

        # Cuadro del checkbox.
        alto = rect.height()
        cb = QRectF(rect.x() + 8, rect.y() + (alto - 20) / 2.0, 20, 20)
        marcado = option.checkState == Qt.Checked or (
            int(index.data(Qt.CheckStateRole) or 0) == Qt.CheckState.Checked.value
        )
        if habilitado:
            borde = QColor(style.color("deshabilitado_texto"))
            fondo = QColor(style.color("elevada"))
            relleno = QColor(COLOR_ACCENTE)
            palomita = QColor(style.color("blanco"))
        else:
            borde = QColor(style.color("deshabilitado_bg"))
            fondo = QColor(style.color("lista_disabled_bg"))
            relleno = QColor(style.color("deshabilitado_bg"))
            palomita = QColor(style.color("deshabilitado_texto"))
        painter.setPen(QPen(relleno if marcado else borde, 2))
        painter.setBrush(relleno if marcado else fondo)
        painter.drawRoundedRect(cb, 5, 5)
        if marcado:
            pen = QPen(palomita, 2.2)
            pen.setCapStyle(Qt.RoundCap)
            painter.setPen(pen)
            painter.drawPolyline(
                QPolygonF(
                    [
                        QPointF(cb.x() + 4.5, cb.y() + 10.5),
                        QPointF(cb.x() + 9.0, cb.y() + 15.0),
                        QPointF(cb.x() + 16.0, cb.y() + 5.5),
                    ]
                )
            )

        # Texto de la descripcion.
        texto = index.data(Qt.DisplayRole)
        tr = QRectF(rect.adjusted(38, 0, -8, 0))
        painter.setPen(QColor(
            style.color("deshabilitado_texto" if not habilitado else "texto")
        ))
        painter.drawText(
            tr,
            int(Qt.AlignVCenter | Qt.AlignLeft),
            painter.fontMetrics().elidedText(texto, Qt.ElideRight, int(tr.width())),
        )
        painter.restore()


# Iconos qtawesome disponibles para los botones de las ZONAS (punto 7).
# El buscador lista TODO el catalogo (mdi6, fa5s, fa6, ph, ri, ...) cargado
# perezosamente; esta cache evita re-enumerar ~10k iconos en cada apertura.
_CACHE_TODOS_ICONOS = None


def _todos_los_iconos():
    """Lista plana 'prefijo.nombre' de TODOS los iconos qtawesome.

    El charmap del singleton se llena al cargar las fuentes (QApplication en
    marcha). Si por cualquier motivo no se pudiera enumerar, queda vacio y el
    buscador solo muestra lo escrito manualmente (no bloquea la GUI).
    """
    global _CACHE_TODOS_ICONOS
    if _CACHE_TODOS_ICONOS is None:
        try:
            mapas = qta._instance().charmap
            _CACHE_TODOS_ICONOS = sorted(
                f"{prefijo}.{nombre}"
                for prefijo, iconos in mapas.items()
                for nombre in iconos
            )
        except Exception:  # noqa: BLE001
            _CACHE_TODOS_ICONOS = []
    return _CACHE_TODOS_ICONOS


class _ModeloIconos(QStringListModel):
    """Modelo de iconos: el rol decorativo renderiza el QIcon (solo los items
    visibles se rasterizan, permitiendo navegar el catalogo completo)."""

    def data(self, index, role):
        if role == Qt.DecorationRole:
            nombre = self.data(index, Qt.DisplayRole)
            try:
                return qta.icon(nombre, color=style.color("texto"))
            except Exception:  # noqa: BLE001
                return qta.icon("mdi6.help-circle", color=style.color("texto"))
        return super().data(index, role)


class CroquisZonasEditor(QFrame):
    """Editor WYSIWYG de zonas del croquis (punto 7).

    Permite mover libremente cada zona arrastrando su cuerpo y redimensionarla
    arrastrando la manija de su esquina inferior-derecha. Al soltar se
    persiste automaticamente la geometria en BD via `guardar_zona`.
    """

    def __init__(self, parent=None, on_seleccion=None):
        super().__init__(parent)
        self.setObjectName("CausasGrid")
        self._on_seleccion = on_seleccion
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._canvas = ZonaCanvas(
            self,
            editable=True,
            on_seleccion=self._seleccionar,
            on_geometria=self._persistir_geometria,
        )
        layout.addWidget(self._canvas)

    def _cargar(self):
        self._canvas.cargar()

    def zona_por_id(self, zona_id):
        return self._canvas.zona_por_id(zona_id)

    @property
    def _selected_id(self):
        return self._canvas._seleccionado_id

    def _seleccionar(self, zona_id):
        if self._on_seleccion and zona_id is not None:
            self._on_seleccion(zona_id)

    def _persistir_geometria(self, zona_id, x, y, w, h, icono_frac):
        zona = self.zona_por_id(zona_id)
        icono = (zona["icono"] if zona else "") or ""
        maquina = (zona["maquina_encendida"] if zona else 0) or 0
        guardar_zona(zona_id, icono, x, y, w, h, icono_frac, maquina)


class SelectorIconoModal(QDialog):
    """Buscador de iconos qtawesome (TODO el catalogo) para las ZONAS.

    Estilo "qtawesome icon browser": campo de busqueda + combobox de coleccion
    + cuadricula en IconMode con render perezoso (solo los iconos visibles se
    rasterizan), asi navegar ~10k iconos no congela la interfaz.
    """

    def __init__(self, parent, actual=""):
        super().__init__(parent)
        self.icono_elegido = actual
        self.setWindowTitle("Buscador de iconos")
        self.setModal(True)
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)

        nombres = _todos_los_iconos()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(8)

        barra = QHBoxLayout()
        self.cmb_fuente = QComboBox(self)
        self.cmb_fuente.addItem("Todas las colecciones", "")
        for fuente in sorted({n.split(".", 1)[0] for n in nombres}):
            self.cmb_fuente.addItem(fuente, fuente)
        self.cmb_fuente.setToolTip("Filtrar por coleccion (mdi6, fa5s, ...)")
        barra.addWidget(self.cmb_fuente)

        self.txt_buscar = QLineEdit(self)
        self.txt_buscar.setPlaceholderText("Buscar icono por nombre...")
        self.txt_buscar.setClearButtonEnabled(True)
        barra.addWidget(self.txt_buscar, stretch=1)

        self.lbl_resumen = QLabel("", self)
        self.lbl_resumen.setObjectName("EstadoInfo")
        barra.addWidget(self.lbl_resumen)
        layout.addLayout(barra)

        self.modelo = _ModeloIconos(nombres, self)
        self.proxy = QSortFilterProxyModel(self)
        self.proxy.setSourceModel(self.modelo)
        self.proxy.setFilterCaseSensitivity(Qt.CaseInsensitive)

        self.lista = QListView(self)
        self.lista.setModel(self.proxy)
        self.lista.setViewMode(QListView.IconMode)
        self.lista.setUniformItemSizes(True)
        self.lista.setWordWrap(True)
        self.lista.setGridSize(QSize(100, 100))
        self.lista.setIconSize(QSize(48, 48))
        self.lista.setSpacing(6)
        self.lista.setSelectionMode(QAbstractItemView.SingleSelection)
        self.lista.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.lista.doubleClicked.connect(self._aceptar)
        layout.addWidget(self.lista, stretch=1)
        desplazamiento_tactil(self.lista)

        barra2 = QWidget(self)
        h2 = QHBoxLayout(barra2)
        h2.setContentsMargins(0, 0, 0, 0)
        h2.setSpacing(8)
        btn_sin = QPushButton("Sin icono", barra2)
        btn_sin.clicked.connect(lambda: self._elegir(""))
        h2.addWidget(btn_sin)
        h2.addStretch(1)
        btn_aceptar = QPushButton("Aceptar", barra2)
        btn_aceptar.setObjectName("Success")
        btn_aceptar.setEnabled(False)
        btn_aceptar.clicked.connect(self._aceptar)
        h2.addWidget(btn_aceptar)
        btn_cancelar = QPushButton("Cancelar", barra2)
        btn_cancelar.clicked.connect(self.reject)
        h2.addWidget(btn_cancelar)
        layout.addWidget(barra2)

        self._btn_aceptar = btn_aceptar
        self.cmb_fuente.currentIndexChanged.connect(self._actualizar_filtro)
        self.txt_buscar.textChanged.connect(self._actualizar_filtro)
        self.lista.selectionModel().selectionChanged.connect(
            self._al_cambiar_seleccion
        )

        self.setMinimumSize(560, 440)
        centrar_y_ajustar(self, parent)

        if actual:
            try:
                fila = nombres.index(actual)
            except ValueError:
                fila = -1
            if fila >= 0:
                self.lista.setCurrentIndex(self.proxy.mapFromSource(
                    self.modelo.index(fila)))
        self._actualizar_filtro()
        self._al_cambiar_seleccion()
        self.txt_buscar.setFocus()

    def _actualizar_filtro(self):
        prefijo = self.cmb_fuente.currentData()
        texto = self.txt_buscar.text()
        patron = ""
        if prefijo:
            patron += rf"^{re.escape(prefijo)}\."
        if texto:
            patron += rf".*{re.escape(texto)}.*"
        self.proxy.setFilterRegularExpression(patron or ".*")
        self.lbl_resumen.setText(f"{self.proxy.rowCount()} iconos")

    def _al_cambiar_seleccion(self):
        self._btn_aceptar.setEnabled(self.lista.currentIndex().isValid())

    def _aceptar(self):
        idx = self.lista.currentIndex()
        if idx.isValid():
            self.icono_elegido = idx.data(Qt.DisplayRole)
        self.accept()

    def _elegir(self, nombre):
        self.icono_elegido = nombre
        self.accept()



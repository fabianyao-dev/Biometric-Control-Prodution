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
    QComboBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSlider,
    QStyle,
    QStyledItemDelegate,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

import qtawesome as qta

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
from src.gui.checkbox import CheckBox
from src.gui.croquis_zonas import ZonaCanvas
from src.gui.style import COLOR_ACCENTE, aplicar_estado
from src.gui.util import centrar_y_ajustar, desplazamiento_tactil, preguntar_texto

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


class AdminView(QWidget):
    def __init__(self, parent, controller, biometrico):
        super().__init__(parent)
        self.controller = controller
        self.biometrico = biometrico

        self._capturando = False
        self._huellas_captura = []
        self._modo_captura = None
        # Captura MULTIPLE encadenada: al registrar un operador nuevo se
        # capturan las huellas una tras otra (sin pulsar el boton por cada
        # dedo) hasta que se presione 'Detener Captura'.
        self._modo_cadena = False
        # Indica que la cadena quedo en espera de que el usuario coloque un
        # dedo distinto (no avanza solo hasta que arranca la captura).
        self._cadena_esperando = False
        self.cola = queue.Queue()
        self.cola_update = queue.Queue()
        self._manifest = None
        self._roles_por_nombre = {}
        self._acceso_admin_bloqueado = False

        self._crear_interfaz()
        self._revisar_cola()
        self._revisar_cola_update()

    def _crear_interfaz(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)

        self.notebook = QTabWidget(self)
        layout.addWidget(self.notebook)

        self.tab_operadores = QWidget()
        self.tab_causas = QWidget()
        self.tab_zonas = QWidget()
        self.tab_roles = QWidget()
        self.tab_sistema = QWidget()
        self.notebook.addTab(self.tab_operadores, "Operadores")
        self.notebook.addTab(self.tab_causas, "Causas de Paro")
        self.notebook.addTab(self.tab_zonas, "Zonas")
        self.notebook.addTab(self.tab_roles, "Roles")
        self.notebook.addTab(self.tab_sistema, "Sistema")

        self._crear_tab_operadores()
        self._crear_tab_causas()
        self._crear_tab_zonas()
        self._crear_tab_roles()
        self._crear_tab_sistema()

    @staticmethod
    def _config_tabla(tabla):
        tabla.setSelectionBehavior(QAbstractItemView.SelectRows)
        tabla.setSelectionMode(QAbstractItemView.SingleSelection)
        tabla.setEditTriggers(QAbstractItemView.NoEditTriggers)
        tabla.verticalHeader().setVisible(False)
        tabla.setAlternatingRowColors(True)
        tabla.setShowGrid(False)
        tabla.horizontalHeader().setStretchLastSection(True)

    # ------------------------------------------------------------------
    # Roles (combo compartido por operadores)
    # ------------------------------------------------------------------

    def _recargar_roles_combo(self):
        """Actualiza los combos de rol y recuerda la seleccion por defecto."""
        self._roles_por_nombre = {
            r["nombre"]: r["id"] for r in listar_roles(activas_solo=True)
        }
        nombres = list(self._roles_por_nombre.keys())
        self.combo_rol.clear()
        self.combo_rol_cambio.clear()
        self.combo_rol.addItems(nombres)
        self.combo_rol_cambio.addItems(nombres)
        # Seleccion por defecto: operador (si existe), si no el primer rol.
        predeterminado = "operador" if "operador" in self._roles_por_nombre else (
            nombres[0] if nombres else "")
        if predeterminado:
            self.combo_rol.setCurrentText(predeterminado)

    # ------------------------------------------------------------------
    # Tab Operadores
    # ------------------------------------------------------------------

    def _crear_tab_operadores(self):
        layout = QVBoxLayout(self.tab_operadores)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(8)

        titulo = QLabel("Registro de Operador", self.tab_operadores)
        titulo.setObjectName("Title")
        layout.addWidget(titulo, alignment=Qt.AlignHCenter)

        fila_nombre_rol = QWidget(self.tab_operadores)
        hn = QHBoxLayout(fila_nombre_rol)
        hn.setContentsMargins(0, 0, 0, 0)
        hn.setSpacing(6)
        self.entry_nombre = QLineEdit(fila_nombre_rol)
        self.entry_nombre.setPlaceholderText("Nombre del operador")
        self.entry_nombre.setFixedWidth(300)
        hn.addWidget(self.entry_nombre)
        lbl_rol = QLabel("Rol:", fila_nombre_rol)
        lbl_rol.setObjectName("EstadoInfo")
        hn.addWidget(lbl_rol)
        self.combo_rol = QComboBox(fila_nombre_rol)
        self.combo_rol.setMinimumWidth(200)
        hn.addWidget(self.combo_rol)
        layout.addWidget(fila_nombre_rol, alignment=Qt.AlignHCenter)

        self.lbl_huella = QLabel(
            "Huellas capturadas: 0",
            self.tab_operadores,
        )
        aplicar_estado(self.lbl_huella, "info")
        layout.addWidget(self.lbl_huella, alignment=Qt.AlignHCenter)

        frame_botones = QWidget(self.tab_operadores)
        hb = QHBoxLayout(frame_botones)
        hb.setContentsMargins(0, 0, 0, 0)
        hb.setSpacing(8)
        self.btn_capturar = QPushButton("Capturar Huellas", frame_botones)
        self.btn_capturar.setToolTip(
            "Captura las huellas una tras otra. Vuelve a presionar "
            "'Detener Captura' cuando hayas puesto las que quieras."
        )
        self.btn_capturar.clicked.connect(self._capturar_huella)
        hb.addWidget(self.btn_capturar)
        btn_quitar = QPushButton("Quitar Última", frame_botones)
        btn_quitar.clicked.connect(self._quitar_ultima_huella)
        hb.addWidget(btn_quitar)
        btn_guardar = QPushButton("Guardar Operador", frame_botones)
        btn_guardar.setObjectName("Success")
        btn_guardar.clicked.connect(self._guardar_operador)
        hb.addWidget(btn_guardar)
        layout.addWidget(frame_botones, alignment=Qt.AlignHCenter)

        self.lbl_mensaje = QLabel("", self.tab_operadores)
        aplicar_estado(self.lbl_mensaje, "info")
        layout.addWidget(self.lbl_mensaje, alignment=Qt.AlignHCenter)

        sep = QFrame(self.tab_operadores)
        sep.setFrameShape(QFrame.HLine)
        sep.setObjectName("Separador")
        layout.addWidget(sep)

        columnas = QWidget(self.tab_operadores)
        hcols = QHBoxLayout(columnas)
        hcols.setContentsMargins(0, 0, 0, 0)
        hcols.setSpacing(12)

        # Columna izquierda: operadores.
        col_operadores = QWidget(columnas)
        lv_ops = QVBoxLayout(col_operadores)
        lv_ops.setContentsMargins(0, 0, 0, 0)
        lv_ops.setSpacing(6)

        lbl_lista = QLabel("Operadores registrados:", col_operadores)
        lbl_lista.setObjectName("HeaderLabel")
        lv_ops.addWidget(lbl_lista)

        self.lista_operadores = QTableWidget(0, 3, col_operadores)
        self.lista_operadores.setHorizontalHeaderLabels(
            ["ID", "Nombre", "Rol"]
        )
        self._config_tabla(self.lista_operadores)
        for i, ancho in enumerate((50, 200, 140)):
            self.lista_operadores.setColumnWidth(i, ancho)
        lv_ops.addWidget(self.lista_operadores, stretch=1)

        fila_eliminar = QWidget(col_operadores)
        h1 = QHBoxLayout(fila_eliminar)
        h1.setContentsMargins(0, 0, 0, 0)
        h1.setSpacing(6)
        btn_eliminar = QPushButton("Eliminar Operador", fila_eliminar)
        btn_eliminar.clicked.connect(self._eliminar_operador)
        h1.addWidget(btn_eliminar)
        lv_ops.addWidget(fila_eliminar, alignment=Qt.AlignHCenter)

        fila_cambio = QWidget(col_operadores)
        h2 = QHBoxLayout(fila_cambio)
        h2.setContentsMargins(0, 0, 0, 0)
        h2.setSpacing(6)
        lbl_cambio = QLabel("Rol:", fila_cambio)
        lbl_cambio.setObjectName("EstadoInfo")
        h2.addWidget(lbl_cambio)
        self.combo_rol_cambio = QComboBox(fila_cambio)
        self.combo_rol_cambio.setMinimumWidth(110)
        h2.addWidget(self.combo_rol_cambio)
        btn_aplicar = QPushButton("Aplicar", fila_cambio)
        btn_aplicar.clicked.connect(self._aplicar_cambio_rol)
        h2.addWidget(btn_aplicar)
        lv_ops.addWidget(fila_cambio, alignment=Qt.AlignHCenter)

        # Columna derecha: huellas del operador seleccionado.
        col_huellas = QWidget(columnas)
        lv_huellas = QVBoxLayout(col_huellas)
        lv_huellas.setContentsMargins(0, 0, 0, 0)
        lv_huellas.setSpacing(6)

        lbl_huellas_titulo = QLabel(
            "Huellas del operador seleccionado:", col_huellas
        )
        lbl_huellas_titulo.setObjectName("HeaderLabel")
        lv_huellas.addWidget(lbl_huellas_titulo)

        self.lbl_huellas_info = QLabel(
            "Selecciona un operador de la lista.", col_huellas
        )
        self.lbl_huellas_info.setObjectName("EstadoInfo")
        lv_huellas.addWidget(self.lbl_huellas_info)

        self.lista_huellas = QTableWidget(0, 2, col_huellas)
        self.lista_huellas.setHorizontalHeaderLabels(["ID", "Fecha de captura"])
        self._config_tabla(self.lista_huellas)
        for i, ancho in enumerate((60, 200)):
            self.lista_huellas.setColumnWidth(i, ancho)
        lv_huellas.addWidget(self.lista_huellas, stretch=1)

        fila_huellas = QWidget(col_huellas)
        hhu = QHBoxLayout(fila_huellas)
        hhu.setContentsMargins(0, 0, 0, 0)
        hhu.setSpacing(6)
        btn_agregar_huella = QPushButton("Agregar Huella", fila_huellas)
        btn_agregar_huella.clicked.connect(self._capturar_huella_agregar)
        hhu.addWidget(btn_agregar_huella)
        btn_reemplazar_huella = QPushButton("Reemplazar Huella", fila_huellas)
        btn_reemplazar_huella.clicked.connect(self._capturar_huella_reemplazar)
        hhu.addWidget(btn_reemplazar_huella)
        lv_huellas.addWidget(fila_huellas, alignment=Qt.AlignHCenter)

        fila_huella_eliminar = QWidget(col_huellas)
        hhe = QHBoxLayout(fila_huella_eliminar)
        hhe.setContentsMargins(0, 0, 0, 0)
        hhe.setSpacing(6)
        btn_eliminar_huella = QPushButton("Eliminar Huella", fila_huella_eliminar)
        btn_eliminar_huella.clicked.connect(self._eliminar_huella)
        hhe.addWidget(btn_eliminar_huella)
        lv_huellas.addWidget(fila_huella_eliminar, alignment=Qt.AlignHCenter)

        self.lbl_huellas_msg = QLabel("", col_huellas)
        aplicar_estado(self.lbl_huellas_msg, "info")
        lv_huellas.addWidget(self.lbl_huellas_msg, alignment=Qt.AlignHCenter)

        hcols.addWidget(col_operadores, stretch=1)
        hcols.addWidget(col_huellas, stretch=1)
        layout.addWidget(columnas, stretch=1)

        self._recargar_roles_combo()
        self._recargar_operadores()
        self.lista_operadores.itemSelectionChanged.connect(self._recargar_huellas)
        self._recargar_huellas()

    def _capturar_huella(self):
        """Toggle de captura MULTIPLE. El boton inicia la cadena (se capturan
        huellas una tras otra sin pulsar por cada dedo) y, al volver a
        presionarlo, la DETIENE dejando las huellas capturadas hasta ese
        momento (el usuario decide cuantas poner)."""
        if self._modo_cadena:
            self._detener_cadena()
            return
        if self._capturando:
            # Otra captura en curso (agregar/reemplazar de un operador).
            return
        if not self.entry_nombre.text().strip():
            self._lbl("Escribe el nombre antes de capturar las huellas.", "error")
            return
        self._modo_captura = None
        self._modo_cadena = True
        self._cadena_esperando = False
        self._lbl("", "info")
        self._lbl_huella(
            "Coloca tu huella... Presiona 'Detener Captura' al terminar.",
            "procesando",
        )
        self._iniciar_captura()
        self._actualizar_boton_captura()

    def _detener_cadena(self):
        """Detiene la captura encadenada; conserva las huellas ya capturadas."""
        self._modo_cadena = False
        self._cadena_esperando = False
        self._lbl_huella("Captura detenida.", "info")
        self._actualizar_boton_captura()

    def _actualizar_boton_captura(self):
        texto = "Detener Captura" if self._modo_cadena else "Capturar Huellas"
        self.btn_capturar.setText(texto)

    def _capturar_huella_agregar(self):
        if self._capturando:
            return
        op_id, _ = self._operador_seleccionado()
        if op_id is None:
            self._lbl_huellas("Selecciona un operador de la lista.", "error")
            return
        self._modo_captura = ("agregar", op_id)
        self._lbl_huellas("Coloca tu huella...", "procesando")
        self._iniciar_captura()

    def _capturar_huella_reemplazar(self):
        if self._capturando:
            return
        huella_id = self._huella_seleccionada()
        if huella_id is None:
            self._lbl_huellas("Selecciona una huella de la lista.", "error")
            return
        self._modo_captura = ("reemplazar", huella_id)
        self._lbl_huellas("Coloca tu huella...", "procesando")
        self._iniciar_captura()

    def _iniciar_captura(self):
        self._capturando = True
        threading.Thread(target=self._hilo_captura, daemon=True).start()

    def _hilo_captura(self):
        try:
            data = self.biometrico.enrollar(on_progress=self._progreso)
            self.cola.put(("ENROLL", data))
        except Exception as e:  # noqa: BLE001
            log.error("Captura admin fallo: %s", e, exc_info=True)
            self.cola.put(("ERROR", str(e)))

    def _progreso(self, mensaje):
        self.cola.put(("PROGRESO", mensaje))

    def _guardar_operador(self):
        if self._capturando:
            return
        nombre = self.entry_nombre.text().strip()
        if not nombre:
            self._lbl("Escribe el nombre.", "error")
            return
        if not self._huellas_captura:
            self._lbl("Captura al menos una huella.", "error")
            return
        rol_id = self._roles_por_nombre.get(self.combo_rol.currentText())
        ok, res = guardar_operador(nombre, self._huellas_captura, rol_id)
        if ok:
            self._lbl(
                f"Operador '{nombre}' registrado con "
                f"{len(self._huellas_captura)} huellas.",
                "exito",
            )
            self.entry_nombre.clear()
            self._huellas_captura = []
            self._modo_cadena = False
            self._cadena_esperando = False
            self._actualizar_estado_captura()
            self._actualizar_boton_captura()
            self._recargar_operadores()
        else:
            self._lbl(str(res), "error")

    def _quitar_ultima_huella(self):
        if not self._huellas_captura:
            return
        # Quitar la ultima tambien DETIENE la cadena de captura multiple.
        self._modo_cadena = False
        self._cadena_esperando = False
        self._huellas_captura.pop()
        self._lbl("Última huella quitada.", "info")
        self._actualizar_estado_captura()
        self._actualizar_boton_captura()

    def _agregar_huella_captura(self, fmd):
        if self._es_duplicada(fmd, self._huellas_captura):
            self._lbl_huella(
                "Esa huella ya se puso. Usa un dedo distinto.", "error"
            )
            if self._modo_cadena:
                # En cadena no se corta: se vuelve a pedir un dedo distinto.
                self._lbl_huella(
                    "Esa huella ya se puso. Retira el dedo y coloca uno "
                    "distinto...",
                    "error",
                )
                self._encadenar_captura()
            return
        self._huellas_captura.append(fmd)
        n = len(self._huellas_captura)
        self._lbl(
            f"Huella {n} capturada. Presiona 'Detener Captura' para "
            "terminar.",
            "exito",
        )
        self._actualizar_estado_captura()
        if self._modo_cadena:
            self._encadenar_captura()

    def _encadenar_captura(self):
        """Arranca la siguiente captura de la cadena con una pausa para que
        el operador retire el dedo y coloque otro."""
        if not self._modo_cadena or self._cadena_esperando:
            return
        if self._capturando:
            return
        self._cadena_esperando = True
        QTimer.singleShot(
            900,
            lambda: self._lanzar_siguiente_captura_cadena()
        )

    def _lanzar_siguiente_captura_cadena(self):
        self._cadena_esperando = False
        # Si mientras se esperaba se detuvo o cancelo la cadena, no lanzar.
        if not self._modo_cadena:
            return
        if self._capturando:
            self._encadenar_captura()
            return
        self._lbl_huella("Coloca el siguiente dedo...", "procesando")
        self._iniciar_captura()

    def _actualizar_estado_captura(self):
        self._lbl_huella(
            f"Huellas capturadas: {len(self._huellas_captura)}.",
            "info",
        )

    def _agregar_huella_operador(self, op_id, fmd):
        existentes = [
            f["huella_template"]
            for f in listar_huellas_operador(op_id, con_template=True)
        ]
        if self._es_duplicada(fmd, existentes):
            self._lbl_huellas(
                "Esa huella ya está registrada para este operador.", "error"
            )
            return
        if agregar_huella(op_id, fmd):
            self._lbl_huellas("Huella agregada.", "exito")
            self._recargar_huellas()
        else:
            self._lbl_huellas("No se pudo agregar la huella.", "error")

    def _reemplazar_huella(self, huella_id, fmd):
        if reemplazar_huella(huella_id, fmd):
            self._lbl_huellas("Huella reemplazada.", "exito")
            self._recargar_huellas()
        else:
            self._lbl_huellas("No se pudo reemplazar la huella.", "error")

    def _es_duplicada(self, fmd, lista):
        for otra in lista:
            score = self.biometrico.comparar(fmd, otra)
            if score is not None and score <= config.UMBRAL_DISIMILARIDAD:
                return True
        return False

    def _eliminar_huella(self):
        op_id, _ = self._operador_seleccionado()
        huella_id = self._huella_seleccionada()
        if op_id is None or huella_id is None:
            self._lbl_huellas("Selecciona una huella de la lista.", "error")
            return
        if len(listar_huellas_operador(op_id)) <= 1:
            self._lbl_huellas(
                "El operador debe conservar al menos una huella.", "error"
            )
            return
        if eliminar_huella(huella_id):
            self._lbl_huellas("Huella eliminada.", "exito")
            self._recargar_huellas()
        else:
            self._lbl_huellas("No se pudo eliminar la huella.", "error")

    def _operador_seleccionado(self):
        fila = self.lista_operadores.currentRow()
        if fila < 0:
            return None, ""
        return (
            int(self.lista_operadores.item(fila, 0).text()),
            self.lista_operadores.item(fila, 1).text(),
        )

    def _huella_seleccionada(self):
        fila = self.lista_huellas.currentRow()
        if fila < 0:
            return None
        return int(self.lista_huellas.item(fila, 0).text())

    def _recargar_huellas(self):
        self.lista_huellas.setRowCount(0)
        op_id, nombre = self._operador_seleccionado()
        if op_id is None:
            self.lbl_huellas_info.setText(
                "Selecciona un operador de la lista para ver sus huellas."
            )
            return
        huellas = listar_huellas_operador(op_id)
        self.lbl_huellas_info.setText(
            f"Operador: {nombre} ({len(huellas)} huella(s))"
        )
        for h in huellas:
            fila = self.lista_huellas.rowCount()
            self.lista_huellas.insertRow(fila)
            self.lista_huellas.setItem(fila, 0, QTableWidgetItem(str(h["id"])))
            self.lista_huellas.setItem(
                fila, 1, QTableWidgetItem(str(h["fecha_captura"]))
            )

    def _eliminar_operador(self):
        fila = self.lista_operadores.currentRow()
        if fila < 0:
            self._lbl("Selecciona un operador de la lista.", "error")
            return
        op_id = int(self.lista_operadores.item(fila, 0).text())
        eliminar_operador(op_id)
        self._lbl("Operador eliminado (desactivado).", "exito")
        self._recargar_operadores()

    def _aplicar_cambio_rol(self):
        fila = self.lista_operadores.currentRow()
        if fila < 0:
            self._lbl("Selecciona un operador de la lista.", "error")
            return
        rol_id = self._roles_por_nombre.get(self.combo_rol_cambio.currentText())
        if rol_id is None:
            self._lbl("Selecciona un rol valido.", "error")
            return
        op_id = int(self.lista_operadores.item(fila, 0).text())
        actualizar_rol_operador(op_id, rol_id)
        self._lbl("Rol actualizado.", "exito")
        self._recargar_operadores()

    def _recargar_operadores(self):
        self.lista_operadores.setRowCount(0)
        for op in listar_operadores_admin():
            if not op["activo"]:
                continue
            fila = self.lista_operadores.rowCount()
            self.lista_operadores.insertRow(fila)
            rol = op["rol"] or "Sin rol"
            valores = (op["id"], op["nombre"], rol)
            for col, valor in enumerate(valores):
                self.lista_operadores.setItem(fila, col, QTableWidgetItem(str(valor)))

    # ------------------------------------------------------------------
    # Tab Causas de paro
    # ------------------------------------------------------------------

    def _crear_tab_causas(self):
        layout = QVBoxLayout(self.tab_causas)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(8)

        titulo = QLabel("Causas de Paro", self.tab_causas)
        titulo.setObjectName("Title")
        layout.addWidget(titulo, alignment=Qt.AlignHCenter)

        # Fila: agregar causa nueva (con su regla de zona, visible desde el alta).
        fila_nueva = QWidget(self.tab_causas)
        hn = QHBoxLayout(fila_nueva)
        hn.setContentsMargins(0, 0, 0, 0)
        hn.setSpacing(6)
        self.entry_causa = QLineEdit(fila_nueva)
        self.entry_causa.setPlaceholderText("Descripcion de la causa")
        self.entry_causa.setFixedWidth(290)
        hn.addWidget(self.entry_causa)
        self.check_causa_nueva = CheckBox("Requiere zona", fila_nueva)
        self.check_causa_nueva.setToolTip(
            "Si está marcada, al detenerse con esta causa se exige elegir "
            "una zona del croquis."
        )
        hn.addWidget(self.check_causa_nueva)
        btn_agregar = QPushButton("Agregar Causa", fila_nueva)
        btn_agregar.clicked.connect(self._agregar_causa)
        hn.addWidget(btn_agregar)
        layout.addWidget(fila_nueva, alignment=Qt.AlignHCenter)

        self.lbl_causa_msg = QLabel("", self.tab_causas)
        aplicar_estado(self.lbl_causa_msg, "info")
        layout.addWidget(self.lbl_causa_msg, alignment=Qt.AlignHCenter)

        # Las causas NO se editan visualmente (icono/tamano/orden son de las
        # ZONAS); solo descripcion + la regla `requiere_zona` (si exige elegir
        # zona del croquis al detenerse).
        self.lista_causas = QTableWidget(0, 4, self.tab_causas)
        self.lista_causas.setHorizontalHeaderLabels(
            ["ID", "Descripcion", "Requiere zona", "Estado"]
        )
        self._config_tabla(self.lista_causas)
        self.lista_causas.setColumnWidth(0, 45)
        self.lista_causas.setColumnWidth(1, 300)
        self.lista_causas.setColumnWidth(2, 110)
        self.lista_causas.itemSelectionChanged.connect(self._seleccionar_causa)
        layout.addWidget(self.lista_causas, stretch=1)

        lbl_edicion = QLabel("Editar causa seleccionada:", self.tab_causas)
        lbl_edicion.setObjectName("HeaderLabel")
        layout.addWidget(lbl_edicion, alignment=Qt.AlignLeft)

        panel = QFrame(self.tab_causas)
        gp = QGridLayout(panel)
        gp.setContentsMargins(10, 8, 10, 8)
        gp.setSpacing(6)

        gp.addWidget(QLabel("Descripcion:"), 0, 0)
        self.edit_causa_desc = QLineEdit(panel)
        self.edit_causa_desc.setFixedWidth(280)
        gp.addWidget(self.edit_causa_desc, 0, 1)

        gp.addWidget(QLabel("Zona del croquis:"), 1, 0)
        self.check_causa_zona = CheckBox(
            "Exigir elegir zona al detenerse", panel
        )
        gp.addWidget(self.check_causa_zona, 1, 1)

        botones = QWidget(panel)
        hb = QHBoxLayout(botones)
        hb.setContentsMargins(0, 0, 0, 0)
        hb.setSpacing(6)
        btn_guardar = QPushButton("Guardar cambios", botones)
        btn_guardar.setObjectName("Success")
        btn_guardar.clicked.connect(self._guardar_causa)
        hb.addWidget(btn_guardar)
        btn_eliminar = QPushButton("Eliminar Causa", botones)
        btn_eliminar.clicked.connect(self._eliminar_causa)
        hb.addWidget(btn_eliminar)
        hb.addStretch(1)
        gp.addWidget(botones, 2, 0, 1, 2)

        layout.addWidget(panel)

        self._causa_seleccionada_id = None
        self._recargar_causas()

    # ------------------------------------------------------------------
    # Causas: logica (solo descripcion + requiere_zona: fijas, sin edicion
    # visual de icono/tamano/orden, que pertenece a las ZONAS)
    # ------------------------------------------------------------------

    def _agregar_causa(self):
        desc = self.entry_causa.text().strip()
        if not desc:
            self._lbl_causa("Escribe una descripcion.", "error")
            return
        if agregar_causa_paro(
            desc, requiere_zona=self.check_causa_nueva.isChecked()
        ):
            self.entry_causa.clear()
            self.check_causa_nueva.setChecked(False)
            self._lbl_causa("Causa agregada.", "exito")
            self._recargar_causas()
        else:
            self._lbl_causa("Descripcion vacia.", "error")

    def _recargar_causas(self):
        self.lista_causas.setRowCount(0)
        por_id = {}
        for causa in listar_causas_paro(activas_solo=True):
            fila = self.lista_causas.rowCount()
            self.lista_causas.insertRow(fila)
            self.lista_causas.setItem(fila, 0, QTableWidgetItem(str(causa["id"])))
            self.lista_causas.setItem(
                fila, 1, QTableWidgetItem(causa["descripcion"])
            )
            self.lista_causas.setItem(
                fila, 2,
                QTableWidgetItem("Si" if causa["requiere_zona"] else "No"),
            )
            self.lista_causas.setItem(fila, 3, QTableWidgetItem("Activa"))
            por_id[causa["id"]] = causa
        self._causas_por_id = por_id
        if self._causa_seleccionada_id is not None:
            self._cargar_formulario_causa(self._causa_seleccionada_id)

    def _seleccionar_causa(self):
        fila = self.lista_causas.currentRow()
        if fila < 0:
            return
        causa_id = int(self.lista_causas.item(fila, 0).text())
        self._cargar_formulario_causa(causa_id)

    def _cargar_formulario_causa(self, causa_id):
        causa = self._causas_por_id.get(causa_id)
        if causa is None:
            return
        self._causa_seleccionada_id = causa_id
        self.edit_causa_desc.setText(causa["descripcion"])
        self.check_causa_zona.setChecked(bool(causa["requiere_zona"]))

    def _guardar_causa(self):
        if self._causa_seleccionada_id is None:
            self._lbl_causa("Selecciona una causa de la lista.", "error")
            return
        guardar_causa_paro(
            self._causa_seleccionada_id,
            self.edit_causa_desc.text(),
            self.check_causa_zona.isChecked(),
        )
        self._lbl_causa("Cambios guardados.", "exito")
        self._recargar_causas()

    def _eliminar_causa(self):
        fila = self.lista_causas.currentRow()
        if fila < 0:
            self._lbl_causa("Selecciona una causa de la lista.", "error")
            return
        causa_id = int(self.lista_causas.item(fila, 0).text())
        eliminar_causa_paro(causa_id)
        self._causa_seleccionada_id = None
        self._lbl_causa("Causa eliminada (desactivada).", "exito")
        self._recargar_causas()

    # ------------------------------------------------------------------
    # Zonas del croquis: editor WYSIWYG (arrastre + icono/tamanios)
    # ------------------------------------------------------------------

    def _crear_tab_zonas(self):
        layout = QVBoxLayout(self.tab_zonas)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(8)

        titulo = QLabel("Zonas de la Maquina", self.tab_zonas)
        titulo.setObjectName("Title")
        layout.addWidget(titulo, alignment=Qt.AlignHCenter)

        texto = QLabel(
            "Croquis del modal de paro. Haz clic en una zona para editarla; "
            "ARRASTRA su cuerpo para moverla libremente y la esquina "
            "inferior-derecha para cambiar su tamano. La posicion y el tamano "
            "se guardan solos al soltar.",
            self.tab_zonas,
        )
        texto.setWordWrap(True)
        aplicar_estado(texto, "info")
        layout.addWidget(texto, alignment=Qt.AlignHCenter)

        self._editor_zonas = CroquisZonasEditor(
            self.tab_zonas, on_seleccion=self._cargar_formulario_zona
        )
        self._editor_zonas.setMinimumHeight(280)
        layout.addWidget(self._editor_zonas, stretch=1)

        lbl_edicion = QLabel("Editar zona seleccionada:", self.tab_zonas)
        lbl_edicion.setObjectName("HeaderLabel")
        layout.addWidget(lbl_edicion, alignment=Qt.AlignLeft)

        panel = QFrame(self.tab_zonas)
        gp = QGridLayout(panel)
        gp.setContentsMargins(10, 8, 10, 8)
        gp.setSpacing(6)

        gp.addWidget(QLabel("Icono:"), 0, 0)
        ic_fila = QWidget(panel)
        hic = QHBoxLayout(ic_fila)
        hic.setContentsMargins(0, 0, 0, 0)
        hic.setSpacing(6)
        self.lbl_zona_icono_preview = QLabel(panel)
        hic.addWidget(self.lbl_zona_icono_preview)
        self.btn_zona_icono = QPushButton("Seleccionar icono...", panel)
        self.btn_zona_icono.clicked.connect(self._abrir_selector_icono_zona)
        hic.addWidget(self.btn_zona_icono)
        hic.addStretch(1)
        gp.addWidget(ic_fila, 0, 1)

        gp.addWidget(QLabel("Tamano del icono:"), 1, 0)
        ic_tam_fila = QWidget(panel)
        hit = QHBoxLayout(ic_tam_fila)
        hit.setContentsMargins(0, 0, 0, 0)
        hit.setSpacing(6)
        self.slider_zona_icono = QSlider(Qt.Horizontal, panel)
        self.slider_zona_icono.setRange(10, 90)
        self.slider_zona_icono.setValue(50)
        self.slider_zona_icono.setFixedWidth(220)
        self.lbl_zona_icono_pct = QLabel("50%", panel)
        self.slider_zona_icono.valueChanged.connect(
            lambda v: self.lbl_zona_icono_pct.setText(f"{v}%")
        )
        hit.addWidget(self.slider_zona_icono)
        hit.addWidget(self.lbl_zona_icono_pct)
        hit.addStretch(1)
        gp.addWidget(ic_tam_fila, 1, 1)

        self.chk_zona_maquina = CheckBox(
            "Mantener la maquina ENCENDIDA durante el paro de esta zona "
            "(como en mantenimiento)",
            panel,
        )
        self.chk_zona_maquina.setToolTip(
            "Si esta zona se elige como motivo de un paro (y la causa lo "
            "permite), la maquina seguira en marcha con el conteo suspendido "
            "hasta que se cierre el paro."
        )
        gp.addWidget(self.chk_zona_maquina, 2, 0, 1, 2)

        botones = QWidget(panel)
        hb = QHBoxLayout(botones)
        hb.setContentsMargins(0, 0, 0, 0)
        hb.setSpacing(6)
        btn_guardar = QPushButton("Guardar cambios", botones)
        btn_guardar.setObjectName("Success")
        btn_guardar.clicked.connect(self._guardar_zona)
        hb.addWidget(btn_guardar)
        hb.addStretch(1)
        gp.addWidget(botones, 4, 0, 1, 2)

        layout.addWidget(panel)

        self._zona_seleccionada_id = None
        self._zona_icono_actual = ""
        if self._editor_zonas._selected_id is not None:
            self._cargar_formulario_zona(self._editor_zonas._selected_id)

    def _cargar_formulario_zona(self, zona_id):
        if not hasattr(self, "slider_zona_icono"):
            return
        zona = self._editor_zonas.zona_por_id(int(zona_id))
        if zona is None:
            return
        self._zona_seleccionada_id = int(zona_id)
        pct = max(10, min(90, int(round(float(zona["icono_frac"]) * 100))))
        self.slider_zona_icono.setValue(pct)
        self.lbl_zona_icono_pct.setText(f"{pct}%")
        self.chk_zona_maquina.setChecked(bool(zona.get("maquina_encendida")))
        self._set_icono_zona(zona["icono"] or "")

    def _set_icono_zona(self, icono):
        self._zona_icono_actual = icono or ""
        if self._zona_icono_actual:
            try:
                self.lbl_zona_icono_preview.setPixmap(
                    qta.icon(self._zona_icono_actual,
                             color=style.color("accento")).pixmap(22, 22)
                )
            except Exception:  # noqa: BLE001  (icono invalido)
                self.lbl_zona_icono_preview.setPixmap(
                    qta.icon("mdi6.help-circle",
                             color=style.color("accento")).pixmap(22, 22)
                )
        else:
            self.lbl_zona_icono_preview.setPixmap(
                qta.icon("mdi6.image-off",
                         color=style.color("texto_sec")).pixmap(22, 22)
            )

    def _abrir_selector_icono_zona(self):
        modal = SelectorIconoModal(self, self._zona_icono_actual)
        if modal.exec():
            self._set_icono_zona(modal.icono_elegido)

    def _guardar_zona(self):
        if self._zona_seleccionada_id is None:
            self._lbl_causa("Selecciona una zona del croquis.", "error")
            return
        zona = self._editor_zonas.zona_por_id(self._zona_seleccionada_id)
        if zona is None:
            self._lbl_causa("Selecciona una zona del croquis.", "error")
            return
        guardar_zona(
            self._zona_seleccionada_id,
            self._zona_icono_actual,
            zona["x"],
            zona["y"],
            zona["w"],
            zona["h"],
            self.slider_zona_icono.value() / 100.0,
            1 if self.chk_zona_maquina.isChecked() else 0,
        )
        self._lbl_causa("Cambios guardados.", "exito")
        self._editor_zonas._cargar()
        self._cargar_formulario_zona(self._zona_seleccionada_id)

    # ------------------------------------------------------------------
    # Tab Roles
    # ------------------------------------------------------------------

    def _crear_tab_roles(self):
        layout = QVBoxLayout(self.tab_roles)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(8)

        titulo = QLabel("Roles", self.tab_roles)
        titulo.setObjectName("Title")
        layout.addWidget(titulo, alignment=Qt.AlignHCenter)

        fila_nuevo = QWidget(self.tab_roles)
        hn = QHBoxLayout(fila_nuevo)
        hn.setContentsMargins(0, 0, 0, 0)
        hn.setSpacing(6)
        self.entry_rol_nombre = QLineEdit(fila_nuevo)
        self.entry_rol_nombre.setPlaceholderText("Nombre del rol")
        self.entry_rol_nombre.setFixedWidth(220)
        hn.addWidget(self.entry_rol_nombre)
        btn_agregar = QPushButton("Agregar Rol", fila_nuevo)
        btn_agregar.clicked.connect(self._agregar_rol)
        hn.addWidget(btn_agregar)
        layout.addWidget(fila_nuevo, alignment=Qt.AlignHCenter)

        self.lbl_rol_msg = QLabel("", self.tab_roles)
        aplicar_estado(self.lbl_rol_msg, "info")
        layout.addWidget(self.lbl_rol_msg, alignment=Qt.AlignHCenter)

        columnas = QWidget(self.tab_roles)
        hcols = QHBoxLayout(columnas)
        hcols.setContentsMargins(0, 0, 0, 0)
        hcols.setSpacing(12)

        # Columna izquierda: roles.
        col_roles = QWidget(columnas)
        lv_roles = QVBoxLayout(col_roles)
        lv_roles.setContentsMargins(0, 0, 0, 0)
        lv_roles.setSpacing(6)

        lbl_roles_titulo = QLabel("Roles:", col_roles)
        lbl_roles_titulo.setObjectName("HeaderLabel")
        lv_roles.addWidget(lbl_roles_titulo)

        self.lista_roles = QTableWidget(0, 2, col_roles)
        self.lista_roles.setHorizontalHeaderLabels(["ID", "Nombre"])
        self._config_tabla(self.lista_roles)
        for i, ancho in enumerate((60, 220)):
            self.lista_roles.setColumnWidth(i, ancho)
        lv_roles.addWidget(self.lista_roles, stretch=1)

        fila_acciones = QWidget(col_roles)
        hr = QHBoxLayout(fila_acciones)
        hr.setContentsMargins(0, 0, 0, 0)
        hr.setSpacing(6)
        btn_renombrar = QPushButton("Renombrar Rol", fila_acciones)
        btn_renombrar.clicked.connect(self._renombrar_rol)
        hr.addWidget(btn_renombrar)
        btn_eliminar = QPushButton("Eliminar Rol", fila_acciones)
        btn_eliminar.clicked.connect(self._eliminar_rol)
        hr.addWidget(btn_eliminar)
        lv_roles.addWidget(fila_acciones, alignment=Qt.AlignHCenter)

        # Columna derecha: permisos del rol seleccionado.
        col_permisos = QWidget(columnas)
        lv_permisos = QVBoxLayout(col_permisos)
        lv_permisos.setContentsMargins(0, 0, 0, 0)
        lv_permisos.setSpacing(6)

        lbl_permisos_titulo = QLabel(
            "Permisos del rol seleccionado:", col_permisos
        )
        lbl_permisos_titulo.setObjectName("HeaderLabel")
        lv_permisos.addWidget(lbl_permisos_titulo)

        self.lbl_permisos_info = QLabel(
            "Selecciona un rol de la lista.", col_permisos
        )
        self.lbl_permisos_info.setObjectName("EstadoInfo")
        lv_permisos.addWidget(self.lbl_permisos_info)

        self.lista_permisos = CheckboxListWidget(col_permisos)
        self.lista_permisos.setItemDelegate(CheckboxListDelegate(self.lista_permisos))
        lv_permisos.addWidget(self.lista_permisos, stretch=1)

        fila_guardar_permisos = QWidget(col_permisos)
        hp = QHBoxLayout(fila_guardar_permisos)
        hp.setContentsMargins(0, 0, 0, 0)
        hp.setSpacing(6)
        btn_guardar_permisos = QPushButton("Guardar Permisos", fila_guardar_permisos)
        btn_guardar_permisos.clicked.connect(self._guardar_permisos)
        hp.addWidget(btn_guardar_permisos)
        lv_permisos.addWidget(fila_guardar_permisos, alignment=Qt.AlignHCenter)

        self.lbl_permiso_msg = QLabel("", col_permisos)
        aplicar_estado(self.lbl_permiso_msg, "info")
        lv_permisos.addWidget(self.lbl_permiso_msg, alignment=Qt.AlignHCenter)

        hcols.addWidget(col_roles, stretch=1)
        hcols.addWidget(col_permisos, stretch=1)
        layout.addWidget(columnas, stretch=1)

        self._recargar_roles()
        self.lista_roles.itemSelectionChanged.connect(self._recargar_permisos_tab)
        self._recargar_permisos_tab()

    def _agregar_rol(self):
        nombre = self.entry_rol_nombre.text().strip()
        if not nombre:
            self._lbl_rol("Escribe un nombre de rol.", "error")
            return
        if agregar_rol(nombre):
            self.entry_rol_nombre.clear()
            self._lbl_rol("Rol agregado.", "exito")
            self._recargar_roles()
            self._recargar_roles_combo()
        else:
            self._lbl_rol("Nombre vacio.", "error")

    def _renombrar_rol(self):
        fila = self.lista_roles.currentRow()
        if fila < 0:
            self._lbl_rol("Selecciona un rol de la lista.", "error")
            return
        rol_id = int(self.lista_roles.item(fila, 0).text())
        nombre_actual = self.lista_roles.item(fila, 1).text()
        nuevo = preguntar_texto(
            self, "Renombrar rol", "Nuevo nombre del rol:", nombre_actual
        )
        if nuevo is None:
            return
        if renombrar_rol(rol_id, nuevo):
            self._lbl_rol("Rol renombrado.", "exito")
            self._recargar_roles()
            self._recargar_roles_combo()
        else:
            self._lbl_rol("Nombre invalido o ya existe.", "error")

    def _eliminar_rol(self):
        fila = self.lista_roles.currentRow()
        if fila < 0:
            self._lbl_rol("Selecciona un rol de la lista.", "error")
            return
        rol_id = int(self.lista_roles.item(fila, 0).text())
        ok, mensaje = eliminar_rol(rol_id)
        if ok:
            self._lbl_rol("Rol eliminado (desactivado).", "exito")
            self._recargar_roles()
            self._recargar_roles_combo()
        else:
            self._lbl_rol(mensaje, "error")

    def _recargar_roles(self):
        self.lista_roles.setRowCount(0)
        for rol in listar_roles(activas_solo=True):
            fila = self.lista_roles.rowCount()
            self.lista_roles.insertRow(fila)
            valores = (rol["id"], rol["nombre"])
            for col, valor in enumerate(valores):
                self.lista_roles.setItem(fila, col, QTableWidgetItem(str(valor)))
        if self.lista_roles.rowCount() > 0 and self.lista_roles.currentRow() < 0:
            self.lista_roles.selectRow(0)

    def _recargar_permisos_tab(self):
        fila = self.lista_roles.currentRow()
        rol_id = None
        nombre_rol = ""
        if fila >= 0:
            rol_id = int(self.lista_roles.item(fila, 0).text())
            nombre_rol = self.lista_roles.item(fila, 1).text()

        asignados = set(permisos_de_rol(rol_id)) if rol_id is not None else set()

        # Proteccion: si este rol es el unico con acceso a Administracion, el
        # permiso acceso_admin queda fijo y no se muestra (no es editable).
        self._acceso_admin_bloqueado = (
            "acceso_admin" in asignados
            and len(roles_con_permiso("acceso_admin")) == 1
        )

        self.lista_permisos.clear()
        for p in listar_permisos():
            if self._acceso_admin_bloqueado and p["nombre"] == "acceso_admin":
                continue
            item = QListWidgetItem(p["descripcion"], self.lista_permisos)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setData(Qt.UserRole, p["nombre"])
            item.setCheckState(
                Qt.Checked if p["nombre"] in asignados else Qt.Unchecked
            )

        if rol_id is None:
            self.lbl_permisos_info.setText(
                "Selecciona un rol de la lista para ver sus permisos."
            )
            self.lista_permisos.setEnabled(False)
            return

        self.lbl_permisos_info.setText(f"Rol: {nombre_rol}")
        self.lista_permisos.setEnabled(True)

    def _guardar_permisos(self):
        fila = self.lista_roles.currentRow()
        if fila < 0:
            self._lbl_permiso("Selecciona un rol de la lista.", "error")
            return
        rol_id = int(self.lista_roles.item(fila, 0).text())
        marcados = [
            self.lista_permisos.item(i).data(Qt.UserRole)
            for i in range(self.lista_permisos.count())
            if self.lista_permisos.item(i).checkState() == Qt.Checked
        ]
        if self._acceso_admin_bloqueado:
            marcados.append("acceso_admin")
        ok, mensaje = actualizar_permisos_rol(rol_id, marcados)
        if ok:
            self._lbl_permiso("Permisos guardados.", "exito")
            self._recargar_permisos_tab()
        else:
            self._lbl_permiso(mensaje, "error")

    # ------------------------------------------------------------------
    # Tab Sistema (actualizaciones por red)
    # ------------------------------------------------------------------

    def _crear_tab_sistema(self):
        layout = QVBoxLayout(self.tab_sistema)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(8)

        titulo = QLabel("Sistema", self.tab_sistema)
        titulo.setObjectName("Title")
        layout.addWidget(titulo, alignment=Qt.AlignHCenter)

        self.lbl_version = QLabel(
            f"Versión instalada: {actualizaciones.version_instalada()}",
            self.tab_sistema,
        )
        aplicar_estado(self.lbl_version, "info")
        layout.addWidget(self.lbl_version, alignment=Qt.AlignHCenter)

        self.btn_actualizar = QPushButton("Buscar actualización", self.tab_sistema)
        self.btn_actualizar.clicked.connect(self._buscar_actualizacion)
        layout.addWidget(self.btn_actualizar, alignment=Qt.AlignHCenter)

        self.lbl_actualizar = QLabel("", self.tab_sistema)
        aplicar_estado(self.lbl_actualizar, "info")
        layout.addWidget(self.lbl_actualizar, alignment=Qt.AlignHCenter)

        if not config.UPDATE_SOURCE:
            self.btn_actualizar.setVisible(False)
            self.lbl_actualizar.setText(
                "Actualizaciones por red no configuradas (UPDATE_SOURCE vacío)."
            )

        layout.addStretch(1)

    def _lbl_actualizar(self, texto, estado):
        self.lbl_actualizar.setText(texto)
        aplicar_estado(self.lbl_actualizar, estado)

    def _buscar_actualizacion(self):
        if not config.UPDATE_SOURCE:
            return
        self.btn_actualizar.setEnabled(False)
        self._lbl_actualizar("Buscando actualización...", "procesando")
        threading.Thread(target=self._hilo_consultar, daemon=True).start()

    def _hilo_consultar(self):
        try:
            self.cola_update.put(("RESULTADO", actualizaciones.consultar_manifest()))
        except Exception as e:  # noqa: BLE001
            log.error("Consulta de actualizacion fallo: %s", e, exc_info=True)
            self.cola_update.put(("ERROR", str(e)))

    def _hilo_descargar(self):
        try:
            zip_path = actualizaciones.descargar_y_verificar(self._manifest)
            updater = actualizaciones.preparar_updater()
            self.cola_update.put(("LISTO", (zip_path, updater)))
        except Exception as e:  # noqa: BLE001
            log.error("Descarga de actualizacion fallo: %s", e, exc_info=True)
            self.cola_update.put(("ERROR", str(e)))

    def _revisar_cola_update(self):
        try:
            while True:
                ev, data = self.cola_update.get_nowait()
                if ev == "RESULTADO":
                    self._mostrar_resultado(data)
                elif ev == "LISTO":
                    self._aplicar_actualizacion(data)
                elif ev == "ERROR":
                    self._lbl_actualizar(f"No se pudo completar: {data}", "error")
                    self.btn_actualizar.setEnabled(True)
        except queue.Empty:
            pass
        QTimer.singleShot(50, self._revisar_cola_update)

    def _mostrar_resultado(self, manifest):
        self.btn_actualizar.setEnabled(True)
        remota = str((manifest or {}).get("version", "")).strip()
        publicada = str((manifest or {}).get("published_at", "") or "")
        instalada = actualizaciones.version_instalada()

        if not remota or not actualizaciones.hay_version_nueva(manifest):
            self._lbl_actualizar(
                "El sistema está actualizado. "
                f"Instalada: {instalada} · Disponible: {remota or '—'}.",
                "exito",
            )
            return

        self._manifest = manifest
        self._lbl_actualizar(
            f"Actualización disponible: {remota} (publicada el {publicada}).",
            "pendiente",
        )

        if not getattr(sys, "frozen", False):
            caja = QMessageBox(self)
            caja.setWindowTitle("Actualización disponible")
            caja.setText(f"Versión instalada: {instalada}\n"
                         f"Versión disponible: {remota}\n"
                         f"Publicada: {publicada}\n\n"
                         "Estás ejecutando el sistema en modo desarrollo. La "
                         "actualización se aplica en el paquete instalado (.exe).")
            caja.setIcon(QMessageBox.Information)
            caja.addButton("Aceptar", QMessageBox.AcceptRole)
            caja.exec()
            return

        caja = QMessageBox(self)
        caja.setWindowTitle("Actualización disponible")
        caja.setText(
            f"Versión instalada: {instalada}\n"
            f"Versión disponible: {remota}\n"
            f"Publicada: {publicada}\n\n"
            "La aplicación se cerrará y reabrirá automáticamente para aplicar "
            "la actualización."
        )
        btn_aplicar = caja.addButton("Aplicar ahora", QMessageBox.AcceptRole)
        caja.addButton("Cancelar", QMessageBox.RejectRole)
        caja.exec()
        if caja.clickedButton() is btn_aplicar:
            self._confirmar_estado_maquina()

    def _confirmar_estado_maquina(self):
        # OJO: maquina_lista() es una ACCION (arranca/pulsa START), no una
        # consulta de estado. Para saber si la maquina esta en marcha hay que
        # usar maquina_detenida() (consulta pura en ambos HAL).
        en_marcha = False
        try:
            hal = getattr(self.controller, "controlador", None)
            en_marcha = bool(hal and not hal.maquina_detenida())
        except Exception:  # noqa: BLE001 - nunca debe crashear la UI
            log.error("No se pudo consultar el estado de la maquina", exc_info=True)
        sesion = sesion_activa_actual()
        if en_marcha or sesion is not None:
            caja = QMessageBox(self)
            caja.setWindowTitle("Máquina en producción")
            caja.setText(
                "Hay una sesión o la máquina está en marcha. La actualización "
                "cerrará y reabrirá la aplicación; la sesión se recuperará al "
                "abrir (como tras un corte de luz).\n\n¿Continuar de todos "
                "modos?"
            )
            btn_ok = caja.addButton("Sí, continuar", QMessageBox.AcceptRole)
            caja.addButton("Cancelar", QMessageBox.RejectRole)
            caja.exec()
            if caja.clickedButton() is not btn_ok:
                return
        self._descargar_actualizacion()

    def _descargar_actualizacion(self):
        self.btn_actualizar.setEnabled(False)
        self._lbl_actualizar("Descargando actualización...", "procesando")
        threading.Thread(target=self._hilo_descargar, daemon=True).start()

    def _aplicar_actualizacion(self, datos):
        zip_path, updater = datos
        version = str((self._manifest or {}).get("version", ""))
        try:
            actualizaciones.lanzar_updater(updater, zip_path, version, relanzar=True)
        except Exception as e:  # noqa: BLE001
            log.error("No se pudo lanzar el updater: %s", e, exc_info=True)
            self._lbl_actualizar(f"No se pudo lanzar el actualizador: {e}", "error")
            self.btn_actualizar.setEnabled(True)
            return
        self._lbl_actualizar("Aplicando actualización...", "procesando")
        # El updater ya corre en proceso separado: cierra la app para que
        # libere sus archivos (el updater espera a que este proceso salga).
        self.controller._salir()

    # ------------------------------------------------------------------
    # Helpers / cola
    # ------------------------------------------------------------------

    def _lbl(self, texto, estado):
        self.lbl_mensaje.setText(texto)
        aplicar_estado(self.lbl_mensaje, estado)

    def _lbl_huella(self, texto, estado):
        self.lbl_huella.setText(texto)
        aplicar_estado(self.lbl_huella, estado)

    def _lbl_huellas(self, texto, estado):
        self.lbl_huellas_msg.setText(texto)
        aplicar_estado(self.lbl_huellas_msg, estado)

    def _lbl_causa(self, texto, estado):
        self.lbl_causa_msg.setText(texto)
        aplicar_estado(self.lbl_causa_msg, estado)

    def _lbl_rol(self, texto, estado):
        self.lbl_rol_msg.setText(texto)
        aplicar_estado(self.lbl_rol_msg, estado)

    def _lbl_permiso(self, texto, estado):
        self.lbl_permiso_msg.setText(texto)
        aplicar_estado(self.lbl_permiso_msg, estado)

    def _revisar_cola(self):
        try:
            while True:
                ev, data = self.cola.get_nowait()
                if ev == "PROGRESO":
                    texto = data or "Procesando..."
                    if self._modo_captura is None:
                        self._lbl_huella(texto, "procesando")
                    else:
                        self._lbl_huellas(texto, "procesando")
                elif ev == "ENROLL":
                    self._capturando = False
                    self._procesar_enroll(data)
                elif ev == "ERROR":
                    self._capturando = False
                    if self._modo_captura is None:
                        self._lbl_huella(f"Error: {data}", "error")
                    else:
                        self._lbl_huellas(f"Error: {data}", "error")
        except queue.Empty:
            pass
        QTimer.singleShot(50, self._revisar_cola)

    def _procesar_enroll(self, data):
        modo = self._modo_captura
        self._modo_captura = None
        fmd = (data or {}).get("fmd")
        if not fmd:
            status = (data or {}).get("status", "?")
            msg = f"Captura sin plantilla ({status})."
            if modo is None:
                self._lbl_huella(msg, "error")
                if self._modo_cadena:
                    self._encadenar_captura()
            else:
                self._lbl_huellas(msg, "error")
            return
        if modo is None:
            self._agregar_huella_captura(fmd)
        elif modo[0] == "agregar":
            self._agregar_huella_operador(modo[1], fmd)
        else:
            self._reemplazar_huella(modo[1], fmd)

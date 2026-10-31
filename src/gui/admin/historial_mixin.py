"""Pestana Historial Easy (HistorialMixin).

Muestra las ultimas ejecuciones de rutinas Easy con su resultado y las
refresca desde la propia pestana.
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
from .widgets import (
    CheckboxListWidget,
    CheckboxListDelegate,
    CroquisZonasEditor,
    SelectorIconoModal,
    _ModeloIconos,
    _todos_los_iconos,
)

try:
    from src.domain.easy import validar_rutina
    from src.gui.admin.rutinas_easy import repo as repo_easy
    from src.gui.admin.rutinas_easy.editor_pasos import EditorPasosEasy
except Exception:  # noqa: BLE001
    repo_easy = None
    EditorPasosEasy = None
    validar_rutina = None

log = logging.getLogger(__name__)






class HistorialMixin:

    def _crear_tab_historial_easy(self):
        layout = QVBoxLayout(self.tab_historial_easy)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(8)

        titulo = QLabel("Historial de ejecuciones Easy", self.tab_historial_easy)
        titulo.setObjectName("Title")
        layout.addWidget(titulo, alignment=Qt.AlignHCenter)

        self.tabla_hist_easy = QTableWidget(self.tab_historial_easy)
        self.tabla_hist_easy.setColumnCount(7)
        self.tabla_hist_easy.setHorizontalHeaderLabels(
            ["Fecha", "Rutina", "Num. parte", "Folio", "Pasos", "OK", "Error"]
        )
        self._config_tabla(self.tabla_hist_easy)
        layout.addWidget(self.tabla_hist_easy, stretch=1)

        self.btn_hist_refrescar = QPushButton("Refrescar", self.tab_historial_easy)
        layout.addWidget(self.btn_hist_refrescar, alignment=Qt.AlignRight)
        self.btn_hist_refrescar.clicked.connect(self._hist_refrescar)
        self._hist_refrescar()

    def _hist_refrescar(self):
        if repo_easy is None:
            return
        self.tabla_hist_easy.setRowCount(0)
        try:
            filas = repo_easy.listar_ejecuciones(100)
        except Exception:
            filas = []
        for r in filas:
            fila = self.tabla_hist_easy.rowCount()
            self.tabla_hist_easy.insertRow(fila)
            self.tabla_hist_easy.setItem(fila, 0, QTableWidgetItem(str(r.get("inicio") or "")))
            self.tabla_hist_easy.setItem(
                fila, 1, QTableWidgetItem(str(r.get("rutina_nombre") or ""))
            )
            self.tabla_hist_easy.setItem(fila, 2, QTableWidgetItem(str(r.get("num_part") or "")))
            self.tabla_hist_easy.setItem(fila, 3, QTableWidgetItem(str(r.get("folio") or "")))
            self.tabla_hist_easy.setItem(fila, 4, QTableWidgetItem(str(r.get("pasos") or 0)))
            self.tabla_hist_easy.setItem(fila, 5, QTableWidgetItem("Si" if r.get("ok") else "No"))
            self.tabla_hist_easy.setItem(fila, 6, QTableWidgetItem(str(r.get("error") or "")))


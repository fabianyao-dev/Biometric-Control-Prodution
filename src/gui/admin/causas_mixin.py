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






class CausasMixin:

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


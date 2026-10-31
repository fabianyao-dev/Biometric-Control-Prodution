"""Pestana Roles y permisos (RolesMixin).

Alta, renombrado y baja logica de roles, mas la edicion de la matriz de
permisos del rol seleccionado.
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






class RolesMixin:

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


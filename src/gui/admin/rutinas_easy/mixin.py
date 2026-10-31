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
from ..widgets import (
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






class RutinasEasyMixin:

    def _abrir_dialogo_pasos(self, rid, nombre_rutina):
        """Abre el dialogo modal con el EditorPasosEasy para la rutina `rid`.

        Devuelve True si el usuario guardo los pasos, False si cancelo.
        """
        if EditorPasosEasy is None or repo_easy is None:
            QMessageBox.information(
                self, "Editor de pasos",
                "El editor de pasos no esta disponible.",
            )
            return False

        try:
            pasos_actuales = repo_easy.listar_pasos(rid)
        except Exception as exc:
            QMessageBox.warning(
                self, "Error", "No se pudieron cargar los pasos: %s" % (exc,)
            )
            return False

        dlg = QDialog(self)
        dlg.setWindowTitle("Pasos de la rutina: %s" % nombre_rutina)
        dlg.setModal(True)
        dlg.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
        dlg.resize(1200, 800)

        vl = QVBoxLayout(dlg)
        vl.setContentsMargins(12, 12, 12, 12)
        vl.setSpacing(8)

        editor = EditorPasosEasy(dlg)
        editor.cargar(pasos_actuales)
        vl.addWidget(editor, stretch=1)

        barra = QHBoxLayout()
        barra.setSpacing(8)
        btn_validar = QPushButton("Validar", dlg)
        btn_guardar = QPushButton("Guardar pasos", dlg)
        btn_cancelar = QPushButton("Cancelar", dlg)
        barra.addWidget(btn_validar)
        barra.addStretch(1)
        barra.addWidget(btn_cancelar)
        barra.addWidget(btn_guardar)
        vl.addLayout(barra)

        def _validar():
            if validar_rutina is None:
                QMessageBox.information(dlg, "Validacion", "Validador no disponible.")
                return
            try:
                validar_rutina(editor.pasos_validables())
                QMessageBox.information(dlg, "Validacion", "Todos los pasos son validos.")
            except Exception as exc:
                QMessageBox.warning(dlg, "Validacion", "Error: %s" % (exc,))

        def _guardar():
            try:
                pasos = editor.pasos()
                if validar_rutina is not None:
                    validar_rutina(editor.pasos_validables())
            except Exception as exc:
                QMessageBox.warning(dlg, "Guardar", "Pasos invalidos: %s" % (exc,))
                return
            try:
                repo_easy.reemplazar_pasos(rid, pasos)
            except Exception as exc:
                QMessageBox.warning(dlg, "Guardar", "Error al guardar: %s" % (exc,))
                return
            dlg.accept()

        btn_validar.clicked.connect(_validar)
        btn_guardar.clicked.connect(_guardar)
        btn_cancelar.clicked.connect(dlg.reject)

        from PySide6.QtCore import QPoint, QRect
        screen = dlg.screen().availableGeometry()
        parent_win = self.window()
        if parent_win is not None and parent_win.isVisible():
            area = QRect(parent_win.mapToGlobal(QPoint(0, 0)), parent_win.size()).intersected(screen)
        else:
            area = screen
        
        ancho = min(1280, area.width() - 40)
        alto = min(900, area.height() - 40)
        dlg.resize(ancho, alto)
        
        x = area.x() + (area.width() - ancho) // 2
        y = area.y() + (area.height() - alto) // 2
        dlg.move(x, y)
        
        return dlg.exec() == QDialog.Accepted

    def _crear_tab_rutinas_easy(self):
        layout = QVBoxLayout(self.tab_rutinas_easy)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(8)

        titulo = QLabel("Rutinas Easy (control remoto de estacion)", self.tab_rutinas_easy)
        titulo.setObjectName("Title")
        layout.addWidget(titulo, alignment=Qt.AlignHCenter)

        ayuda = QLabel(
            "Elige una rutina, ajusta sus datos basicos y pulsa "
            "\u201cGuardar datos\u201d. Para agregar o modificar los pasos usa "
            "\u201cEditar pasos\u2026\u201d.",
            self.tab_rutinas_easy,
        )
        ayuda.setObjectName("EstadoInfo")
        ayuda.setWordWrap(True)
        ayuda.setAlignment(Qt.AlignHCenter)
        layout.addWidget(ayuda)

        # --- Fila principal: lista de rutinas + datos de la seleccionada ---
        contenido = QWidget(self.tab_rutinas_easy)
        fila_principal = QHBoxLayout(contenido)
        fila_principal.setContentsMargins(0, 0, 0, 0)
        fila_principal.setSpacing(12)
        layout.addWidget(contenido, stretch=1)

        # -- columna izquierda: lista --
        caja_lista = QGroupBox("Rutinas guardadas", contenido)
        vl = QVBoxLayout(caja_lista)
        vl.setContentsMargins(8, 8, 8, 8)
        vl.setSpacing(8)
        self.tabla_rutinas_easy = QTableWidget(caja_lista)
        self.tabla_rutinas_easy.setColumnCount(2)
        self.tabla_rutinas_easy.setHorizontalHeaderLabels(["Nombre", "Activa"])
        self._config_tabla(self.tabla_rutinas_easy)
        self.tabla_rutinas_easy.setColumnWidth(0, 180)
        self.tabla_rutinas_easy.setMinimumWidth(220)
        vl.addWidget(self.tabla_rutinas_easy, stretch=1)
        self.lbl_re_vacio = QLabel(
            "Todavia no hay rutinas. Pulsa \u201cNueva\u201d para crear la "
            "primera.",
            caja_lista,
        )
        self.lbl_re_vacio.setObjectName("EstadoInfo")
        self.lbl_re_vacio.setWordWrap(True)
        self.lbl_re_vacio.setVisible(False)
        vl.addWidget(self.lbl_re_vacio)
        fila_btns = QHBoxLayout()
        self.btn_re_nueva = QPushButton("Nueva", caja_lista)
        self.btn_re_duplicar = QPushButton("Duplicar", caja_lista)
        self.btn_re_eliminar = QPushButton("Desactivar", caja_lista)
        for b in (self.btn_re_nueva, self.btn_re_duplicar, self.btn_re_eliminar):
            fila_btns.addWidget(b)
        fila_btns.addStretch(1)
        vl.addLayout(fila_btns)
        fila_principal.addWidget(caja_lista, stretch=2)

        # -- columna derecha: datos basicos de la rutina --
        caja_datos = QGroupBox("Datos de la rutina", contenido)
        self._caja_datos = caja_datos
        vd = QVBoxLayout(caja_datos)
        vd.setContentsMargins(12, 12, 12, 12)
        vd.setSpacing(10)
        form = QFormLayout()
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.re_nombre = QLineEdit(caja_datos)
        self.re_nombre.setPlaceholderText("Nombre unico (sin espacios)")
        self.re_descripcion = QLineEdit(caja_datos)
        self.re_descripcion.setPlaceholderText(
            "Para que sirve esta rutina (opcional)"
        )
        self.re_timeout = QSpinBox(caja_datos)
        self.re_timeout.setRange(1, 600)
        self.re_timeout.setValue(30)
        self.re_timeout.setSuffix(" s")
        self.re_activo = CheckBox("Activa", caja_datos)
        self.re_activo.setToolTip(
            "Solo las rutinas activas se envian a la estacion."
        )
        form.addRow("Nombre:", self.re_nombre)
        form.addRow("Descripcion:", self.re_descripcion)
        form.addRow("Timeout:", self.re_timeout)
        form.addRow("", self.re_activo)
        vd.addLayout(form)

        # boton de edicion de pasos dentro del grupo de datos
        self.btn_re_editar_pasos = QPushButton(
            "Editar pasos de la rutina\u2026", caja_datos
        )
        self.btn_re_editar_pasos.setToolTip(
            "Abre el editor de pasos para la rutina seleccionada."
        )
        vd.addWidget(self.btn_re_editar_pasos)
        vd.addStretch(1)
        fila_principal.addWidget(caja_datos, stretch=3)

        # --- Barra de acciones: aplica a la rutina seleccionada ------------
        barra = QHBoxLayout()
        barra.setSpacing(8)
        self.btn_re_guardar = QPushButton("Guardar datos",
                                          self.tab_rutinas_easy)
        self.btn_re_guardar.setToolTip(
            "Guarda el nombre, descripcion, timeout y estado activo."
        )
        self.btn_re_probar = QPushButton("Probar en estacion",
                                         self.tab_rutinas_easy)
        self.btn_re_probar.setToolTip(
            "Envia la rutina a la estacion (requiere EASY_HOST)."
        )
        barra.addStretch(1)
        barra.addWidget(self.btn_re_guardar)
        barra.addWidget(self.btn_re_probar)
        layout.addLayout(barra)

        self.tabla_rutinas_easy.itemSelectionChanged.connect(
            self._re_cargar_seleccion
        )
        self.btn_re_nueva.clicked.connect(self._re_nueva)
        self.btn_re_duplicar.clicked.connect(self._re_duplicar)
        self.btn_re_eliminar.clicked.connect(self._re_desactivar)
        self.btn_re_editar_pasos.clicked.connect(self._re_editar_pasos)
        self.btn_re_guardar.clicked.connect(self._re_guardar)
        self.btn_re_probar.clicked.connect(self._re_probar)

        self._re_refrescar_lista()

    def _re_habilitar_editor(self, activo):
        """Bloquea los datos cuando no hay rutina seleccionada."""
        self._caja_datos.setEnabled(activo)
        if activo:
            return
        self.re_nombre.clear()
        self.re_descripcion.clear()
        self.re_timeout.setValue(30)
        self.re_activo.setChecked(False)

    def _re_refrescar_lista(self, seleccionar=None):
        if repo_easy is None:
            return
        if seleccionar is None:
            seleccionar = self._re_seleccionada_id()
        try:
            rutinas = repo_easy.listar_rutinas()
        except Exception:
            rutinas = []
        self.tabla_rutinas_easy.blockSignals(True)
        self.tabla_rutinas_easy.setRowCount(0)
        for r in rutinas:
            fila = self.tabla_rutinas_easy.rowCount()
            self.tabla_rutinas_easy.insertRow(fila)
            self.tabla_rutinas_easy.setItem(fila, 0, QTableWidgetItem(r["nombre"]))
            self.tabla_rutinas_easy.setItem(
                fila, 1, QTableWidgetItem("Si" if r.get("activo") else "No")
            )
            self.tabla_rutinas_easy.item(fila, 0).setData(Qt.UserRole, r["id"])
        self.tabla_rutinas_easy.blockSignals(False)

        self.lbl_re_vacio.setVisible(not rutinas)
        self.btn_re_duplicar.setEnabled(bool(rutinas))
        self.btn_re_eliminar.setEnabled(bool(rutinas))
        if not rutinas:
            self._re_habilitar_editor(False)
            return
        fila = 0
        if seleccionar is not None:
            for i in range(self.tabla_rutinas_easy.rowCount()):
                item = self.tabla_rutinas_easy.item(i, 0)
                if item is not None and item.data(Qt.UserRole) == seleccionar:
                    fila = i
                    break
        self._re_habilitar_editor(True)
        self.tabla_rutinas_easy.setCurrentCell(fila, 0)
        self._re_cargar_seleccion()

    def _re_seleccionada_id(self):
        fila = self.tabla_rutinas_easy.currentRow()
        if fila < 0:
            return None
        item = self.tabla_rutinas_easy.item(fila, 0)
        if item is None:
            return None
        return item.data(Qt.UserRole)

    def _re_cargar_seleccion(self):
        rid = self._re_seleccionada_id()
        if rid is None or repo_easy is None:
            return
        try:
            rutina = repo_easy.obtener_rutina(rid)
        except Exception:
            return
        if not rutina:
            return
        self.re_nombre.setText(rutina.get("nombre") or "")
        self.re_descripcion.setText(rutina.get("descripcion") or "")
        self.re_timeout.setValue(int(rutina.get("timeout_s") or 30))
        self.re_activo.setChecked(bool(rutina.get("activo")))

    def _re_nueva(self):
        if repo_easy is None:
            return
        existentes = {r["nombre"] for r in repo_easy.listar_rutinas()}
        nombre = "nueva_rutina"
        numero = 2
        while nombre in existentes:
            nombre = "nueva_rutina_%d" % numero
            numero += 1
        rid = repo_easy.crear_rutina(nombre, "", 0, 0, 30)
        self._re_refrescar_lista(rid)

    def _re_duplicar(self):
        if repo_easy is None:
            return
        rid = self._re_seleccionada_id()
        if rid is None:
            return
        rutina = repo_easy.obtener_rutina(rid)
        pasos = repo_easy.listar_pasos(rid)
        if not rutina:
            return
        existentes = {r["nombre"] for r in repo_easy.listar_rutinas()}
        base = (rutina.get("nombre") or "") + "_copia"
        nuevo_nombre = base
        numero = 2
        while nuevo_nombre in existentes:
            nuevo_nombre = "%s_%d" % (base, numero)
            numero += 1
        nuevo_id = repo_easy.crear_rutina(
            nuevo_nombre, rutina.get("descripcion") or "", 0,
            (rutina.get("orden") or 0) + 1,
            rutina.get("timeout_s") or 30,
        )
        repo_easy.reemplazar_pasos(nuevo_id, pasos)
        self._re_refrescar_lista(nuevo_id)

    def _re_desactivar(self):
        rid = self._re_seleccionada_id()
        if rid is None or repo_easy is None:
            return
        resp = QMessageBox.question(
            self, "Desactivar rutina",
            "La rutina dejara de enviarse a la estacion. Continuar?",
        )
        if resp != QMessageBox.Yes:
            return
        repo_easy.desactivar_rutina(rid)
        self._re_refrescar_lista(rid)

    def _re_editar_pasos(self):
        """Abre el dialogo de edicion de pasos para la rutina seleccionada."""
        rid = self._re_seleccionada_id()
        if rid is None:
            return
        nombre = self.re_nombre.text().strip() or "rutina"
        self._abrir_dialogo_pasos(rid, nombre)

    def _re_guardar(self):
        """Guarda solo los datos basicos (nombre, descripcion, timeout, activo)."""
        if repo_easy is None:
            return
        rid = self._re_seleccionada_id()
        nombre = self.re_nombre.text().strip()
        if not nombre:
            QMessageBox.warning(self, "Guardar", "El nombre es obligatorio.")
            return
        datos = {
            "nombre": nombre,
            "descripcion": self.re_descripcion.text().strip(),
            "activo": 1 if self.re_activo.isChecked() else 0,
            "timeout_s": self.re_timeout.value(),
        }
        try:
            if rid is None:
                rid = repo_easy.crear_rutina(
                    nombre, datos["descripcion"],
                    datos["activo"], 0, datos["timeout_s"],
                )
            else:
                repo_easy.actualizar_rutina(rid, **datos)
        except Exception as exc:
            QMessageBox.warning(self, "Guardar", "Error al guardar: %s" % (exc,))
            return
        QMessageBox.information(self, "Guardar", "Datos guardados.")
        self._re_refrescar_lista(rid)

    def _re_probar(self):
        QMessageBox.information(
            self, "Probar",
            "El envio de prueba se realiza al cargar un trabajo "
            "(EASY_HOST debe estar configurado).",
        )


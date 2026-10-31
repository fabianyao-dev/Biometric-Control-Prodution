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






class ZonasMixin:

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


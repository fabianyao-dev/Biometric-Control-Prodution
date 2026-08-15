"""
sessions_view.py - Consulta de sesiones de produccion y sus paros.

Lista todas las sesiones registradas y, al seleccionar una, muestra los paros
de esa sesion (motivo, inicio, fin) para el historial del turno.
"""

import logging
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.database import listar_sesiones, obtener_paros_de_sesion

log = logging.getLogger(__name__)


class SessionsView(QWidget):
    def __init__(self, parent, controller):
        super().__init__(parent)
        self.controller = controller
        self._crear_interfaz()
        self._recargar_sesiones()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _crear_interfaz(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(8)

        titulo = QLabel("Historial de Sesiones", self)
        titulo.setObjectName("Title")
        layout.addWidget(titulo, alignment=Qt.AlignHCenter)

        subtitulo = QLabel("Selecciona una sesion para ver sus paros:", self)
        subtitulo.setObjectName("EstadoInfo")
        layout.addWidget(subtitulo, alignment=Qt.AlignHCenter)

        self.tree_sesiones = QTableWidget(0, 7, self)
        self.tree_sesiones.setHorizontalHeaderLabels(
            ["ID", "Operador", "Inicio", "Cortes", "Estado", "Min", "Paros"]
        )
        self._config_tabla(self.tree_sesiones)
        for i, ancho in enumerate((50, 140, 130, 70, 90, 60, 60)):
            self.tree_sesiones.setColumnWidth(i, ancho)
        self.tree_sesiones.itemSelectionChanged.connect(self._on_select_sesion)
        layout.addWidget(self.tree_sesiones, stretch=3)

        lbl_paros = QLabel("Paros de la sesion:", self)
        lbl_paros.setObjectName("HeaderLabel")
        layout.addWidget(lbl_paros, alignment=Qt.AlignHCenter)

        self.tree_paros = QTableWidget(0, 3, self)
        self.tree_paros.setHorizontalHeaderLabels(["Causa", "Inicio", "Fin"])
        self._config_tabla(self.tree_paros)
        for i, ancho in enumerate((220, 130, 130)):
            self.tree_paros.setColumnWidth(i, ancho)
        layout.addWidget(self.tree_paros, stretch=2)

        btn_actualizar = QPushButton("Actualizar", self)
        btn_actualizar.clicked.connect(self._recargar_sesiones)
        layout.addWidget(btn_actualizar, alignment=Qt.AlignHCenter)

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
    # Datos
    # ------------------------------------------------------------------

    def _recargar_sesiones(self):
        self.tree_sesiones.setRowCount(0)
        for s in listar_sesiones():
            fila = self.tree_sesiones.rowCount()
            self.tree_sesiones.insertRow(fila)
            valores = (
                s["id"], s["nombre"], s["fecha_inicio"], s["total_cortes"],
                s["estado"], s["minutos"], s["num_paros"],
            )
            for col, valor in enumerate(valores):
                self.tree_sesiones.setItem(fila, col, QTableWidgetItem(str(valor)))
        self._limpiar_paros()

    def _on_select_sesion(self):
        fila = self.tree_sesiones.currentRow()
        if fila < 0:
            return
        sesion_id = int(self.tree_sesiones.item(fila, 0).text())
        self._recargar_paros(sesion_id)

    def _recargar_paros(self, sesion_id):
        self.tree_paros.setRowCount(0)
        for p in obtener_paros_de_sesion(sesion_id):
            fila = self.tree_paros.rowCount()
            self.tree_paros.insertRow(fila)
            causa = p["descripcion"] if p["descripcion"] else "(sin causa registrada)"
            self.tree_paros.setItem(fila, 0, QTableWidgetItem(causa))
            self.tree_paros.setItem(fila, 1, QTableWidgetItem(p["inicio_paro"]))
            self.tree_paros.setItem(fila, 2, QTableWidgetItem(p["fin_paro"] or "En curso"))

    def _limpiar_paros(self):
        self.tree_paros.setRowCount(0)

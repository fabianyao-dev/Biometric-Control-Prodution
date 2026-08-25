"""
sessions_view.py - Consulta de sesiones de produccion, paros y trabajos.

Lista todas las sesiones registradas (con su hora de fin) y, al seleccionar
una, muestra lado a lado los PAROS (causa, inicio, fin, quien autorizo) y los
TRABAJOS (folio, parte, avance) de esa sesion. Columnas responsive: cada una
se ajusta a su contenido salvo las de texto libre (Operador/Causa/Parte),
que se estiran.
"""

import logging
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.database import (
    listar_sesiones,
    listar_trabajos_de_sesion,
    obtener_paros_de_sesion,
)

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

        self.tree_sesiones = QTableWidget(0, 8, self)
        self.tree_sesiones.setHorizontalHeaderLabels(
            ["ID", "Operador", "Inicio", "Fin", "Cortes", "Estado", "Min",
             "Paros"]
        )
        # Operador se estira; el resto se ajusta a su contenido (sin anchos
        # fijos: columnas de un digito no deben ocupar el mismo espacio).
        self._config_tabla(self.tree_sesiones, col_stretch=(1,))
        self.tree_sesiones.itemSelectionChanged.connect(self._on_select_sesion)
        layout.addWidget(self.tree_sesiones, stretch=3)

        # Paros (izquierda) y trabajos (derecha), lado a lado.
        fila_detalle = QHBoxLayout()
        fila_detalle.setSpacing(12)

        col_paros = QVBoxLayout()
        col_paros.setSpacing(4)
        self.lbl_paros = QLabel("Paros de la sesion:", self)
        self.lbl_paros.setObjectName("HeaderLabel")
        col_paros.addWidget(self.lbl_paros)
        self.tree_paros = QTableWidget(0, 4, self)
        self.tree_paros.setHorizontalHeaderLabels(
            ["Causa", "Inicio", "Fin", "Autorizó"]
        )
        # La causa se estira; inicio/fin/autorizador al contenido.
        self._config_tabla(self.tree_paros, col_stretch=(0,))
        col_paros.addWidget(self.tree_paros, stretch=2)
        fila_detalle.addLayout(col_paros, stretch=1)

        col_trabajos = QVBoxLayout()
        col_trabajos.setSpacing(4)
        self.lbl_trabajos = QLabel("Trabajos de la sesion:", self)
        self.lbl_trabajos.setObjectName("HeaderLabel")
        col_trabajos.addWidget(self.lbl_trabajos)
        self.tree_trabajos = QTableWidget(0, 7, self)
        self.tree_trabajos.setHorizontalHeaderLabels(
            ["Folio", "Num Part", "Cantidad", "Cortados (sesion)",
             "Inicio", "Fin", "Estado"]
        )
        # Num Part se estira; el resto al contenido.
        self._config_tabla(self.tree_trabajos, col_stretch=(1,))
        col_trabajos.addWidget(self.tree_trabajos, stretch=2)
        fila_detalle.addLayout(col_trabajos, stretch=1)

        layout.addLayout(fila_detalle, stretch=2)

        btn_actualizar = QPushButton("Actualizar", self)
        btn_actualizar.clicked.connect(self._recargar_sesiones)
        layout.addWidget(btn_actualizar, alignment=Qt.AlignHCenter)

    @staticmethod
    def _config_tabla(tabla, col_stretch=()):
        tabla.setSelectionBehavior(QAbstractItemView.SelectRows)
        tabla.setSelectionMode(QAbstractItemView.SingleSelection)
        tabla.setEditTriggers(QAbstractItemView.NoEditTriggers)
        tabla.verticalHeader().setVisible(False)
        tabla.setAlternatingRowColors(True)
        tabla.setShowGrid(False)
        header = tabla.horizontalHeader()
        header.setStretchLastSection(False)
        for col in range(tabla.columnCount()):
            modo = (
                QHeaderView.Stretch if col in col_stretch
                else QHeaderView.ResizeToContents
            )
            header.setSectionResizeMode(col, modo)
        header.setSectionsClickable(True)

    # ------------------------------------------------------------------
    # Datos
    # ------------------------------------------------------------------

    def _recargar_sesiones(self):
        self.tree_sesiones.setRowCount(0)
        for s in listar_sesiones():
            fila = self.tree_sesiones.rowCount()
            self.tree_sesiones.insertRow(fila)
            valores = (
                s["id"], s["nombre"], s["fecha_inicio"],
                s["fecha_fin"] or "En curso", s["total_cortes"],
                s["estado"], s["minutos"], s["num_paros"],
            )
            for col, valor in enumerate(valores):
                self.tree_sesiones.setItem(fila, col, QTableWidgetItem(str(valor)))
        self.lbl_paros.setText("Paros de la sesion:")
        self._limpiar_paros()
        self.lbl_trabajos.setText("Trabajos de la sesion:")
        self.tree_trabajos.setRowCount(0)

    def _on_select_sesion(self):
        fila = self.tree_sesiones.currentRow()
        if fila < 0:
            return
        sesion_id = int(self.tree_sesiones.item(fila, 0).text())
        operador = self.tree_sesiones.item(fila, 1).text()
        # De quien era la sesion, junto al detalle de paros.
        self.lbl_paros.setText(
            f"Paros de la sesion #{sesion_id} (operador: {operador}):"
        )
        self._recargar_paros(sesion_id)
        self.lbl_trabajos.setText(f"Trabajos de la sesion #{sesion_id}:")
        self._recargar_trabajos(sesion_id)

    def _recargar_trabajos(self, sesion_id):
        """Trabajos de la sesion POR SEGMENTO (folio x sesion): 'Cortados
        (sesion)' es lo cortado en ESTA sesion para ese folio."""
        self.tree_trabajos.setRowCount(0)
        for t in listar_trabajos_de_sesion(sesion_id):
            fila = self.tree_trabajos.rowCount()
            self.tree_trabajos.insertRow(fila)
            valores = (
                t["folio"], t["num_part"], t["cantidad_total"],
                t["cantidad_sesion"],
                t["fecha_inicio"],
                t["fecha_fin"] or ("En curso" if t["estado"] == "Abierto"
                                   else "Sin registro"),
                t["estado"],
            )
            for col, valor in enumerate(valores):
                self.tree_trabajos.setItem(
                    fila, col, QTableWidgetItem(str(valor))
                )

    def _recargar_paros(self, sesion_id):
        self.tree_paros.setRowCount(0)
        for p in obtener_paros_de_sesion(sesion_id):
            fila = self.tree_paros.rowCount()
            self.tree_paros.insertRow(fila)
            causa = p["descripcion"] if p["descripcion"] else "(sin causa registrada)"
            en_curso = not p["fin_paro"]
            autorizador = p["autorizador"] or (
                "Sin autorizar" if en_curso else "(sin registro)"
            )
            self.tree_paros.setItem(fila, 0, QTableWidgetItem(causa))
            self.tree_paros.setItem(fila, 1, QTableWidgetItem(p["inicio_paro"]))
            self.tree_paros.setItem(
                fila, 2, QTableWidgetItem("En curso" if en_curso else p["fin_paro"])
            )
            self.tree_paros.setItem(fila, 3, QTableWidgetItem(autorizador))

    def _limpiar_paros(self):
        self.tree_paros.setRowCount(0)

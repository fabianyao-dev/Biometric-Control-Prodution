"""
selector_causas.py - Widget reutilizable para elegir una causa de paro.

Muestra una cuadricula con las causas activas mas usadas (por numero de
paros registrados) y un boton "Buscar caso" que abre un modal con todas las
causas activas y un filtro por texto. Se usa en el modal de autorizacion de
paros (HuellaModal).
"""

import logging
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src import config
from src.database import listar_causas_frecuentes, listar_causas_paro
from src.gui.util import centrar_y_ajustar

log = logging.getLogger(__name__)


class SelectorCausas(QFrame):
    """Cuadricula de causas frecuentes + boton de busqueda."""

    def __init__(self, master, on_seleccion=None,
                 limite=config.CAUSAS_FRECUENTES_LIMITE,
                 columnas=config.CAUSAS_GRID_COLUMNAS):
        super().__init__(master)
        self.on_seleccion = on_seleccion
        self.columnas = max(1, columnas)

        self.seleccion_id = None
        self.seleccion_descripcion = None
        self._botones = {}

        self._crear_interfaz()
        self._cargar_frecuentes(limite)

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _crear_interfaz(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        lbl = QLabel("Causas mas usadas:", self)
        lbl.setObjectName("EstadoInfo")
        layout.addWidget(lbl, alignment=Qt.AlignLeft)

        self._contenedor = QFrame(self)
        self._contenedor.setObjectName("CausasGrid")
        self._grid = QGridLayout(self._contenedor)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setSpacing(6)
        layout.addWidget(self._contenedor)

        self.btn_buscar = QPushButton("Buscar caso", self)
        self.btn_buscar.clicked.connect(self._buscar)
        layout.addWidget(self.btn_buscar)

        self.lbl_vacio = QLabel("", self)
        self.lbl_vacio.setObjectName("EstadoInfo")

    def _cargar_frecuentes(self, limite):
        causas = listar_causas_frecuentes(limite)
        for i, causa in enumerate(causas):
            fila, col = divmod(i, self.columnas)
            boton = self._crear_boton(causa["id"], causa["descripcion"])
            self._grid.addWidget(boton, fila, col)
            self._grid.setColumnStretch(col, 1)

        # SIN preseleccion: el operador debe elegir la causa explicitamente
        # (seleccion_id queda en None hasta que pulse un boton o busque).
        if not causas:
            self.lbl_vacio.setText("Aun sin causas frecuentes; usa 'Buscar caso'.")
            self.layout().addWidget(self.lbl_vacio)

    def _crear_boton(self, causa_id, descripcion):
        boton = QPushButton(descripcion, self._contenedor)
        boton.setObjectName("Causa")
        boton.setMinimumHeight(40)
        boton.clicked.connect(
            lambda checked=False, c=causa_id, d=descripcion: self._seleccionar(c, d)
        )
        self._botones[causa_id] = (boton, descripcion)
        return boton

    # ------------------------------------------------------------------
    # Seleccion
    # ------------------------------------------------------------------

    def _seleccionar(self, causa_id, descripcion):
        """Marca la causa elegida (boton en verde) y notifica al oyente."""
        self.seleccion_id = causa_id
        self.seleccion_descripcion = descripcion
        for i, (boton, _desc) in self._botones.items():
            boton.setObjectName("CausaSel" if i == causa_id else "Causa")
            boton.style().unpolish(boton)
            boton.style().polish(boton)
        if self.on_seleccion:
            self.on_seleccion(causa_id, descripcion)

    def _buscar(self):
        BuscarCausaModal(self, on_seleccion=self._seleccionar).exec()


class BuscarCausaModal(QDialog):
    """Modal de busqueda de causa sobre todas las causas activas."""

    def __init__(self, parent, on_seleccion):
        super().__init__(parent)
        self.on_seleccion = on_seleccion
        self._todas = listar_causas_paro(activas_solo=True)

        self.setWindowTitle("Buscar causa de paro")
        self.setModal(True)
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)

        self._crear_interfaz()
        self._filtrar()
        centrar_y_ajustar(self, parent)
        self.entry.setFocus()

    def _crear_interfaz(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(8)

        lbl = QLabel("Escribe para filtrar o selecciona una causa:", self)
        lbl.setObjectName("EstadoInfo")
        layout.addWidget(lbl)

        self.entry = QLineEdit(self)
        self.entry.setPlaceholderText("Filtrar...")
        self.entry.textChanged.connect(self._filtrar)
        self.entry.returnPressed.connect(self._aceptar)
        layout.addWidget(self.entry)

        self.lista = QTableWidget(0, 2, self)
        self.lista.setHorizontalHeaderLabels(["ID", "Descripcion"])
        self.lista.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.lista.setSelectionMode(QAbstractItemView.SingleSelection)
        self.lista.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.lista.verticalHeader().setVisible(False)
        self.lista.setShowGrid(False)
        self.lista.setColumnWidth(0, 50)
        self.lista.horizontalHeader().setStretchLastSection(True)
        self.lista.cellDoubleClicked.connect(lambda r, c: self._aceptar())
        self.lista.cellActivated.connect(lambda r, c: self._aceptar())
        layout.addWidget(self.lista, stretch=1)

        barra = QWidget(self)
        h = QHBoxLayout(barra)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)
        btn_aceptar = QPushButton("Seleccionar", barra)
        btn_aceptar.setObjectName("Success")
        btn_aceptar.clicked.connect(self._aceptar)
        h.addWidget(btn_aceptar)
        btn_cancelar = QPushButton("Cancelar", barra)
        btn_cancelar.clicked.connect(self.reject)
        h.addWidget(btn_cancelar)
        layout.addWidget(barra)

    # ------------------------------------------------------------------
    # Logica
    # ------------------------------------------------------------------

    def _filtrar(self, texto=""):
        texto = texto.strip().lower()
        self.lista.setRowCount(0)
        for causa in self._todas:
            if texto in causa["descripcion"].lower():
                fila = self.lista.rowCount()
                self.lista.insertRow(fila)
                self.lista.setItem(fila, 0, QTableWidgetItem(str(causa["id"])))
                self.lista.setItem(fila, 1, QTableWidgetItem(causa["descripcion"]))

    def _aceptar(self):
        fila = self.lista.currentRow()
        if fila < 0:
            return
        causa_id = int(self.lista.item(fila, 0).text())
        descripcion = self.lista.item(fila, 1).text()
        self.on_seleccion(causa_id, descripcion)
        self.accept()

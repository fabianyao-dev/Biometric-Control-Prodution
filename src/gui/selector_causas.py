"""
selector_causas.py - Widget combinado zona + causa para el modal de paro (punto 7).

Al registrar/autorizar un paro, el operador ve:
  - a la IZQUIERDA el croquis de zonas de la maquina (botones seleccionables
    SIEMPRE: puede elegir cualquier zona con o sin causa, y con causa que no
    requiera zona; la zona SOLO se envia al confirmar si la causa la
    requiere). El ICONO, la POSICION y el TAMANO de cada boton-zona son
    editables en Administracion -> Zonas (posicion/tamano libres por arrastre).
  - a la DERECHA la lista de causas de UNA sola columna, fijas (solo
    descripcion + regla `requiere_zona`), con un filtro BUSCAR.

El boton Confirmar vive en el HuellaModal (abajo), que valida causa + zona
antes de pedir la huella que autoriza el paro.
"""

import logging
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from src.database import listar_causas_paro
from src.gui.croquis_zonas import ZonaCanvas

log = logging.getLogger(__name__)


class SelectorZonas(QFrame):
    """Croquis de zonas de la maquina, con posicion y tamano libres.

    Las zonas se muestran sobre un lienzo proporcional (ZonaCanvas). Su icono,
    tamano y posicion se configuran en Administracion -> Zonas.
    """

    def __init__(self, master, on_seleccion=None, preseleccionar=True):
        super().__init__(master)
        self.on_seleccion = on_seleccion
        self.seleccion_zona_id = None
        self.seleccion_zona_nombre = None
        self._canvas = None
        self._preseleccionar = bool(preseleccionar)
        self._crear_interfaz()

    def _crear_interfaz(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        lbl = QLabel("Zonas de la maquina:", self)
        lbl.setObjectName("EstadoInfo")
        self.lbl_zona = QLabel("Zona: ninguna", self)
        self.lbl_zona.setObjectName("EstadoInfo")
        layout.addWidget(lbl, alignment=Qt.AlignLeft)
        self._canvas = ZonaCanvas(
            self,
            editable=False,
            on_seleccion=self._seleccionar_zona_id,
            preseleccionar=self._preseleccionar,
        )
        self._canvas.setMinimumHeight(150)
        layout.addWidget(self._canvas, stretch=1)
        layout.addWidget(self.lbl_zona, alignment=Qt.AlignLeft)

    def _cargar(self):
        self._canvas.cargar()

    def _seleccionar_zona_id(self, zona_id):
        if self._canvas is None:
            return
        zona = self._canvas.zona_por_id(zona_id)
        if not zona:
            return
        self.seleccion_zona_id = zona["id"]
        self.seleccion_zona_nombre = zona["nombre"]
        self.lbl_zona.setText(f"Zona: {zona['nombre']}")
        if self.on_seleccion:
            self.on_seleccion()


class SelectorCausaZona(QFrame):
    """Combinacion: croquis de zonas (izq) + lista de causas con BUSCAR (der).

    Expone `seleccion_id`/`seleccion_descripcion` (causa) y
    `seleccion_zona_id`/`seleccion_zona_nombre` (zona). `puede_confirmar()`
    es True cuando hay causa y, si esta requiere zona, zona elegida.
    """

    def __init__(self, master, on_seleccion=None, on_cambio=None):
        super().__init__(master)
        self.on_seleccion = on_seleccion
        self.on_cambio = on_cambio
        self.seleccion_id = None
        self.seleccion_descripcion = None
        self._causa_req_zona = False
        self._botones_causa = {}
        self._causas = []
        self._crear_interfaz()
        self._cargar_causas()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _crear_interfaz(self):
        # El selector va SIEMPRE en una fila: croquis (izq) y causas (der) a
        # la misma altura, en cualquier pantalla u orientacion.
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        # Zonas (croquis): se lleva TODO el espacio sobrante para verse grande.
        # Sin preseleccionar: el operador elige zona SOLO si la causa lo pide.
        self.zonas = SelectorZonas(
            self, on_seleccion=self._notificar_cambio, preseleccionar=False
        )
        layout.addWidget(self.zonas, stretch=1)

        # Causas a la derecha, ANCHAS exactamente lo que necesitan (nada de
        # espacio muerto): el sobrante horizontal va al croquis.
        col_causas = self._columna_causas()
        col_causas.setMaximumWidth(430)
        layout.addWidget(col_causas, stretch=0)

    def _columna_causas(self):
        """Lista de causas con BUSCAR (columna derecha)."""
        col_causas = QWidget(self)
        vc = QVBoxLayout(col_causas)
        vc.setContentsMargins(0, 0, 0, 0)
        vc.setSpacing(4)

        lbl = QLabel("Causa del paro:", col_causas)
        lbl.setObjectName("EstadoInfo")
        vc.addWidget(lbl, alignment=Qt.AlignLeft)

        self.entry_filtro = QLineEdit(col_causas)
        self.entry_filtro.setPlaceholderText("Buscar...")
        self.entry_filtro.setClearButtonEnabled(True)
        self.entry_filtro.textChanged.connect(self._refrescar_causas)
        vc.addWidget(self.entry_filtro)

        scroll = QScrollArea(col_causas)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        cont = QWidget(scroll)
        self.lista = QVBoxLayout(cont)
        self.lista.setContentsMargins(0, 0, 0, 0)
        self.lista.setSpacing(4)
        self.lista.addStretch(1)
        scroll.setWidget(cont)
        vc.addWidget(scroll, stretch=1)

        self.lbl_causa = QLabel("Causa: ninguna", col_causas)
        self.lbl_causa.setObjectName("EstadoInfo")
        vc.addWidget(self.lbl_causa, alignment=Qt.AlignLeft)
        return col_causas

    def _cargar_causas(self):
        self._causas = listar_causas_paro(activas_solo=True)
        self._refrescar_causas()

    def _refrescar_causas(self):
        # Limpiar botones actuales.
        while self.lista.count():
            item = self.lista.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._botones_causa = {}

        filtro = self.entry_filtro.text().strip().lower()
        for causa in self._causas:
            if filtro and filtro not in causa["descripcion"].lower():
                continue
            boton = self._crear_boton_causa(causa)
            self.lista.insertWidget(self.lista.count() - 1, boton)
            self._botones_causa[causa["id"]] = (boton, causa)

    def _crear_boton_causa(self, causa):
        # La causa es fija (solo descripcion + regla `requiere_zona`); el icono
        # y el tamano configurable pertenecen a las ZONAS, no a la causa.
        boton = QPushButton(causa["descripcion"], self)
        boton.setObjectName("Causa")
        boton.setMinimumHeight(44)
        if causa["requiere_zona"]:
            boton.setToolTip("Requiere elegir zona de la maquina.")
        boton.clicked.connect(
            lambda checked=False, c=causa: self._seleccionar(c)
        )
        return boton

    # ------------------------------------------------------------------
    # Seleccion
    # ------------------------------------------------------------------

    def _seleccionar(self, causa):
        self.seleccion_id = causa["id"]
        self.seleccion_descripcion = causa["descripcion"]
        self._causa_req_zona = bool(causa["requiere_zona"])
        for cid, (boton, _c) in self._botones_causa.items():
            activo = (cid == causa["id"])
            boton.setObjectName("CausaSel" if activo else "Causa")
            boton.style().unpolish(boton)
            boton.style().polish(boton)
        self.lbl_causa.setText("Causa: " + causa["descripcion"])
        if self.on_seleccion:
            self.on_seleccion(causa["id"], causa["descripcion"])
        self._notificar_cambio()

    def _notificar_cambio(self):
        if self.on_cambio:
            self.on_cambio()

    def puede_confirmar(self) -> bool:
        if self.seleccion_id is None:
            return False
        if self._causa_req_zona and self.zonas.seleccion_zona_id is None:
            return False
        return True

    def seleccion_zona_id(self):
        # La zona se elige SIEMPRE (croquis siempre habilitado), pero SOLO se
        # envia (no None) cuando la causa la requiere.
        if not self._causa_req_zona:
            return None
        return self.zonas.seleccion_zona_id

    def seleccion_zona_nombre(self):
        if not self._causa_req_zona:
            return None
        return self.zonas.seleccion_zona_nombre

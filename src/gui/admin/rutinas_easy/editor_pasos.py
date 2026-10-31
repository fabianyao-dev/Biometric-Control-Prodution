# -*- coding: utf-8 -*-
"""Editor de pasos de una rutina Easy.

La rutina vive en `rutinas_easy` y sus pasos en `rutinas_easy_pasos` (una fila
por paso). Este widget evita editar JSON a mano: muestra los pasos en una
tabla y permite agregarlos, editarlos, ordenarlos y activarlos con un
formulario que cambia segun la accion elegida.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.domain.easy import (
    ACCIONES_PERMITIDAS,
    PARAMETROS_OPCIONALES,
    PARAMETROS_REQUERIDOS,
    validar_paso,
)

ETIQUETAS_ACCION = {
    "click": "Clic",
    "doble_click": "Doble clic",
    "click_derecho": "Clic derecho",
    "mover": "Mover mouse",
    "texto": "Escribir texto",
    "tecla": "Presionar tecla",
    "atajo": "Atajo de teclado",
    "esperar": "Esperar",
}

ETIQUETAS_PARAMETRO = {
    "x": "X",
    "y": "Y",
    "valor": "Valor",
    "teclas": "Teclas",
    "segundos": "Espera",
    "boton": "Boton",
    "clicks": "Clicks",
    "intervalo": "Intervalo",
    "normalizar": "Normalizar",
    "comentario": "Nota",
}

AYUDAS = {
    "texto": "Usa {num_part} para el numero de parte del trabajo.",
    "tecla": "Ejemplos: enter, tab, esc, f5.",
    "atajo": "Separadas por coma o +. Ejemplo: ctrl, a",
    "teclas": "Separadas por coma o +. Ejemplo: ctrl, a",
}


def _orden_acciones():
    orden = (
        "click", "doble_click", "click_derecho", "mover",
        "texto", "tecla", "atajo", "esperar",
    )
    return [a for a in orden if a in ACCIONES_PERMITIDAS]


def _paso_plano(paso):
    """Convierte una fila de BD (con `parametros`) a dict plano."""
    item = {"accion": paso["accion"]}
    params = paso.get("parametros")
    if params is None:
        params = {
            k: v for k, v in paso.items()
            if k not in ("accion", "activo")
        }
    item.update(params or {})
    item["activo"] = bool(paso.get("activo", 1))
    return item


def _resumen_paso(paso):
    """Texto legible de los parametros, para la columna de la tabla."""
    partes = []
    for clave, valor in paso.items():
        if clave in ("accion", "activo"):
            continue
        if isinstance(valor, (list, tuple)):
            valor = " + ".join(str(v) for v in valor)
        elif isinstance(valor, bool):
            valor = "si" if valor else "no"
        etiqueta = ETIQUETAS_PARAMETRO.get(clave, clave)
        if clave == "segundos":
            valor = "%s s" % valor
        partes.append("%s: %s" % (etiqueta, valor))
    return "   ".join(partes) or "(sin parametros)"


class EditorPasosEasy(QWidget):
    """Tabla + formulario para editar los pasos de una rutina Easy."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pasos = []
        self._editando = None
        self._refrescando = False
        self._campos = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        split = QSplitter(Qt.Horizontal, self)
        layout.addWidget(split, stretch=1)

        izq = QWidget(split)
        vl = QVBoxLayout(izq)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.setSpacing(6)

        barra = QHBoxLayout()
        lbl_pasos = QLabel("Pasos (orden de ejecucion):", izq)
        barra.addWidget(lbl_pasos)
        barra.addStretch(1)
        vl.addLayout(barra)

        self.tabla = QTableWidget(izq)
        self.tabla.setColumnCount(4)
        self.tabla.setHorizontalHeaderLabels(
            ["#", "Accion", "Parametros", "Activa"]
        )
        self.tabla.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tabla.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tabla.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tabla.verticalHeader().setVisible(False)
        self.tabla.horizontalHeader().setStretchLastSection(False)
        self.tabla.horizontalHeader().setMinimumSectionSize(36)
        for col, ancho in enumerate((40, 130, 240, 55)):
            self.tabla.setColumnWidth(col, ancho)
        self.tabla.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.Stretch
        )
        vl.addWidget(self.tabla, stretch=1)

        fila_botones = QGridLayout()
        fila_botones.setSpacing(6)
        self.btn_editar = QPushButton("Editar", izq)
        self.btn_eliminar = QPushButton("Eliminar", izq)
        self.btn_subir = QPushButton("Subir", izq)
        self.btn_bajar = QPushButton("Bajar", izq)
        fila_botones.addWidget(self.btn_editar, 0, 0)
        fila_botones.addWidget(self.btn_eliminar, 0, 1)
        fila_botones.addWidget(self.btn_subir, 1, 0)
        fila_botones.addWidget(self.btn_bajar, 1, 1)
        vl.addLayout(fila_botones)

        ayuda_tabla = QLabel(
            "Doble clic en un paso para editarlo. Los pasos se ejecutan "
            "de arriba hacia abajo.", izq
        )
        ayuda_tabla.setObjectName("EstadoInfo")
        ayuda_tabla.setWordWrap(True)
        vl.addWidget(ayuda_tabla)
        split.addWidget(izq)

        caja = QGroupBox("Paso", split)
        vc = QVBoxLayout(caja)
        vc.setContentsMargins(8, 8, 8, 8)
        vc.setSpacing(8)
        fila_accion = QHBoxLayout()
        fila_accion.addWidget(QLabel("Accion:", caja))
        self.combo_accion = QComboBox(caja)
        for accion in _orden_acciones():
            self.combo_accion.addItem(ETIQUETAS_ACCION.get(accion, accion), accion)
        fila_accion.addWidget(self.combo_accion, stretch=1)
        vc.addLayout(fila_accion)

        self.caja_params = QWidget(caja)
        self.grid_params = QGridLayout(self.caja_params)
        self.grid_params.setContentsMargins(0, 0, 0, 0)
        self.grid_params.setSpacing(8)
        self.grid_params.setColumnStretch(1, 1)
        self.grid_params.setColumnStretch(3, 1)
        vc.addWidget(self.caja_params)

        self.lbl_ayuda = QLabel("", caja)
        self.lbl_ayuda.setObjectName("EstadoInfo")
        self.lbl_ayuda.setWordWrap(True)
        vc.addWidget(self.lbl_ayuda)

        leyenda = QLabel("* campo obligatorio", caja)
        leyenda.setObjectName("EstadoInfo")
        vc.addWidget(leyenda)

        vc.addStretch(1)
        fila_paso = QHBoxLayout()
        self.btn_guardar_paso = QPushButton("Agregar paso", caja)
        self.btn_cancelar = QPushButton("Cancelar", caja)
        self.btn_cancelar.setVisible(False)
        fila_paso.addWidget(self.btn_guardar_paso)
        fila_paso.addWidget(self.btn_cancelar)
        fila_paso.addStretch(1)
        vc.addLayout(fila_paso)
        split.addWidget(caja)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        split.setSizes([470, 340])

        self.combo_accion.currentIndexChanged.connect(self._accion_cambiada)
        self.tabla.itemDoubleClicked.connect(lambda _item: self._editar())
        self.tabla.itemChanged.connect(self._item_cambiado)
        self.btn_editar.clicked.connect(self._editar)
        self.btn_eliminar.clicked.connect(self._eliminar)
        self.btn_subir.clicked.connect(lambda: self._mover(-1))
        self.btn_bajar.clicked.connect(lambda: self._mover(1))
        self.btn_guardar_paso.clicked.connect(self._guardar_paso)
        self.btn_cancelar.clicked.connect(self._cancelar_edicion)

        self._accion_cambiada()

    # ------------------------------------------------------------------
    # API publica
    # ------------------------------------------------------------------
    def cargar(self, pasos):
        self._pasos = [_paso_plano(p) for p in (pasos or [])]
        self._cancelar_edicion()
        self._refrescar()

    def pasos(self):
        """Pasos con su estado `activo` (para guardar en la BD)."""
        return [dict(paso) for paso in self._pasos]

    def pasos_validables(self):
        """Pasos sin `activo` (para `validar_rutina`)."""
        return [
            {k: v for k, v in paso.items() if k != "activo"}
            for paso in self._pasos
        ]

    def vaciar(self):
        self.cargar([])

    # ------------------------------------------------------------------
    # Tabla
    # ------------------------------------------------------------------
    def _refrescar(self):
        self._refrescando = True
        try:
            self.tabla.setRowCount(len(self._pasos))
            for fila, paso in enumerate(self._pasos):
                self.tabla.setItem(fila, 0, QTableWidgetItem(str(fila + 1)))
                self.tabla.setItem(
                    fila, 1,
                    QTableWidgetItem(
                        ETIQUETAS_ACCION.get(paso["accion"], paso["accion"])
                    ),
                )
                self.tabla.setItem(fila, 2, QTableWidgetItem(_resumen_paso(paso)))
                item_activo = QTableWidgetItem("")
                item_activo.setFlags(
                    Qt.ItemIsUserCheckable | Qt.ItemIsEnabled
                    | Qt.ItemIsSelectable
                )
                item_activo.setCheckState(
                    Qt.Checked if paso.get("activo", True) else Qt.Unchecked
                )
                self.tabla.setItem(fila, 3, item_activo)
        finally:
            self._refrescando = False

    def _fila_actual(self):
        return self.tabla.currentRow()

    def _item_cambiado(self, item):
        if self._refrescando or item.column() != 3:
            return
        fila = item.row()
        if 0 <= fila < len(self._pasos):
            self._pasos[fila]["activo"] = (
                item.checkState() == Qt.Checked
            )

    def _seleccionar(self, fila):
        if 0 <= fila < self.tabla.rowCount():
            self.tabla.setCurrentCell(fila, 0)

    # ------------------------------------------------------------------
    # Formulario
    # ------------------------------------------------------------------
    def _limpiar_form_params(self):
        while self.grid_params.count():
            item = self.grid_params.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self._campos = {}

    def _accion_cambiada(self, *_args):
        accion = self.combo_accion.currentData()
        self._limpiar_form_params()
        if not accion:
            return
        requeridos = PARAMETROS_REQUERIDOS.get(accion, ())
        nombres = list(requeridos)
        nombres += [
            n for n in PARAMETROS_OPCIONALES.get(accion, ())
            if n not in nombres
        ]
        nombres.append("comentario")
        # Dos campos por renglon: con 6 parametros (clic) la caja no crece
        # de alto y los campos quedan alineados.
        for indice, nombre in enumerate(nombres):
            campo = self._crear_campo(nombre)
            self._campos[nombre] = campo
            etiqueta = ETIQUETAS_PARAMETRO.get(nombre, nombre)
            if nombre in requeridos:
                etiqueta += " *"
            fila, columna = divmod(indice, 2)
            self.grid_params.addWidget(
                QLabel(etiqueta + ":", self.caja_params), fila, columna * 2
            )
            self.grid_params.addWidget(campo, fila, columna * 2 + 1)
        self.lbl_ayuda.setText(AYUDAS.get(accion, ""))
        self.lbl_ayuda.setVisible(bool(AYUDAS.get(accion, "")))

    def _crear_campo(self, nombre):
        if nombre == "x":
            campo = QSpinBox(self.caja_params)
            campo.setRange(0, 1023)
        elif nombre == "y":
            campo = QSpinBox(self.caja_params)
            campo.setRange(0, 767)
        elif nombre == "clicks":
            campo = QSpinBox(self.caja_params)
            campo.setRange(0, 20)
            campo.setSpecialValueText("(por defecto)")
        elif nombre == "segundos":
            campo = QDoubleSpinBox(self.caja_params)
            campo.setRange(0.0, 600.0)
            campo.setDecimals(2)
        elif nombre == "intervalo":
            campo = QDoubleSpinBox(self.caja_params)
            campo.setRange(0.0, 60.0)
            campo.setDecimals(2)
            campo.setSpecialValueText("(por defecto)")
        elif nombre == "boton":
            campo = QComboBox(self.caja_params)
            campo.addItem("(por defecto)", None)
            for valor in ("izq", "der", "medio"):
                campo.addItem(valor, valor)
        elif nombre == "normalizar":
            campo = QCheckBox("Quitar espacios repetidos", self.caja_params)
        else:
            campo = QLineEdit(self.caja_params)
            if nombre == "valor":
                campo.setPlaceholderText("Texto a escribir o tecla a pulsar")
            elif nombre == "teclas":
                campo.setPlaceholderText("ctrl, a")
        return campo

    def _leer_campo(self, nombre):
        campo = self._campos[nombre]
        if isinstance(campo, QSpinBox):
            return campo.value()
        if isinstance(campo, QDoubleSpinBox):
            return campo.value()
        if isinstance(campo, QComboBox):
            return campo.currentData()
        if isinstance(campo, QCheckBox):
            return campo.isChecked()
        return campo.text().strip()

    def _aplicar_valores(self, paso):
        for nombre, campo in self._campos.items():
            if nombre not in paso:
                continue
            valor = paso[nombre]
            if isinstance(campo, QSpinBox):
                campo.setValue(int(valor))
            elif isinstance(campo, QDoubleSpinBox):
                campo.setValue(float(valor))
            elif isinstance(campo, QComboBox):
                idx = campo.findData(valor)
                campo.setCurrentIndex(idx if idx >= 0 else 0)
            elif isinstance(campo, QCheckBox):
                campo.setChecked(bool(valor))
            else:
                if isinstance(valor, list):
                    valor = ", ".join(str(v) for v in valor)
                campo.setText(str(valor))

    def _leer_formulario(self):
        accion = self.combo_accion.currentData()
        if not accion:
            raise ValueError("Selecciona una accion.")
        paso = {"accion": accion}
        requeridos = PARAMETROS_REQUERIDOS.get(accion, ())
        for nombre in requeridos:
            valor = self._leer_campo(nombre)
            if nombre == "teclas":
                valor = [
                    t.strip() for t in str(valor).replace("+", ",").split(",")
                    if t.strip()
                ]
            if valor in ("", None, []):
                raise ValueError(
                    "El campo %s es obligatorio."
                    % ETIQUETAS_PARAMETRO.get(nombre, nombre)
                )
            paso[nombre] = valor
        for nombre in PARAMETROS_OPCIONALES.get(accion, ()):
            valor = self._leer_campo(nombre)
            if nombre == "boton":
                if valor:
                    paso[nombre] = valor
            elif nombre in ("clicks", "intervalo"):
                if valor:
                    paso[nombre] = valor
            elif nombre == "normalizar":
                if valor:
                    paso[nombre] = True
        comentario = self._leer_campo("comentario")
        if comentario:
            paso["comentario"] = comentario
        return validar_paso(paso)

    # ------------------------------------------------------------------
    # Acciones
    # ------------------------------------------------------------------
    def _guardar_paso(self):
        try:
            paso = self._leer_formulario()
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Paso invalido", str(exc))
            return
        if self._editando is None:
            paso["activo"] = True
            self._pasos.append(paso)
            fila = len(self._pasos) - 1
        else:
            paso["activo"] = self._pasos[self._editando].get("activo", True)
            self._pasos[self._editando] = paso
            fila = self._editando
        self._cancelar_edicion()
        self._refrescar()
        self._seleccionar(fila)

    def _editar(self):
        fila = self._fila_actual()
        if not (0 <= fila < len(self._pasos)):
            return
        paso = self._pasos[fila]
        idx = self.combo_accion.findData(paso["accion"])
        if idx < 0:
            QMessageBox.warning(
                self, "Editar", "La accion %r no es valida." % (paso["accion"],)
            )
            return
        self._editando = fila
        self.combo_accion.setCurrentIndex(idx)
        self._accion_cambiada()
        self._aplicar_valores(paso)
        self.btn_guardar_paso.setText("Actualizar paso")
        self.btn_cancelar.setVisible(True)

    def _cancelar_edicion(self):
        self._editando = None
        self.btn_guardar_paso.setText("Agregar paso")
        self.btn_cancelar.setVisible(False)
        self._accion_cambiada()

    def _eliminar(self):
        fila = self._fila_actual()
        if not (0 <= fila < len(self._pasos)):
            return
        del self._pasos[fila]
        self._cancelar_edicion()
        self._refrescar()
        self._seleccionar(min(fila, len(self._pasos) - 1))

    def _mover(self, delta):
        fila = self._fila_actual()
        destino = fila + delta
        if not (0 <= fila < len(self._pasos) and 0 <= destino < len(self._pasos)):
            return
        self._pasos[fila], self._pasos[destino] = (
            self._pasos[destino], self._pasos[fila]
        )
        self._refrescar()
        self._seleccionar(destino)

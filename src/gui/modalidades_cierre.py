"""
modalidades_cierre.py - Dialogo de cierre de trabajo (#5).

Al finalizar un trabajo (manual con el boton de maquina o automatico por
meta), el operador confirma la cantidad cortada en un input editable
(pre-cargado con el conteo detectado) y la corrige si no es el numero:
    - Guardar: se guarda la cantidad del input tal cual.
    - Folio modificado: se indica a cuanto se modifico el total del
      folio y se guarda min(cantidad del input, nuevo_total).
El estado final (Cerrado/Abierto) lo decide la capa de BD segun si la
cantidad guardada alcanza la meta; aqui solo se decide la CANTIDAD.
"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QIntValidator
from PySide6.QtWidgets import (
    QDialog,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from src.gui.style import aplicar_estilo_boton
from src.gui.util import centrar_y_ajustar

# Etiquetas persistidas en `trabajos_sesiones.modalidad` (compatibilidad con
# historial y con Sesiones). El guardado directo conserva 'parcial' (cantidad
# confirmada por el operador, sin topar); ya no hay botones Normal/Parcial.
MODALIDAD_NORMAL = "normal"
MODALIDAD_PARCIAL = "parcial"
MODALIDAD_FOLIO = "folio"


def _pedir_entero(parent, titulo, etiqueta, minimo=0):
    """Pide un entero. Devuelve int valido, None si se cancela o False si el
    valor escrito no es un entero valido (mayor o igual a `minimo`)."""
    texto, aceptado = QInputDialog.getText(parent, titulo, etiqueta)
    if not aceptado:
        return None
    texto = texto.strip()
    try:
        valor = int(texto)
    except ValueError:
        return False
    if valor < minimo:
        return False
    return valor


class ModalidadCierreDialog(QDialog):
    """Confirma la cantidad final del trabajo y recoge los datos de cierre.

    El input viene pre-cargado con el conteo detectado y es editable: si el
    numero no es correcto, el operador lo corrige ahi mismo. Botones:
    GUARDAR (guarda el input tal cual) y FOLIO MODIFICADO (pide el nuevo
    total y guarda min(input, nuevo_total)).

    Tras `exec()` con Accepted, leer:
        - `resultado_modalidad`: MODALIDAD_PARCIAL (directo) o MODALIDAD_FOLIO
        - `resultado_cantidad`: cantidad final a guardar
        - `resultado_nuevo_total`: int (solo MODALIDAD_FOLIO) o None
    """

    def __init__(self, parent, folio, num_part, cortado, meta,
                 cancelable=True):
        super().__init__(parent)
        self.folio = folio
        self.num_part = num_part
        self.cortado = cortado
        self.meta = meta
        self.cancelable = cancelable

        self.resultado_modalidad = None
        self.resultado_cantidad = None
        self.resultado_nuevo_total = None

        self.setWindowTitle("FINALIZAR TRABAJO")
        self.setModal(True)
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
        self._crear_interfaz()
        centrar_y_ajustar(self, parent)

    def _crear_interfaz(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 18, 24, 18)
        lay.setSpacing(14)

        titulo = QLabel("FINALIZAR TRABAJO", self)
        titulo.setObjectName("Title")
        titulo.setAlignment(Qt.AlignCenter)
        lay.addWidget(titulo)

        resumen = QLabel(
            f"Trabajo {self.folio} ({self.num_part})\n"
            f"Cortadas en esta sesión: {self.cortado}  ·  Meta: {self.meta}",
            self,
        )
        resumen.setObjectName("EstadoInfo")
        resumen.setAlignment(Qt.AlignCenter)
        resumen.setWordWrap(True)
        lay.addWidget(resumen)

        lbl_cantidad = QLabel("Cantidad cortada (corrige si no es el numero):", self)
        lbl_cantidad.setObjectName("EstadoInfo")
        lbl_cantidad.setAlignment(Qt.AlignCenter)
        lbl_cantidad.setWordWrap(True)
        lay.addWidget(lbl_cantidad)

        self.input_cantidad = QLineEdit(str(int(self.cortado)), self)
        self.input_cantidad.setValidator(QIntValidator(0, 99999999, self))
        self.input_cantidad.setAlignment(Qt.AlignCenter)
        self.input_cantidad.selectAll()
        lay.addWidget(self.input_cantidad)

        btn_guardar = QPushButton("GUARDAR", self)
        btn_guardar.setObjectName("Success")
        btn_guardar.clicked.connect(self._guardar_directo)
        btn_guardar.setAutoDefault(False)
        btn_guardar.setDefault(False)
        lay.addWidget(btn_guardar)

        btn_folio = QPushButton("FOLIO MODIFICADO", self)
        btn_folio.clicked.connect(self._elegir_folio)
        btn_folio.setAutoDefault(False)
        btn_folio.setDefault(False)
        lay.addWidget(btn_folio)

        # En el cierre por META (`cancelable=False`) no se permite cancelar:
        # el operador debe confirmar la cantidad y autorizar; no puede dejar
        # el trabajo Abierto con la cantidad_total ya cumplida.
        if self.cancelable:
            btn_cancelar = QPushButton("Cancelar", self)
            btn_cancelar.setAutoDefault(False)
            btn_cancelar.setDefault(False)
            btn_cancelar.clicked.connect(self.reject)
            lay.addWidget(btn_cancelar)

        self.input_cantidad.setFocus()

    def _leer_input(self):
        """Devuelve el entero del input o None si esta vacio/invalido."""
        try:
            return int(self.input_cantidad.text().strip())
        except ValueError:
            return None

    def _avisar_invalido(self):
        caja = QMessageBox(self)
        caja.setWindowTitle("Valor no valido")
        caja.setText("Escribe la cantidad cortada (numero entero mayor o igual a cero).")
        caja.setIcon(QMessageBox.Warning)
        caja.addButton("Aceptar", QMessageBox.AcceptRole)
        caja.exec()
        self.input_cantidad.setFocus()
        self.input_cantidad.selectAll()

    def _guardar_directo(self):
        """Guarda la cantidad del input tal cual (confirmada o corregida)."""
        valor = self._leer_input()
        if valor is None:
            self._avisar_invalido()
            return
        self.resultado_modalidad = MODALIDAD_PARCIAL
        self.resultado_cantidad = valor
        self.resultado_nuevo_total = None
        self.accept()

    def _elegir_folio(self):
        """Folio modificado: pide el nuevo total y guarda el input TOPADO a
        ese nuevo total."""
        cantidad = self._leer_input()
        if cantidad is None:
            self._avisar_invalido()
            return
        valor = _pedir_entero(
            self, "Folio modificado",
            "¿A cuanto se modifico la cantidad total del folio?", minimo=1,
        )
        if valor is None:
            return
        if valor is False:
            caja = QMessageBox(self)
            caja.setWindowTitle("Valor no valido")
            caja.setText("Escribe un numero entero mayor que cero.")
            caja.setIcon(QMessageBox.Warning)
            caja.addButton("Aceptar", QMessageBox.AcceptRole)
            caja.exec()
            return
        self.resultado_modalidad = MODALIDAD_FOLIO
        self.resultado_nuevo_total = valor
        self.resultado_cantidad = min(cantidad, valor)
        self.accept()

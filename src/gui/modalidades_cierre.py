"""
modalidades_cierre.py - Dialogo de modalidad de cierre de trabajo (#5).

Al apagar la maquina con un trabajo cargado, el operador elige como se
refleja la cantidad final del trabajo:
    - Produccion normal: cantidad = min(cortado, meta) (topada a la meta).
    - Produccion parcial: se confirma el conteo hecho, o se corrige a mano.
    - Folio modificado: se indica a cuanto se modifico el total del
      folio y se guarda min(cortado, nuevo_total).
El estado final (Cerrado/Abierto) lo decide la capa de BD segun si la
cantidad guardada alcanza la meta; aqui solo se decide la CANTIDAD.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from src.gui.style import aplicar_estilo_boton
from src.gui.util import centrar_y_ajustar

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
    """Elige la modalidad de cierre y recoge los datos de la cantidad final.

    Tras `exec()` con Accepted, leer:
        - `resultado_modalidad`: MODALIDAD_* 
        - `resultado_cantidad`: cantidad final a guardar (ya topada)
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
            f"Cortadas: {self.cortado}  ·  Meta: {self.meta}",
            self,
        )
        resumen.setObjectName("EstadoInfo")
        resumen.setAlignment(Qt.AlignCenter)
        resumen.setWordWrap(True)
        lay.addWidget(resumen)

        btn_normal = QPushButton("PRODUCCION NORMAL", self)
        btn_normal.clicked.connect(self._elegir_normal)
        btn_normal.setAutoDefault(False)
        btn_normal.setDefault(False)
        lay.addWidget(btn_normal)

        btn_parcial = QPushButton("PRODUCCION PARCIAL", self)
        btn_parcial.clicked.connect(self._elegir_parcial)
        btn_parcial.setAutoDefault(False)
        btn_parcial.setDefault(False)
        lay.addWidget(btn_parcial)

        btn_folio = QPushButton("FOLIO MODIFICADO", self)
        btn_folio.clicked.connect(self._elegir_folio)
        btn_folio.setAutoDefault(False)
        btn_folio.setDefault(False)
        lay.addWidget(btn_folio)

        # En el cierre por META (`cancelable=False`) no se permite cancelar:
        # el operador debe elegir modalidad y autorizar; no puede dejar el
        # trabajo Abierto con la cantidad_total ya cumplida.
        if self.cancelable:
            btn_cancelar = QPushButton("Cancelar", self)
            btn_cancelar.setAutoDefault(False)
            btn_cancelar.setDefault(False)
            btn_cancelar.clicked.connect(self.reject)
            lay.addWidget(btn_cancelar)

        # Evitar que ningun boton tenga foco inicial (no preseleccion)
        self.setFocusPolicy(Qt.NoFocus)

    def _elegir_normal(self):
        """Produccion normal: se guarda el cortado, TOPADO a la meta."""
        self.resultado_modalidad = MODALIDAD_NORMAL
        self.resultado_cantidad = min(self.cortado, self.meta)
        self.resultado_nuevo_total = None
        self.accept()

    def _elegir_parcial(self):
        """Parcial: confirma el conteo o pide corregirlo a mano."""
        self.resultado_modalidad = MODALIDAD_PARCIAL
        caja = QMessageBox(self)
        caja.setWindowTitle("Confirmar conteo")
        caja.setText(f"¿El conteo de {self.cortado} piezas es correcto?")
        caja.setIcon(QMessageBox.Question)
        btn_si = caja.addButton("Sí", QMessageBox.YesRole)
        caja.addButton("No", QMessageBox.NoRole)
        caja.exec()
        if caja.clickedButton() == btn_si:
            self.resultado_cantidad = self.cortado
            self.resultado_nuevo_total = None
            self.accept()
            return
        valor = _pedir_entero(
            self, "Corregir conteo",
            "Escribe la cantidad correcta de piezas:", minimo=0,
        )
        if valor is None:
            return
        if valor is False:
            caja = QMessageBox(self)
            caja.setWindowTitle("Valor no valido")
            caja.setText("Escribe un numero entero mayor o igual a cero.")
            caja.setIcon(QMessageBox.Warning)
            caja.addButton("Aceptar", QMessageBox.AcceptRole)
            caja.exec()
            return
        self.resultado_cantidad = valor
        self.resultado_nuevo_total = None
        self.accept()

    def _elegir_folio(self):
        """Folio modificado: pide el nuevo total y guarda el cortado
        TOPADO a ese nuevo total."""
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
        self.resultado_cantidad = min(self.cortado, valor)
        self.accept()

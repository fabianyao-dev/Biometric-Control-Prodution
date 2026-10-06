"""
modalidades_cierre.py - Dialogo de cierre de trabajo (#5).

Al finalizar un trabajo (manual con el boton de maquina o automatico por
meta), el operador confirma la cantidad cortada en un input editable
(pre-cargado con el conteo detectado) y la corrige si no es el numero,
tecleando o con los botones +/- (paso de 1):
    - Guardar: se guarda la cantidad del input tal cual.
    - Folio modificado: se indica a cuanto se modifico el total del
      folio y se guarda min(cantidad del input, nuevo_total).
El estado final (Cerrado/Abierto) lo decide la capa de BD segun si la
cantidad guardada alcanza la meta; aqui solo se decide la CANTIDAD.
"""

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QIntValidator
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from src.gui.util import centrar_y_ajustar

# Etiquetas persistidas en `trabajos_sesiones.modalidad` (compatibilidad con
# historial y con Sesiones). El guardado directo conserva 'parcial' (cantidad
# confirmada por el operador, sin topar); ya no hay botones Normal/Parcial.
MODALIDAD_NORMAL = "normal"
MODALIDAD_PARCIAL = "parcial"
MODALIDAD_FOLIO = "folio"

# Tope del input de cantidad (mismo limite que su QIntValidator).
MAX_CANTIDAD = 99999999


def ajustar_cantidad(texto, delta, maximo=MAX_CANTIDAD):
    """Nuevo texto del input de cantidad tras aplicar +/- `delta` (paso 1).

    Funcion pura (sin Qt) para poder probarla sin QApplication: texto vacio
    o no numerico cuenta como 0 y el resultado SIEMPRE queda entre 0 y
    `maximo` (el input no acepta negativos ni se pasa del tope).
    """
    try:
        valor = int(str(texto).strip() or 0)
    except ValueError:
        valor = 0
    return str(max(0, min(int(maximo), valor + int(delta))))


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
    numero no es correcto, el operador lo corrige tecleando o con los
    botones +/- (paso de 1; tambien flechas arriba/abajo sobre el input).
    Botones: GUARDAR (guarda el input tal cual) y FOLIO MODIFICADO (pide el
    nuevo total y guarda min(input, nuevo_total)).

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
        # Ancho acotado: el modal es pequeño por diseno (una sola columna de
        # ~440 px), no por el contenido que le pase la ventana padre.
        centrar_y_ajustar(self, parent, max_ancho=440)

    def _crear_interfaz(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 14, 20, 14)
        lay.setSpacing(8)

        titulo = QLabel("FINALIZAR TRABAJO", self)
        titulo.setObjectName("Title")
        titulo.setAlignment(Qt.AlignCenter)
        lay.addWidget(titulo)

        resumen = QLabel(
            f"Trabajo {self.folio} · {self.num_part}\n"
            f"Cortadas {self.cortado} · Meta {self.meta}",
            self,
        )
        resumen.setObjectName("EstadoInfo")
        resumen.setAlignment(Qt.AlignCenter)
        resumen.setWordWrap(True)
        lay.addWidget(resumen)

        lbl_cantidad = QLabel("Cantidad cortada", self)
        lbl_cantidad.setObjectName("EstadoInfo")
        lbl_cantidad.setAlignment(Qt.AlignCenter)
        lay.addWidget(lbl_cantidad)

        # Fila +/-: los botones flanquean el input al centro. El ritmo de
        # toque es grande (52 px) porque la app corre en panel tactil.
        self.input_cantidad = QLineEdit(str(int(self.cortado)), self)
        self.input_cantidad.setValidator(QIntValidator(0, MAX_CANTIDAD, self))
        self.input_cantidad.setAlignment(Qt.AlignCenter)
        self.input_cantidad.setPlaceholderText("Corrige si no es el numero")
        self.input_cantidad.setFixedHeight(52)
        fuente = self.input_cantidad.font()
        fuente.setPointSize(14)
        fuente.setBold(True)
        self.input_cantidad.setFont(fuente)
        self.input_cantidad.installEventFilter(self)

        btn_menos = self._boton_paso("-", lambda: self._ajustar_cantidad(-1))
        btn_mas = self._boton_paso("+", lambda: self._ajustar_cantidad(1))

        fila = QHBoxLayout()
        fila.setSpacing(8)
        fila.addStretch(1)
        fila.addWidget(btn_menos)
        fila.addWidget(self.input_cantidad, stretch=1)
        fila.addWidget(btn_mas)
        fila.addStretch(1)
        lay.addLayout(fila)

        self.input_cantidad.selectAll()

        btn_guardar = QPushButton("GUARDAR", self)
        btn_guardar.setObjectName("Success")
        btn_guardar.clicked.connect(self._guardar_directo)
        btn_guardar.setAutoDefault(False)
        btn_guardar.setDefault(False)
        lay.addWidget(btn_guardar)

        # FOLIO MODIFICADO y Cancelar comparten fila (antes iban apilados,
        # lo que alargaba el modal). En el cierre por META
        # (`cancelable=False`) no se permite cancelar: el operador debe
        # confirmar la cantidad; no puede dejar el trabajo Abierto con la
        # cantidad_total ya cumplida.
        fila_acciones = QHBoxLayout()
        fila_acciones.setSpacing(8)
        btn_folio = QPushButton("FOLIO MODIFICADO", self)
        btn_folio.clicked.connect(self._elegir_folio)
        btn_folio.setAutoDefault(False)
        btn_folio.setDefault(False)
        fila_acciones.addWidget(btn_folio, stretch=1)
        if self.cancelable:
            btn_cancelar = QPushButton("Cancelar", self)
            btn_cancelar.setAutoDefault(False)
            btn_cancelar.setDefault(False)
            btn_cancelar.clicked.connect(self.reject)
            fila_acciones.addWidget(btn_cancelar, stretch=1)
        lay.addLayout(fila_acciones)

        self.input_cantidad.setFocus()

    def _boton_paso(self, texto, al_pulsar):
        """Boton +/- de la fila de cantidad (tactil, sin accion primaria)."""
        boton = QPushButton(texto, self)
        boton.setObjectName("Causa")
        boton.setFixedSize(52, 52)
        boton.setAutoDefault(False)
        boton.setDefault(False)
        boton.clicked.connect(lambda checked=False: al_pulsar())
        fuente = boton.font()
        fuente.setPointSize(18)
        fuente.setBold(True)
        boton.setFont(fuente)
        return boton

    def eventFilter(self, objeto, evento):
        # Sobre el input: flechas arriba/abajo y +/- hacen lo mismo que los
        # botones (Enter queda reservado, no guarda).
        if objeto is self.input_cantidad and evento.type() == QEvent.KeyPress:
            tecla = evento.key()
            if tecla in (Qt.Key_Up, Qt.Key_Plus, Qt.Key_Equal):
                self._ajustar_cantidad(1)
                return True
            if tecla in (Qt.Key_Down, Qt.Key_Minus):
                self._ajustar_cantidad(-1)
                return True
        return super().eventFilter(objeto, evento)

    def _ajustar_cantidad(self, delta):
        """Aplica +/- 1 al input y devuelve el foco al texto (no al boton)."""
        self.input_cantidad.setText(
            ajustar_cantidad(self.input_cantidad.text(), delta)
        )
        self.input_cantidad.setFocus()
        self.input_cantidad.deselect()

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

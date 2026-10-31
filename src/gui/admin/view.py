"""Panel de administracion con pestanas (AdminView).

Compone la UI base y mezcla un mixin por pestana: Operadores, Causas de Paro,
Zonas, Rutinas Easy, Historial Easy, Roles y Sistema. Aqui viven el layout, los
helpers de etiquetas, la cola de captura de huella y `set_modulo()`.
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
from .operadores_mixin import OperadoresMixin
from .causas_mixin import CausasMixin
from .zonas_mixin import ZonasMixin
from .roles_mixin import RolesMixin
from .sistema_mixin import SistemaMixin
from .rutinas_easy.mixin import RutinasEasyMixin
from .historial_mixin import HistorialMixin

try:
    from src.domain.easy import validar_rutina
    from src.gui.admin.rutinas_easy import repo as repo_easy
    from src.gui.admin.rutinas_easy.editor_pasos import EditorPasosEasy
except Exception:  # noqa: BLE001
    repo_easy = None
    EditorPasosEasy = None
    validar_rutina = None

log = logging.getLogger(__name__)


class AdminView(
    QWidget,
    OperadoresMixin,
    CausasMixin,
    ZonasMixin,
    RolesMixin,
    SistemaMixin,
    RutinasEasyMixin,
    HistorialMixin,
):
    def __init__(self, parent, controller, biometrico):
        super().__init__(parent)
        self.controller = controller
        self.biometrico = biometrico

        self._capturando = False
        # Hilo de captura en curso: el lector NO admite dos capturas a la vez
        # (la llamada nativa es bloqueante y sin cancelacion); este handle es
        # la exclusion mutua real (`_lector_ocupado`). `_capturando` es solo
        # estado de UI y puede ir por delante cuando se invalida una captura.
        self._hilo_captura = None
        self._huellas_captura = []
        self._modo_captura = None
        # Secuencia de capturas: cada `_iniciar_captura` la incrementa. Sirve
        # para INVALIDAR una captura en vuelo (ej. se pulsa Guardar mientras
        # la cadena ya arranco la siguiente): su resultado tardio se descarta
        # en `_revisar_cola` en vez de colarse como huella fantasma.
        self._captura_seq = 0
        # Captura MULTIPLE encadenada: al registrar un operador nuevo se
        # capturan las huellas una tras otra (sin pulsar el boton por cada
        # dedo) hasta que se presione 'Detener Captura'.
        self._modo_cadena = False
        # Indica que la cadena quedo en espera de que el usuario coloque un
        # dedo distinto (no avanza solo hasta que arranca la captura).
        self._cadena_esperando = False
        self.cola = queue.Queue()
        self.cola_update = queue.Queue()
        self._manifest = None
        self._roles_por_nombre = {}
        self._acceso_admin_bloqueado = False

        self._crear_interfaz()
        self._revisar_cola()
        self._revisar_cola_update()

    def _crear_interfaz(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)

        self.notebook = QTabWidget(self)
        layout.addWidget(self.notebook)

        self.tab_operadores = QWidget()
        self.tab_causas = QWidget()
        self.tab_zonas = QWidget()
        self.tab_roles = QWidget()
        self.tab_sistema = QWidget()
        self.tab_rutinas_easy = QWidget()
        self.tab_historial_easy = QWidget()
        self.notebook.addTab(self.tab_operadores, "Operadores")
        self.notebook.addTab(self.tab_causas, "Causas de Paro")
        self.notebook.addTab(self.tab_zonas, "Zonas")
        self.notebook.addTab(self.tab_rutinas_easy, "Rutinas Easy")
        self.notebook.addTab(self.tab_historial_easy, "Historial Easy")
        self.notebook.addTab(self.tab_roles, "Roles")
        self.notebook.addTab(self.tab_sistema, "Sistema")

        self._crear_tab_operadores()
        self._crear_tab_causas()
        self._crear_tab_zonas()
        self._crear_tab_rutinas_easy()
        self._crear_tab_historial_easy()
        self._crear_tab_roles()
        self._crear_tab_sistema()

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
    # Roles (combo compartido por operadores)
    # ------------------------------------------------------------------

    def _recargar_roles_combo(self):
        """Actualiza los combos de rol y recuerda la seleccion por defecto."""
        self._roles_por_nombre = {
            r["nombre"]: r["id"] for r in listar_roles(activas_solo=True)
        }
        nombres = list(self._roles_por_nombre.keys())
        self.combo_rol.clear()
        self.combo_rol_cambio.clear()
        self.combo_rol.addItems(nombres)
        self.combo_rol_cambio.addItems(nombres)
        # Seleccion por defecto: operador (si existe), si no el primer rol.
        predeterminado = "operador" if "operador" in self._roles_por_nombre else (
            nombres[0] if nombres else "")
        if predeterminado:
            self.combo_rol.setCurrentText(predeterminado)

 
    # ------------------------------------------------------------------
    # Helpers / cola
    # ------------------------------------------------------------------

    def _lbl(self, texto, estado):
        self.lbl_mensaje.setText(texto)
        aplicar_estado(self.lbl_mensaje, estado)

    def _lbl_huella(self, texto, estado):
        self.lbl_huella.setText(texto)
        aplicar_estado(self.lbl_huella, estado)

    def _lbl_huellas(self, texto, estado):
        self.lbl_huellas_msg.setText(texto)
        aplicar_estado(self.lbl_huellas_msg, estado)

    def _lbl_causa(self, texto, estado):
        self.lbl_causa_msg.setText(texto)
        aplicar_estado(self.lbl_causa_msg, estado)

    def _lbl_rol(self, texto, estado):
        self.lbl_rol_msg.setText(texto)
        aplicar_estado(self.lbl_rol_msg, estado)

    def _lbl_permiso(self, texto, estado):
        self.lbl_permiso_msg.setText(texto)
        aplicar_estado(self.lbl_permiso_msg, estado)

    def _revisar_cola(self):
        try:
            while True:
                ev, data = self.cola.get_nowait()
                # Los eventos llevan (seq, carga): si la secuencia no es la
                # vigente, la captura fue invalidada (ej. se guardo mientras
                # corria) y el evento tardio se descarta SIN tocar
                # `_capturando` (podria haber una captura nueva en curso).
                seq, carga = data if isinstance(data, tuple) else (self._captura_seq, data)
                if seq != self._captura_seq:
                    continue
                if ev == "PROGRESO":
                    texto = carga or "Procesando..."
                    if self._modo_captura is None:
                        self._lbl_huella(texto, "procesando")
                    else:
                        self._lbl_huellas(texto, "procesando")
                elif ev == "ENROLL":
                    self._capturando = False
                    self._procesar_enroll(carga)
                elif ev == "ERROR":
                    self._capturando = False
                    if self._modo_captura is None:
                        self._lbl_huella(f"Error: {carga}", "error")
                    else:
                        self._lbl_huellas(f"Error: {carga}", "error")
        except queue.Empty:
            pass
        QTimer.singleShot(50, self._revisar_cola)

    def _procesar_enroll(self, data):
        modo = self._modo_captura
        self._modo_captura = None
        fmd = (data or {}).get("fmd")
        if not fmd:
            status = (data or {}).get("status", "?")
            msg = f"Captura sin plantilla ({status})."
            if modo is None:
                self._lbl_huella(msg, "error")
                if self._modo_cadena:
                    self._encadenar_captura()
            else:
                self._lbl_huellas(msg, "error")
            return
        if modo is None:
            self._agregar_huella_captura(fmd)
        elif modo[0] == "agregar":
            self._agregar_huella_operador(modo[1], fmd)
        else:
            self._reemplazar_huella(modo[1], fmd)
 
    # ------------------------------------------------------------------
    # Tab: Historial Easy
    # ------------------------------------------------------------------

    def set_modulo(self, clave):
        """Muestra/oculta las tabs propias del modulo activo."""
        # Tabs globales: siempre visibles.
        globales = {"Operadores", "Roles", "Sistema"}
        # Tabs de corte:
        de_corte = {"Causas de Paro", "Zonas", "Rutinas Easy", "Historial Easy"}
        for i in range(self.notebook.count()):
            texto = self.notebook.tabText(i)
            if texto in globales:
                self.notebook.setTabVisible(i, True)
            elif texto in de_corte:
                self.notebook.setTabVisible(i, (clave == "corte"))
            else:
                self.notebook.setTabVisible(i, True)


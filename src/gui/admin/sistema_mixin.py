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






class SistemaMixin:

    def _crear_tab_sistema(self):
        layout = QVBoxLayout(self.tab_sistema)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(8)

        titulo = QLabel("Sistema", self.tab_sistema)
        titulo.setObjectName("Title")
        layout.addWidget(titulo, alignment=Qt.AlignHCenter)

        self.lbl_version = QLabel(
            f"Versión instalada: {actualizaciones.version_instalada()}",
            self.tab_sistema,
        )
        aplicar_estado(self.lbl_version, "info")
        layout.addWidget(self.lbl_version, alignment=Qt.AlignHCenter)

        self.btn_actualizar = QPushButton("Buscar actualización", self.tab_sistema)
        self.btn_actualizar.clicked.connect(self._buscar_actualizacion)
        layout.addWidget(self.btn_actualizar, alignment=Qt.AlignHCenter)

        self.lbl_actualizar = QLabel("", self.tab_sistema)
        aplicar_estado(self.lbl_actualizar, "info")
        layout.addWidget(self.lbl_actualizar, alignment=Qt.AlignHCenter)

        if not config.UPDATE_SOURCE:
            self.btn_actualizar.setVisible(False)
            self.lbl_actualizar.setText(
                "Actualizaciones por red no configuradas (UPDATE_SOURCE vacío)."
            )

        layout.addStretch(1)

    def _lbl_actualizar(self, texto, estado):
        self.lbl_actualizar.setText(texto)
        aplicar_estado(self.lbl_actualizar, estado)

    def _buscar_actualizacion(self):
        if not config.UPDATE_SOURCE:
            return
        self.btn_actualizar.setEnabled(False)
        self._lbl_actualizar("Buscando actualización...", "procesando")
        threading.Thread(target=self._hilo_consultar, daemon=True).start()

    def _hilo_consultar(self):
        try:
            self.cola_update.put(("RESULTADO", actualizaciones.consultar_manifest()))
        except Exception as e:  # noqa: BLE001
            log.error("Consulta de actualizacion fallo: %s", e, exc_info=True)
            self.cola_update.put(("ERROR", str(e)))

    def _hilo_descargar(self):
        try:
            zip_path = actualizaciones.descargar_y_verificar(self._manifest)
            updater = actualizaciones.preparar_updater()
            self.cola_update.put(("LISTO", (zip_path, updater)))
        except Exception as e:  # noqa: BLE001
            log.error("Descarga de actualizacion fallo: %s", e, exc_info=True)
            self.cola_update.put(("ERROR", str(e)))

    def _revisar_cola_update(self):
        try:
            while True:
                ev, data = self.cola_update.get_nowait()
                if ev == "RESULTADO":
                    self._mostrar_resultado(data)
                elif ev == "LISTO":
                    self._aplicar_actualizacion(data)
                elif ev == "ERROR":
                    self._lbl_actualizar(f"No se pudo completar: {data}", "error")
                    self.btn_actualizar.setEnabled(True)
        except queue.Empty:
            pass
        QTimer.singleShot(50, self._revisar_cola_update)

    def _mostrar_resultado(self, manifest):
        self.btn_actualizar.setEnabled(True)
        remota = str((manifest or {}).get("version", "")).strip()
        publicada = str((manifest or {}).get("published_at", "") or "")
        instalada = actualizaciones.version_instalada()

        if not remota or not actualizaciones.hay_version_nueva(manifest):
            self._lbl_actualizar(
                "El sistema está actualizado. "
                f"Instalada: {instalada} · Disponible: {remota or '—'}.",
                "exito",
            )
            return

        self._manifest = manifest
        self._lbl_actualizar(
            f"Actualización disponible: {remota} (publicada el {publicada}).",
            "pendiente",
        )

        if not getattr(sys, "frozen", False):
            caja = QMessageBox(self)
            caja.setWindowTitle("Actualización disponible")
            caja.setText(f"Versión instalada: {instalada}\n"
                         f"Versión disponible: {remota}\n"
                         f"Publicada: {publicada}\n\n"
                         "Estás ejecutando el sistema en modo desarrollo. La "
                         "actualización se aplica en el paquete instalado (.exe).")
            caja.setIcon(QMessageBox.Information)
            caja.addButton("Aceptar", QMessageBox.AcceptRole)
            caja.exec()
            return

        caja = QMessageBox(self)
        caja.setWindowTitle("Actualización disponible")
        caja.setText(
            f"Versión instalada: {instalada}\n"
            f"Versión disponible: {remota}\n"
            f"Publicada: {publicada}\n\n"
            "La aplicación se cerrará y reabrirá automáticamente para aplicar "
            "la actualización."
        )
        btn_aplicar = caja.addButton("Aplicar ahora", QMessageBox.AcceptRole)
        caja.addButton("Cancelar", QMessageBox.RejectRole)
        caja.exec()
        if caja.clickedButton() is btn_aplicar:
            self._confirmar_estado_maquina()

    def _confirmar_estado_maquina(self):
        # OJO: maquina_lista() es una ACCION (arranca/pulsa START), no una
        # consulta de estado. Para saber si la maquina esta en marcha hay que
        # usar maquina_detenida() (consulta pura en ambos HAL).
        en_marcha = False
        try:
            hal = getattr(self.controller, "controlador", None)
            en_marcha = bool(hal and not hal.maquina_detenida())
        except Exception:  # noqa: BLE001 - nunca debe crashear la UI
            log.error("No se pudo consultar el estado de la maquina", exc_info=True)
        sesion = sesion_activa_actual()
        if en_marcha or sesion is not None:
            caja = QMessageBox(self)
            caja.setWindowTitle("Máquina en producción")
            caja.setText(
                "Hay una sesión o la máquina está en marcha. La actualización "
                "cerrará y reabrirá la aplicación; la sesión se recuperará al "
                "abrir (como tras un corte de luz).\n\n¿Continuar de todos "
                "modos?"
            )
            btn_ok = caja.addButton("Sí, continuar", QMessageBox.AcceptRole)
            caja.addButton("Cancelar", QMessageBox.RejectRole)
            caja.exec()
            if caja.clickedButton() is not btn_ok:
                return
        self._descargar_actualizacion()

    def _descargar_actualizacion(self):
        self.btn_actualizar.setEnabled(False)
        self._lbl_actualizar("Descargando actualización...", "procesando")
        threading.Thread(target=self._hilo_descargar, daemon=True).start()

    def _aplicar_actualizacion(self, datos):
        zip_path, updater = datos
        version = str((self._manifest or {}).get("version", ""))
        try:
            actualizaciones.lanzar_updater(updater, zip_path, version, relanzar=True)
        except Exception as e:  # noqa: BLE001
            log.error("No se pudo lanzar el updater: %s", e, exc_info=True)
            self._lbl_actualizar(f"No se pudo lanzar el actualizador: {e}", "error")
            self.btn_actualizar.setEnabled(True)
            return
        self._lbl_actualizar("Aplicando actualización...", "procesando")
        # El updater ya corre en proceso separado: cierra la app para que
        # libere sus archivos (el updater espera a que este proceso salga).
        self.controller._salir()


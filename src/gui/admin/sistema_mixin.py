"""Pestana Sistema: actualizaciones (SistemaMixin).

Consulta el catalogo `releases.json`, lista TODAS las versiones publicadas con
sus notas y estado (nueva/instalada/anterior) y permite instalar cualquiera de
ellas. La descarga y la aplicacion corren en hilos secundarios, drenando el
resultado por una cola. Pide confirmacion del estado de la maquina antes de
actualizar.
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
    QHeaderView,
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

        self.tabla_actualizaciones = QTableWidget(0, 4, self.tab_sistema)
        self.tabla_actualizaciones.setHorizontalHeaderLabels(
            ["Versión", "Estado", "Publicada", "Notas"]
        )
        self._config_tabla(self.tabla_actualizaciones)
        cabecera = self.tabla_actualizaciones.horizontalHeader()
        cabecera.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        cabecera.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        cabecera.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        cabecera.setSectionResizeMode(3, QHeaderView.Stretch)
        layout.addWidget(self.tabla_actualizaciones, 1)

        fila_botones = QHBoxLayout()
        self.btn_actualizar = QPushButton("Buscar actualizaciones", self.tab_sistema)
        self.btn_actualizar.clicked.connect(self._buscar_actualizacion)
        fila_botones.addWidget(self.btn_actualizar)

        self.btn_instalar = QPushButton(
            "Instalar versión seleccionada", self.tab_sistema
        )
        self.btn_instalar.setEnabled(False)
        self.btn_instalar.clicked.connect(self._instalar_seleccionada)
        fila_botones.addWidget(self.btn_instalar)
        layout.addLayout(fila_botones)

        self.lbl_actualizar = QLabel("", self.tab_sistema)
        self.lbl_actualizar.setWordWrap(True)
        aplicar_estado(self.lbl_actualizar, "info")
        layout.addWidget(self.lbl_actualizar)

        self.tabla_actualizaciones.itemSelectionChanged.connect(
            self._actualizar_boton_instalar
        )
        self.tabla_actualizaciones.cellDoubleClicked.connect(
            lambda *_: self._instalar_seleccionada()
        )

        if not config.UPDATE_SOURCE:
            self.btn_actualizar.setVisible(False)
            self.btn_instalar.setVisible(False)
            self.lbl_actualizar.setText(
                "Actualizaciones por red no configuradas (UPDATE_SOURCE vacío)."
            )
        else:
            self._lbl_actualizar(
                "Pulsa «Buscar actualizaciones» para ver las versiones "
                "publicadas en el servidor.",
                "info",
            )

    def _lbl_actualizar(self, texto, estado):
        self.lbl_actualizar.setText(texto)
        aplicar_estado(self.lbl_actualizar, estado)

    def _buscar_actualizacion(self):
        if not config.UPDATE_SOURCE:
            return
        self.btn_actualizar.setEnabled(False)
        self.btn_instalar.setEnabled(False)
        self._lbl_actualizar("Buscando actualizaciones...", "procesando")
        threading.Thread(target=self._hilo_consultar, daemon=True).start()

    def _hilo_consultar(self):
        try:
            self.cola_update.put(
                ("CATALOGO", actualizaciones.consultar_catalogo())
            )
        except Exception as e:  # noqa: BLE001
            log.error("Consulta de actualizaciones fallo: %s", e, exc_info=True)
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
                if ev == "CATALOGO":
                    self._mostrar_catalogo(data)
                elif ev == "LISTO":
                    self._aplicar_actualizacion(data)
                elif ev == "ERROR":
                    self._lbl_actualizar(f"No se pudo completar: {data}", "error")
                    self._set_botones_habilitados(True)
        except queue.Empty:
            pass
        QTimer.singleShot(50, self._revisar_cola_update)

    def _set_botones_habilitados(self, habilitado):
        self.btn_actualizar.setEnabled(habilitado)
        self.btn_instalar.setEnabled(
            habilitado and self._version_seleccionada() is not None
        )

    def _version_seleccionada(self):
        """Entrada del catalogo seleccionada en la tabla (o None)."""
        modelo = self.tabla_actualizaciones.selectionModel()
        filas = modelo.selectedRows() if modelo else []
        if not filas:
            return None
        item = self.tabla_actualizaciones.item(filas[0].row(), 0)
        return item.data(Qt.UserRole) if item else None

    def _actualizar_boton_instalar(self):
        entrada = self._version_seleccionada()
        self.btn_instalar.setEnabled(bool(entrada))
        if not entrada:
            self.btn_instalar.setText("Instalar versión seleccionada")
            return
        estado = actualizaciones.clasificar_version(
            str(entrada.get("version") or "")
        )
        textos = {
            "anterior": "Instalar versión anterior",
            "instalada": "Reinstalar versión instalada",
            "nueva": "Instalar versión seleccionada",
        }
        self.btn_instalar.setText(
            textos.get(estado, "Instalar versión seleccionada")
        )

    def _mostrar_catalogo(self, lista):
        """Llena la tabla con TODAS las versiones publicadas por el servidor."""
        self.btn_actualizar.setEnabled(True)
        self.tabla_actualizaciones.setRowCount(0)
        self._manifest = None
        lista = lista or []
        instalada = actualizaciones.version_instalada()
        etiquetas = {
            "nueva": "Nueva",
            "instalada": "Instalada",
            "anterior": "Anterior",
        }
        nuevas = 0
        for entrada in lista:
            version = str(entrada.get("version") or "")
            estado = actualizaciones.clasificar_version(version, instalada)
            if estado == "nueva":
                nuevas += 1
            fila = self.tabla_actualizaciones.rowCount()
            self.tabla_actualizaciones.insertRow(fila)
            item_version = QTableWidgetItem(version)
            item_version.setData(Qt.UserRole, entrada)
            item_estado = QTableWidgetItem(etiquetas.get(estado, estado))
            item_publicada = QTableWidgetItem(
                str(entrada.get("published_at") or "—")
            )
            notas = str(entrada.get("notas") or "").strip()
            item_notas = QTableWidgetItem(" ".join(notas.split()) or "—")
            item_notas.setToolTip(notas)
            self.tabla_actualizaciones.setItem(fila, 0, item_version)
            self.tabla_actualizaciones.setItem(fila, 1, item_estado)
            self.tabla_actualizaciones.setItem(fila, 2, item_publicada)
            self.tabla_actualizaciones.setItem(fila, 3, item_notas)

        self._actualizar_boton_instalar()
        if not lista:
            self._lbl_actualizar(
                "No hay versiones publicadas en el servidor.", "info"
            )
            return
        resumen = (
            f"{len(lista)} versión(es) publicada(s) · instalada: {instalada}"
        )
        if nuevas:
            resumen += f" · {nuevas} nueva(s) por instalar"
        self._lbl_actualizar(resumen, "exito" if nuevas else "info")

        # Seleccionar la primera version nueva; si no hay, la primera fila.
        fila_elegida = 0
        for fila in range(self.tabla_actualizaciones.rowCount()):
            item = self.tabla_actualizaciones.item(fila, 1)
            if item and item.text() == "Nueva":
                fila_elegida = fila
                break
        self.tabla_actualizaciones.selectRow(fila_elegida)

    def _instalar_seleccionada(self):
        """Confirma e inicia la instalacion de la version elegida en la tabla."""
        entrada = self._version_seleccionada()
        if not entrada:
            return
        version = str(entrada.get("version") or "")
        instalada = actualizaciones.version_instalada()
        estado = actualizaciones.clasificar_version(version, instalada)
        publicada = str(entrada.get("published_at") or "—")
        notas = str(entrada.get("notas") or "").strip() or "(sin notas)"

        if not getattr(sys, "frozen", False):
            caja = QMessageBox(self)
            caja.setWindowTitle("Instalar actualización")
            caja.setText(
                f"Versión instalada: {instalada}\n"
                f"Versión seleccionada: {version}\n"
                f"Publicada: {publicada}\n\n"
                f"Notas:\n{notas}\n\n"
                "Estás ejecutando el sistema en modo desarrollo. La "
                "actualización se aplica en el paquete instalado (.exe)."
            )
            caja.setIcon(QMessageBox.Information)
            caja.addButton("Aceptar", QMessageBox.AcceptRole)
            caja.exec()
            return

        if estado == "anterior":
            aviso = (
                "\n\nATENCIÓN: la versión seleccionada es ANTERIOR a la "
                "instalada. Se aplicará un descenso de versión."
            )
        elif estado == "instalada":
            aviso = "\n\nEs la misma versión instalada: se reinstalará."
        else:
            aviso = ""

        caja = QMessageBox(self)
        caja.setWindowTitle("Instalar actualización")
        caja.setText(
            f"Versión instalada: {instalada}\n"
            f"Versión seleccionada: {version}\n"
            f"Publicada: {publicada}\n\n"
            f"Notas:\n{notas}{aviso}\n\n"
            "La aplicación se cerrará y reabrirá automáticamente para aplicar "
            "la actualización."
        )
        caja.setIcon(
            QMessageBox.Warning if estado == "anterior" else QMessageBox.Information
        )
        btn_instalar = caja.addButton("Instalar ahora", QMessageBox.AcceptRole)
        caja.addButton("Cancelar", QMessageBox.RejectRole)
        caja.exec()
        if caja.clickedButton() is btn_instalar:
            self._confirmar_estado_maquina(entrada)

    def _confirmar_estado_maquina(self, entrada):
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
        self._descargar_actualizacion(entrada)

    def _descargar_actualizacion(self, entrada):
        self._manifest = entrada
        self.btn_actualizar.setEnabled(False)
        self.btn_instalar.setEnabled(False)
        version = str((entrada or {}).get("version") or "")
        self._lbl_actualizar(
            f"Descargando versión {version}...", "procesando"
        )
        threading.Thread(target=self._hilo_descargar, daemon=True).start()

    def _aplicar_actualizacion(self, datos):
        zip_path, updater = datos
        entrada = self._manifest or {}
        version = str(entrada.get("version") or "")
        permitir_descenso = (
            actualizaciones.clasificar_version(version) == "anterior"
        )
        try:
            actualizaciones.lanzar_updater(
                updater,
                zip_path,
                version,
                relanzar=True,
                permitir_descenso=permitir_descenso,
                notas=str(entrada.get("notas") or ""),
            )
        except Exception as e:  # noqa: BLE001
            log.error("No se pudo lanzar el updater: %s", e, exc_info=True)
            self._lbl_actualizar(f"No se pudo lanzar el actualizador: {e}", "error")
            self._set_botones_habilitados(True)
            return
        self._lbl_actualizar(f"Aplicando versión {version}...", "procesando")
        # El updater ya corre en proceso separado: cierra la app para que
        # libere sus archivos (el updater espera a que este proceso salga).
        # Usar close() (closeEvent) en lugar de _salir() para no apagar la
        # computadora: _salir() apaga la PC si el rol es operador; aqui
        # solo queremos cerrar la ventana y dejar que el updater trabaje.
        self.close()


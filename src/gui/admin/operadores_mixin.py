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






class OperadoresMixin:

    def _crear_tab_operadores(self):
        layout = QVBoxLayout(self.tab_operadores)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(8)

        titulo = QLabel("Registro de Operador", self.tab_operadores)
        titulo.setObjectName("Title")
        layout.addWidget(titulo, alignment=Qt.AlignHCenter)

        fila_nombre_rol = QWidget(self.tab_operadores)
        hn = QHBoxLayout(fila_nombre_rol)
        hn.setContentsMargins(0, 0, 0, 0)
        hn.setSpacing(6)
        self.entry_nombre = QLineEdit(fila_nombre_rol)
        self.entry_nombre.setPlaceholderText("Nombre del operador")
        self.entry_nombre.setFixedWidth(300)
        hn.addWidget(self.entry_nombre)
        lbl_rol = QLabel("Rol:", fila_nombre_rol)
        lbl_rol.setObjectName("EstadoInfo")
        hn.addWidget(lbl_rol)
        self.combo_rol = QComboBox(fila_nombre_rol)
        self.combo_rol.setMinimumWidth(200)
        hn.addWidget(self.combo_rol)
        layout.addWidget(fila_nombre_rol, alignment=Qt.AlignHCenter)

        self.lbl_huella = QLabel(
            "Huellas capturadas: 0",
            self.tab_operadores,
        )
        aplicar_estado(self.lbl_huella, "info")
        layout.addWidget(self.lbl_huella, alignment=Qt.AlignHCenter)

        frame_botones = QWidget(self.tab_operadores)
        hb = QHBoxLayout(frame_botones)
        hb.setContentsMargins(0, 0, 0, 0)
        hb.setSpacing(8)
        self.btn_capturar = QPushButton("Capturar Huellas", frame_botones)
        self.btn_capturar.setToolTip(
            "Captura las huellas una tras otra. Vuelve a presionar "
            "'Detener Captura' cuando hayas puesto las que quieras."
        )
        self.btn_capturar.clicked.connect(self._capturar_huella)
        hb.addWidget(self.btn_capturar)
        btn_quitar = QPushButton("Quitar Última", frame_botones)
        btn_quitar.clicked.connect(self._quitar_ultima_huella)
        hb.addWidget(btn_quitar)
        btn_guardar = QPushButton("Guardar Operador", frame_botones)
        btn_guardar.setObjectName("Success")
        btn_guardar.clicked.connect(self._guardar_operador)
        hb.addWidget(btn_guardar)
        layout.addWidget(frame_botones, alignment=Qt.AlignHCenter)

        self.lbl_mensaje = QLabel("", self.tab_operadores)
        aplicar_estado(self.lbl_mensaje, "info")
        layout.addWidget(self.lbl_mensaje, alignment=Qt.AlignHCenter)

        sep = QFrame(self.tab_operadores)
        sep.setFrameShape(QFrame.HLine)
        sep.setObjectName("Separador")
        layout.addWidget(sep)

        columnas = QWidget(self.tab_operadores)
        hcols = QHBoxLayout(columnas)
        hcols.setContentsMargins(0, 0, 0, 0)
        hcols.setSpacing(12)

        # Columna izquierda: operadores.
        col_operadores = QWidget(columnas)
        lv_ops = QVBoxLayout(col_operadores)
        lv_ops.setContentsMargins(0, 0, 0, 0)
        lv_ops.setSpacing(6)

        lbl_lista = QLabel("Operadores registrados:", col_operadores)
        lbl_lista.setObjectName("HeaderLabel")
        lv_ops.addWidget(lbl_lista)

        self.lista_operadores = QTableWidget(0, 3, col_operadores)
        self.lista_operadores.setHorizontalHeaderLabels(
            ["ID", "Nombre", "Rol"]
        )
        self._config_tabla(self.lista_operadores)
        for i, ancho in enumerate((50, 200, 140)):
            self.lista_operadores.setColumnWidth(i, ancho)
        lv_ops.addWidget(self.lista_operadores, stretch=1)

        fila_eliminar = QWidget(col_operadores)
        h1 = QHBoxLayout(fila_eliminar)
        h1.setContentsMargins(0, 0, 0, 0)
        h1.setSpacing(6)
        btn_eliminar = QPushButton("Eliminar Operador", fila_eliminar)
        btn_eliminar.clicked.connect(self._eliminar_operador)
        h1.addWidget(btn_eliminar)
        lv_ops.addWidget(fila_eliminar, alignment=Qt.AlignHCenter)

        fila_cambio = QWidget(col_operadores)
        h2 = QHBoxLayout(fila_cambio)
        h2.setContentsMargins(0, 0, 0, 0)
        h2.setSpacing(6)
        lbl_cambio = QLabel("Rol:", fila_cambio)
        lbl_cambio.setObjectName("EstadoInfo")
        h2.addWidget(lbl_cambio)
        self.combo_rol_cambio = QComboBox(fila_cambio)
        self.combo_rol_cambio.setMinimumWidth(110)
        h2.addWidget(self.combo_rol_cambio)
        btn_aplicar = QPushButton("Aplicar", fila_cambio)
        btn_aplicar.clicked.connect(self._aplicar_cambio_rol)
        h2.addWidget(btn_aplicar)
        lv_ops.addWidget(fila_cambio, alignment=Qt.AlignHCenter)

        # Columna derecha: huellas del operador seleccionado.
        col_huellas = QWidget(columnas)
        lv_huellas = QVBoxLayout(col_huellas)
        lv_huellas.setContentsMargins(0, 0, 0, 0)
        lv_huellas.setSpacing(6)

        lbl_huellas_titulo = QLabel(
            "Huellas del operador seleccionado:", col_huellas
        )
        lbl_huellas_titulo.setObjectName("HeaderLabel")
        lv_huellas.addWidget(lbl_huellas_titulo)

        self.lbl_huellas_info = QLabel(
            "Selecciona un operador de la lista.", col_huellas
        )
        self.lbl_huellas_info.setObjectName("EstadoInfo")
        lv_huellas.addWidget(self.lbl_huellas_info)

        self.lista_huellas = QTableWidget(0, 2, col_huellas)
        self.lista_huellas.setHorizontalHeaderLabels(["ID", "Fecha de captura"])
        self._config_tabla(self.lista_huellas)
        for i, ancho in enumerate((60, 200)):
            self.lista_huellas.setColumnWidth(i, ancho)
        lv_huellas.addWidget(self.lista_huellas, stretch=1)

        fila_huellas = QWidget(col_huellas)
        hhu = QHBoxLayout(fila_huellas)
        hhu.setContentsMargins(0, 0, 0, 0)
        hhu.setSpacing(6)
        btn_agregar_huella = QPushButton("Agregar Huella", fila_huellas)
        btn_agregar_huella.clicked.connect(self._capturar_huella_agregar)
        hhu.addWidget(btn_agregar_huella)
        btn_reemplazar_huella = QPushButton("Reemplazar Huella", fila_huellas)
        btn_reemplazar_huella.clicked.connect(self._capturar_huella_reemplazar)
        hhu.addWidget(btn_reemplazar_huella)
        lv_huellas.addWidget(fila_huellas, alignment=Qt.AlignHCenter)

        fila_huella_eliminar = QWidget(col_huellas)
        hhe = QHBoxLayout(fila_huella_eliminar)
        hhe.setContentsMargins(0, 0, 0, 0)
        hhe.setSpacing(6)
        btn_eliminar_huella = QPushButton("Eliminar Huella", fila_huella_eliminar)
        btn_eliminar_huella.clicked.connect(self._eliminar_huella)
        hhe.addWidget(btn_eliminar_huella)
        lv_huellas.addWidget(fila_huella_eliminar, alignment=Qt.AlignHCenter)

        self.lbl_huellas_msg = QLabel("", col_huellas)
        aplicar_estado(self.lbl_huellas_msg, "info")
        lv_huellas.addWidget(self.lbl_huellas_msg, alignment=Qt.AlignHCenter)

        hcols.addWidget(col_operadores, stretch=1)
        hcols.addWidget(col_huellas, stretch=1)
        layout.addWidget(columnas, stretch=1)

        self._recargar_roles_combo()
        self._recargar_operadores()
        self.lista_operadores.itemSelectionChanged.connect(self._recargar_huellas)
        self._recargar_huellas()

    def _capturar_huella(self):
        """Toggle de captura MULTIPLE. El boton inicia la cadena (se capturan
        huellas una tras otra sin pulsar por cada dedo) y, al volver a
        presionarlo, la DETIENE dejando las huellas capturadas hasta ese
        momento (el usuario decide cuantas poner)."""
        if self._modo_cadena:
            self._detener_cadena()
            return
        if self._capturando or self._lector_ocupado():
            # Hay una captura en curso (o liberandose): no pisarla.
            self._lbl_huella(
                "Lector ocupado: coloca el dedo para liberar la captura en "
                "curso o espera unos segundos...", "error"
            )
            return
        if not self.entry_nombre.text().strip():
            self._lbl("Escribe el nombre antes de capturar las huellas.", "error")
            return
        self._modo_captura = None
        self._modo_cadena = True
        self._cadena_esperando = False
        self._lbl("", "info")
        self._lbl_huella(
            "Coloca tu huella... Presiona 'Detener Captura' al terminar.",
            "procesando",
        )
        # Timeout CORTO en cadena: si el usuario detiene/garda a media
        # captura, el hilo en vuelo (no cancelable) libera el lector pronto.
        if not self._iniciar_captura(
            timeout_ms=config.CAPTURE_TIMEOUT_CADENA_MS
        ):
            self._modo_cadena = False
            self._lbl_huella("Lector ocupado, intenta de nuevo...", "error")
            return
        self._actualizar_boton_captura()

    def _detener_cadena(self):
        """Detiene la captura encadenada; conserva las huellas ya capturadas.

        Si habia una captura en vuelo (no cancelable), se invalida: su
        resultado tardio se descarta y Guardar funciona de inmediato aunque
        el lector siga liberandose unos segundos."""
        self._modo_cadena = False
        self._cadena_esperando = False
        if self._modo_captura is None:
            self._invalidar_captura_en_vuelo()
        self._lbl_huella("Captura detenida.", "info")
        self._actualizar_boton_captura()

    def _actualizar_boton_captura(self):
        texto = "Detener Captura" if self._modo_cadena else "Capturar Huellas"
        self.btn_capturar.setText(texto)

    def _capturar_huella_agregar(self):
        if self._capturando or self._lector_ocupado():
            return
        op_id, _ = self._operador_seleccionado()
        if op_id is None:
            self._lbl_huellas("Selecciona un operador de la lista.", "error")
            return
        self._modo_captura = ("agregar", op_id)
        self._lbl_huellas("Coloca tu huella...", "procesando")
        self._iniciar_captura()

    def _capturar_huella_reemplazar(self):
        if self._capturando or self._lector_ocupado():
            return
        huella_id = self._huella_seleccionada()
        if huella_id is None:
            self._lbl_huellas("Selecciona una huella de la lista.", "error")
            return
        self._modo_captura = ("reemplazar", huella_id)
        self._lbl_huellas("Coloca tu huella...", "procesando")
        self._iniciar_captura()

    def _lector_ocupado(self):
        """True si hay un hilo de captura VIVO (dueno real del lector)."""
        h = self._hilo_captura
        return bool(h is not None and h.is_alive())

    def _iniciar_captura(self, timeout_ms=None):
        """Arranca una captura en hilo. Devuelve False (sin arrancar) si el
        lector esta ocupado: NUNCA se pisa una captura en curso, porque dos
        `dpfpdd_capture` concurrentes traban el lector hasta reiniciar."""
        if self._lector_ocupado():
            return False
        self._captura_seq += 1
        seq = self._captura_seq
        self._capturando = True
        h = threading.Thread(target=self._trabajo_captura,
                             args=(seq, timeout_ms), daemon=True)
        self._hilo_captura = h
        h.start()
        return True

    def _trabajo_captura(self, seq, timeout_ms):
        try:
            data = self.biometrico.enrollar(
                timeout_ms=timeout_ms,
                on_progress=lambda m: self.cola.put(("PROGRESO", (seq, m))),
            )
            self.cola.put(("ENROLL", (seq, data)))
        except Exception as e:  # noqa: BLE001
            log.error("Captura admin fallo: %s", e, exc_info=True)
            self.cola.put(("ERROR", (seq, str(e))))

    def _progreso(self, mensaje):
        self.cola.put(("PROGRESO", (self._captura_seq, mensaje)))

    def _invalidar_captura_en_vuelo(self):
        """Invalida la captura en curso: su resultado tardio se descarta en
        `_revisar_cola` (no se agrega como huella fantasma)."""
        self._captura_seq += 1
        self._capturando = False

    def _guardar_operador(self):
        if self._modo_cadena:
            # Guardar DETIENE la cadena (`_detener_cadena` ya invalida la
            # captura en vuelo y baja `_capturando`): se guarda de inmediato
            # con lo capturado, aunque el lector siga liberandose.
            self._detener_cadena()
        if self._capturando:
            # Solo posible en flujos agregar/reemplazar (la cadena ya
            # invalido su captura). El bloqueo del lector NUNCA frena el
            # guardado: solo el arranque de NUEVAS capturas lo respeta.
            self._lbl("Termina la captura en curso y vuelve a guardar.",
                      "error")
            return
        nombre = self.entry_nombre.text().strip()
        if not nombre:
            self._lbl("Escribe el nombre.", "error")
            return
        if not self._huellas_captura:
            self._lbl("Captura al menos una huella.", "error")
            return
        rol_id = self._roles_por_nombre.get(self.combo_rol.currentText())
        ok, res = guardar_operador(nombre, self._huellas_captura, rol_id)
        if ok:
            self._lbl(
                f"Operador '{nombre}' registrado con "
                f"{len(self._huellas_captura)} huellas.",
                "exito",
            )
            self.entry_nombre.clear()
            self._huellas_captura = []
            self._modo_cadena = False
            self._cadena_esperando = False
            self._actualizar_estado_captura()
            self._actualizar_boton_captura()
            self._recargar_operadores()
        else:
            self._lbl(str(res), "error")

    def _quitar_ultima_huella(self):
        if not self._huellas_captura:
            return
        # Quitar la ultima tambien DETIENE la cadena de captura multiple.
        era_cadena = self._modo_cadena
        self._modo_cadena = False
        self._cadena_esperando = False
        # Si la cadena tenia una captura en vuelo, invalidarla para que su
        # resultado tardio no re-agregue la huella que se acaba de quitar.
        if era_cadena and self._modo_captura is None:
            self._invalidar_captura_en_vuelo()
        self._huellas_captura.pop()
        self._lbl("Última huella quitada.", "info")
        self._actualizar_estado_captura()
        self._actualizar_boton_captura()

    def _agregar_huella_captura(self, fmd):
        if self._es_duplicada(fmd, self._huellas_captura):
            self._lbl_huella(
                "Esa huella ya se puso. Usa un dedo distinto.", "error"
            )
            if self._modo_cadena:
                # En cadena no se corta: se vuelve a pedir un dedo distinto.
                self._lbl_huella(
                    "Esa huella ya se puso. Retira el dedo y coloca uno "
                    "distinto...",
                    "error",
                )
                self._encadenar_captura()
            return
        self._huellas_captura.append(fmd)
        n = len(self._huellas_captura)
        self._lbl(
            f"Huella {n} capturada. Presiona 'Detener Captura' para "
            "terminar.",
            "exito",
        )
        self._actualizar_estado_captura()
        if self._modo_cadena:
            self._encadenar_captura()

    def _encadenar_captura(self):
        """Arranca la siguiente captura de la cadena con una pausa para que
        el operador retire el dedo y coloque otro."""
        if not self._modo_cadena or self._cadena_esperando:
            return
        if self._capturando:
            return
        self._cadena_esperando = True
        QTimer.singleShot(
            900,
            lambda: self._lanzar_siguiente_captura_cadena()
        )

    def _lanzar_siguiente_captura_cadena(self):
        self._cadena_esperando = False
        # Si mientras se esperaba se detuvo o cancelo la cadena, no lanzar.
        if not self._modo_cadena:
            return
        if self._capturando or self._lector_ocupado():
            # El lector sigue liberandose (captura invalidada en vuelo):
            # reintentar cuando quede libre, sin pisarlo.
            self._encadenar_captura()
            return
        self._lbl_huella("Coloca el siguiente dedo...", "procesando")
        self._iniciar_captura(
            timeout_ms=config.CAPTURE_TIMEOUT_CADENA_MS
        )

    def _actualizar_estado_captura(self):
        self._lbl_huella(
            f"Huellas capturadas: {len(self._huellas_captura)}.",
            "info",
        )

    def _agregar_huella_operador(self, op_id, fmd):
        existentes = [
            f["huella_template"]
            for f in listar_huellas_operador(op_id, con_template=True)
        ]
        if self._es_duplicada(fmd, existentes):
            self._lbl_huellas(
                "Esa huella ya está registrada para este operador.", "error"
            )
            return
        if agregar_huella(op_id, fmd):
            self._lbl_huellas("Huella agregada.", "exito")
            self._recargar_huellas()
        else:
            self._lbl_huellas("No se pudo agregar la huella.", "error")

    def _reemplazar_huella(self, huella_id, fmd):
        if reemplazar_huella(huella_id, fmd):
            self._lbl_huellas("Huella reemplazada.", "exito")
            self._recargar_huellas()
        else:
            self._lbl_huellas("No se pudo reemplazar la huella.", "error")

    def _es_duplicada(self, fmd, lista):
        for otra in lista:
            score = self.biometrico.comparar(fmd, otra)
            if score is not None and score <= config.UMBRAL_DISIMILARIDAD:
                return True
        return False

    def _eliminar_huella(self):
        op_id, _ = self._operador_seleccionado()
        huella_id = self._huella_seleccionada()
        if op_id is None or huella_id is None:
            self._lbl_huellas("Selecciona una huella de la lista.", "error")
            return
        if len(listar_huellas_operador(op_id)) <= 1:
            self._lbl_huellas(
                "El operador debe conservar al menos una huella.", "error"
            )
            return
        if eliminar_huella(huella_id):
            self._lbl_huellas("Huella eliminada.", "exito")
            self._recargar_huellas()
        else:
            self._lbl_huellas("No se pudo eliminar la huella.", "error")

    def _operador_seleccionado(self):
        fila = self.lista_operadores.currentRow()
        if fila < 0:
            return None, ""
        return (
            int(self.lista_operadores.item(fila, 0).text()),
            self.lista_operadores.item(fila, 1).text(),
        )

    def _huella_seleccionada(self):
        fila = self.lista_huellas.currentRow()
        if fila < 0:
            return None
        return int(self.lista_huellas.item(fila, 0).text())

    def _recargar_huellas(self):
        self.lista_huellas.setRowCount(0)
        op_id, nombre = self._operador_seleccionado()
        if op_id is None:
            self.lbl_huellas_info.setText(
                "Selecciona un operador de la lista para ver sus huellas."
            )
            return
        huellas = listar_huellas_operador(op_id)
        self.lbl_huellas_info.setText(
            f"Operador: {nombre} ({len(huellas)} huella(s))"
        )
        for h in huellas:
            fila = self.lista_huellas.rowCount()
            self.lista_huellas.insertRow(fila)
            self.lista_huellas.setItem(fila, 0, QTableWidgetItem(str(h["id"])))
            self.lista_huellas.setItem(
                fila, 1, QTableWidgetItem(str(h["fecha_captura"]))
            )

    def _eliminar_operador(self):
        fila = self.lista_operadores.currentRow()
        if fila < 0:
            self._lbl("Selecciona un operador de la lista.", "error")
            return
        op_id = int(self.lista_operadores.item(fila, 0).text())
        eliminar_operador(op_id)
        self._lbl("Operador eliminado (desactivado).", "exito")
        self._recargar_operadores()

    def _aplicar_cambio_rol(self):
        fila = self.lista_operadores.currentRow()
        if fila < 0:
            self._lbl("Selecciona un operador de la lista.", "error")
            return
        rol_id = self._roles_por_nombre.get(self.combo_rol_cambio.currentText())
        if rol_id is None:
            self._lbl("Selecciona un rol valido.", "error")
            return
        op_id = int(self.lista_operadores.item(fila, 0).text())
        actualizar_rol_operador(op_id, rol_id)
        self._lbl("Rol actualizado.", "exito")
        self._recargar_operadores()

    def _recargar_operadores(self):
        self.lista_operadores.setRowCount(0)
        for op in listar_operadores_admin():
            if not op["activo"]:
                continue
            fila = self.lista_operadores.rowCount()
            self.lista_operadores.insertRow(fila)
            rol = op["rol"] or "Sin rol"
            valores = (op["id"], op["nombre"], rol)
            for col, valor in enumerate(valores):
                self.lista_operadores.setItem(fila, col, QTableWidgetItem(str(valor)))


"""
sessions_view.py - Consulta de sesiones de produccion, paros y trabajos.

Lista todas las sesiones registradas (con su hora de fin) y, al seleccionar
una, muestra lado a lado los PAROS (causa, inicio, fin, quien autorizo) y los
TRABAJOS (folio, parte, avance) de esa sesion. Columnas responsive: cada una
se ajusta a su contenido salvo las de texto libre (Operador/Causa/Parte),
que se estiran.
"""

import logging
from PySide6.QtCore import QDate, QStandardPaths, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCalendarWidget,
    QDialog,
    QFileDialog,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

import qtawesome as qta

from src.database import (
    listar_sesiones,
    listar_trabajos_de_sesion,
    obtener_paros_de_sesion,
)
from src.reportes.export_dia import exportar_dia

log = logging.getLogger(__name__)


class SessionsView(QWidget):
    def __init__(self, parent, controller):
        super().__init__(parent)
        self.controller = controller
        self._crear_interfaz()
        self._recargar_sesiones()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _crear_interfaz(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(8)

        # Encabezado: titulo centrado a todo el ancho + boton Exportar
        # flotante arriba a la derecha (fuera del layout para no desplazar
        # el titulo).
        self.lbl_titulo = QLabel("Historial de Sesiones", self)
        self.lbl_titulo.setObjectName("Title")
        layout.addWidget(self.lbl_titulo, alignment=Qt.AlignHCenter)

        self.btn_exportar = QPushButton("Exportar", self)
        self.btn_exportar.setObjectName("Success")
        self.btn_exportar.setIcon(qta.icon("mdi6.file-excel", color="white"))
        self.btn_exportar.clicked.connect(self._exportar_dia)
        self.btn_exportar.raise_()
        self._posicionar_export()

        subtitulo = QLabel("Selecciona una sesion para ver sus paros:", self)
        subtitulo.setObjectName("EstadoInfo")
        layout.addWidget(subtitulo, alignment=Qt.AlignHCenter)

        self.tree_sesiones = QTableWidget(0, 8, self)
        self.tree_sesiones.setHorizontalHeaderLabels(
            ["ID", "Operador", "Inicio", "Fin", "Cortes", "Estado", "Min",
             "Paros"]
        )
        # Operador se estira; el resto se ajusta a su contenido (sin anchos
        # fijos: columnas de un digito no deben ocupar el mismo espacio).
        self._config_tabla(self.tree_sesiones, col_stretch=(1,))
        self.tree_sesiones.itemSelectionChanged.connect(self._on_select_sesion)
        layout.addWidget(self.tree_sesiones, stretch=3)

        # Paros (izquierda) y trabajos (derecha), lado a lado.
        fila_detalle = QHBoxLayout()
        fila_detalle.setSpacing(12)

        col_paros = QVBoxLayout()
        col_paros.setSpacing(4)
        self.lbl_paros = QLabel("Paros de la sesion:", self)
        self.lbl_paros.setObjectName("HeaderLabel")
        col_paros.addWidget(self.lbl_paros)
        self.tree_paros = QTableWidget(0, 5, self)
        self.tree_paros.setHorizontalHeaderLabels(
            ["Causa", "Zona", "Inicio", "Fin", "Autorizó"]
        )
        # La causa recibe un ancho fijo AMPLIO (más espacio para leerla) y deja
        # desplazamiento lateral si el total excede el panel; inicio/fin/
        # autorizador al contenido. `Stretch` se adapta al ancho disponible y
        # recorta la causa sin poder desplazarse, por eso se usa Interactive.
        self._config_tabla(self.tree_paros, col_stretch=())
        header_paros = self.tree_paros.horizontalHeader()
        header_paros.setSectionResizeMode(0, QHeaderView.Interactive)
        self.tree_paros.setColumnWidth(0, 150)
        self.tree_paros.setColumnWidth(1, 110)
        col_paros.addWidget(self.tree_paros, stretch=2)
        fila_detalle.addLayout(col_paros, stretch=1)

        col_trabajos = QVBoxLayout()
        col_trabajos.setSpacing(4)
        self.lbl_trabajos = QLabel("Trabajos de la sesion:", self)
        self.lbl_trabajos.setObjectName("HeaderLabel")
        col_trabajos.addWidget(self.lbl_trabajos)
        self.tree_trabajos = QTableWidget(0, 7, self)
        self.tree_trabajos.setHorizontalHeaderLabels(
            ["Folio", "Parte", "Meta", "Cortados", "Fin", "Modalidad",
             "Estado"]
        )
        # Encabezados cortos para que TODO entre en el panel derecho; parte
        # se estira y el resto al contenido. Si el panel es muy angosto, las
        # columnas de la derecha se recorren por scroll lateral (nunca quedan
        # inaccesibles como con ResizeToContents sin cabida).
        self._config_tabla(self.tree_trabajos, col_stretch=(1,))
        col_trabajos.addWidget(self.tree_trabajos, stretch=2)
        fila_detalle.addLayout(col_trabajos, stretch=1)

        layout.addLayout(fila_detalle, stretch=2)

        btn_actualizar = QPushButton("Actualizar", self)
        btn_actualizar.clicked.connect(self._recargar_sesiones)
        layout.addWidget(btn_actualizar, alignment=Qt.AlignHCenter)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._posicionar_export()

    def _posicionar_export(self):
        """Boton Exportar flotante: alineado a la derecha del titulo sin
        ocupar espacio en el layout (no desplaza nada)."""
        btn = getattr(self, "btn_exportar", None)
        titulo = getattr(self, "lbl_titulo", None)
        if btn is None or titulo is None:
            return
        hint = btn.sizeHint()
        x = self.width() - hint.width() - 16
        y = titulo.y() + max(0, (titulo.height() - hint.height()) // 2)
        btn.setGeometry(x, y, hint.width(), hint.height())

    @staticmethod
    def _config_tabla(tabla, col_stretch=()):
        tabla.setSelectionBehavior(QAbstractItemView.SelectRows)
        tabla.setSelectionMode(QAbstractItemView.SingleSelection)
        tabla.setEditTriggers(QAbstractItemView.NoEditTriggers)
        tabla.verticalHeader().setVisible(False)
        tabla.setAlternatingRowColors(True)
        tabla.setShowGrid(False)
        header = tabla.horizontalHeader()
        header.setStretchLastSection(False)
        for col in range(tabla.columnCount()):
            modo = (
                QHeaderView.Stretch if col in col_stretch
                else QHeaderView.ResizeToContents
            )
            header.setSectionResizeMode(col, modo)
        header.setSectionsClickable(True)

    # ------------------------------------------------------------------
    # Datos
    # ------------------------------------------------------------------

    def _recargar_sesiones(self):
        self.tree_sesiones.setRowCount(0)
        for s in listar_sesiones():
            fila = self.tree_sesiones.rowCount()
            self.tree_sesiones.insertRow(fila)
            valores = (
                s["id"], s["nombre"], s["fecha_inicio"],
                s["fecha_fin"] or "En curso", s["total_cortes"],
                s["estado"], s["minutos"], s["num_paros"],
            )
            for col, valor in enumerate(valores):
                self.tree_sesiones.setItem(fila, col, QTableWidgetItem(str(valor)))
        self.lbl_paros.setText("Paros de la sesion:")
        self._limpiar_paros()
        self.lbl_trabajos.setText("Trabajos de la sesion:")
        self.tree_trabajos.setRowCount(0)

    def _on_select_sesion(self):
        fila = self.tree_sesiones.currentRow()
        if fila < 0:
            return
        sesion_id = int(self.tree_sesiones.item(fila, 0).text())
        operador = self.tree_sesiones.item(fila, 1).text()
        # De quien era la sesion, junto al detalle de paros.
        self.lbl_paros.setText(
            f"Paros de la sesion #{sesion_id} (operador: {operador}):"
        )
        self._recargar_paros(sesion_id)
        self.lbl_trabajos.setText(f"Trabajos de la sesion #{sesion_id}:")
        self._recargar_trabajos(sesion_id)

    def _recargar_trabajos(self, sesion_id):
        """Trabajos de la sesion POR SEGMENTO (folio x sesion): 'Cortados'
        es lo cortado en ESTA sesion para ese folio, 'Modalidad' el tipo de
        cierre de ese segmento y 'Estado' el del folio AL MOMENTO del
        segmento (no el actual)."""
        modalidad_nombre = {
            "normal": "Normal", "parcial": "Parcial",
            "folio": "Folio modificado",
        }
        self.tree_trabajos.setRowCount(0)
        for t in listar_trabajos_de_sesion(sesion_id):
            fila = self.tree_trabajos.rowCount()
            self.tree_trabajos.insertRow(fila)
            en_curso = not t["fecha_fin"]
            modalidad = (
                modalidad_nombre.get(t["modalidad"], t["modalidad"])
                if not en_curso else "En curso"
            )
            estado_seg = (
                t["estado_segmento"] if t["estado_segmento"]
                else ("En curso" if en_curso else t["estado"])
            )
            valores = (
                t["folio"], t["num_part"], t["cantidad_total"],
                t["cantidad_sesion"],
                t["fecha_fin"] or ("En curso" if t["estado"] == "Abierto"
                                   else "Sin registro"),
                modalidad,
                estado_seg,
            )
            for col, valor in enumerate(valores):
                self.tree_trabajos.setItem(
                    fila, col, QTableWidgetItem(str(valor))
                )

    def _recargar_paros(self, sesion_id):
        self.tree_paros.setRowCount(0)
        for p in obtener_paros_de_sesion(sesion_id):
            fila = self.tree_paros.rowCount()
            self.tree_paros.insertRow(fila)
            causa = p["descripcion"] if p["descripcion"] else "(sin causa registrada)"
            en_curso = not p["fin_paro"]
            autorizador = p["autorizador"] or (
                "Sin autorizar" if en_curso else "(sin registro)"
            )
            zona = p["zona"] if p["zona"] else ""
            self.tree_paros.setItem(fila, 0, QTableWidgetItem(causa))
            self.tree_paros.setItem(fila, 1, QTableWidgetItem(zona))
            self.tree_paros.setItem(fila, 2, QTableWidgetItem(p["inicio_paro"]))
            self.tree_paros.setItem(
                fila, 3, QTableWidgetItem("En curso" if en_curso else p["fin_paro"])
            )
            self.tree_paros.setItem(fila, 4, QTableWidgetItem(autorizador))

    def _limpiar_paros(self):
        self.tree_paros.setRowCount(0)

    # ------------------------------------------------------------------
    # Export por dia
    # ------------------------------------------------------------------

    def _pedir_fecha_export(self):
        """Dialogo de fecha para el export. Devuelve 'YYYY-MM-DD' o None."""
        dialogo = QDialog(self)
        dialogo.setWindowTitle("Exportar día")
        lay = QVBoxLayout(dialogo)
        lay.addWidget(QLabel("Selecciona el día a exportar:", dialogo))
        cal = QCalendarWidget(dialogo)
        hoy = QDate.currentDate()
        cal.setSelectedDate(hoy)
        cal.setMaximumDate(hoy)
        lay.addWidget(cal)
        fila = QHBoxLayout()
        fila.addStretch(1)
        btn_ok = QPushButton("Aceptar", dialogo)
        btn_ok.setObjectName("Success")
        btn_ok.clicked.connect(dialogo.accept)
        btn_no = QPushButton("Cancelar", dialogo)
        btn_no.clicked.connect(dialogo.reject)
        fila.addWidget(btn_ok)
        fila.addWidget(btn_no)
        lay.addLayout(fila)
        if dialogo.exec() != QDialog.Accepted:
            return None
        return cal.selectedDate().toString("yyyy-MM-dd")

    def _exportar_dia(self):
        from src import config

        fecha = self._pedir_fecha_export()
        if not fecha:
            return
        # Carpeta inicial: la ultima donde se guardo (persistida en
        # config.json como el tema); si no hay o ya no existe, Documentos.
        base = config.leer_config("export_dir", "") or ""
        import os

        if not base or not os.path.isdir(base):
            base = QStandardPaths.writableLocation(
                QStandardPaths.DocumentsLocation
            ) or ""
        destino_ini = (
            os.path.join(base, f"Sesiones_{fecha}.xlsx") if base
            else f"Sesiones_{fecha}.xlsx"
        )
        ruta, _ = QFileDialog.getSaveFileName(
            self, "Exportar día a Excel", destino_ini, "Excel (*.xlsx)"
        )
        if not ruta:
            return
        ok, mensaje, _stats = exportar_dia(fecha, ruta)
        if ok:
            # Recordar la carpeta para el proximo export.
            try:
                config.guardar_config("export_dir", os.path.dirname(ruta))
            except Exception:  # noqa: BLE001 - no debe opacar el exito
                log.warning("No se pudo guardar export_dir", exc_info=True)
        caja = QMessageBox(self)
        caja.setWindowTitle("Exportar día" if ok else "Sin datos")
        caja.setText(mensaje)
        caja.setIcon(QMessageBox.Information if ok else QMessageBox.Warning)
        caja.addButton("Aceptar", QMessageBox.AcceptRole)
        caja.exec()
        if not ok:
            log.info("Export día %s sin generar: %s", fecha, mensaje)
        else:
            log.info("Export día %s guardado en %s", fecha, ruta)

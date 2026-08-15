"""
style.py - Tema oscuro "chill" para la GUI en PySide6 (Qt).

Define los colores, la hoja de estilos QSS y helpers para aplicar estados
visuales a los widgets. Se aplica con `aplicar_estilo(app)` sobre el
QApplication (usa el estilo Fusion para que el QSS se renderice de forma
consistente en Windows).
"""

from PySide6.QtGui import QFont

FAMILIA_FUENTE = "Segoe UI"

COLOR_FONDO = "#14181f"
COLOR_SUPERFICIE = "#1c232e"
COLOR_SUPERFICIE_ELEVADA = "#232b39"
COLOR_BORDE = "#2e3846"
COLOR_TEXTO = "#e7eaf0"
COLOR_TEXTO_SECUNDARIO = "#9aa5b3"
COLOR_ACCENTE = "#6d7cff"
COLOR_ACCENTE_CLARO = "#8b97ff"
COLOR_EXITO = "#34d399"
COLOR_EXITO_CLARO = "#5eead4"
COLOR_ADVERTENCIA = "#fbbf24"
COLOR_ERROR = "#f87171"
COLOR_DESACTIVADO = "#3a4454"

# Superficie interior de modales/contenedores (mismo fondo que la tarjeta).
COLOR_FONDO_INTERIOR = COLOR_SUPERFICIE

# ESTILOS_ESTADO[estado] es el objectName QSS que se le asigna al widget
# cuando quiere mostrarse en ese estado de color (vease `aplicar_estado`).
ESTILOS_ESTADO = {
    "pendiente": "EstadoPendiente",
    "procesando": "EstadoProcesando",
    "exito": "EstadoExito",
    "error": "EstadoError",
    "info": "EstadoInfo",
}

HOJA_ESTILOS = """
* {
    font-family: "Segoe UI";
    font-size: 14px;
    color: #e7eaf0;
}

QWidget {
    background: #14181f;
}

/* ---- Encabezado y sidebar ---- */
QFrame#Header {
    background: #1c232e;
    border-bottom: 1px solid #2e3846;
}
QFrame#Sidebar {
    background: #1c232e;
    border-right: 1px solid #2e3846;
}
QFrame#Separador {
    background: #2e3846;
    border: none;
    max-height: 1px;
}

/* ---- Etiquetas ---- */
QLabel {
    background: transparent;
}
QLabel#Title {
    font-size: 24px;
    font-weight: 700;
    color: #e7eaf0;
}
QLabel#Big {
    font-size: 48px;
    font-weight: 700;
    color: #e7eaf0;
}
QLabel#HeaderLabel {
    font-size: 16px;
    font-weight: 600;
    color: #e7eaf0;
}
QLabel#EstadoPendiente, QLabel#EstadoProcesando {
    color: #fbbf24;
    font-weight: 600;
}
QLabel#EstadoExito {
    color: #34d399;
    font-weight: 600;
}
QLabel#EstadoError {
    color: #f87171;
    font-weight: 600;
}
QLabel#EstadoInfo {
    color: #9aa5b3;
}

/* ---- Botones ---- */
QPushButton {
    background: #6d7cff;
    color: #ffffff;
    border: none;
    border-radius: 12px;
    padding: 10px 20px;
    font-weight: 600;
}
QPushButton:hover {
    background: #8b97ff;
}
QPushButton:pressed {
    background: #5a68e8;
}
QPushButton:disabled {
    background: #3a4454;
    color: #6b7686;
}

QPushButton#Nav {
    background: transparent;
    color: #9aa5b3;
    text-align: left;
    padding: 10px 14px;
    border-radius: 10px;
    font-weight: 600;
}
QPushButton#Nav:hover {
    background: #232b39;
    color: #e7eaf0;
}
QPushButton#Nav:pressed {
    background: #2e3846;
}

/* Boton principal de poder: grande, redondo (PLAY/STOP). */
QPushButton#Power, QPushButton#PowerOn {
    border-radius: 52px;
    font-size: 42px;
    min-width: 104px;
    min-height: 104px;
    padding: 0;
}
QPushButton#Power {
    background: #f87171;
    color: #ffffff;
}
QPushButton#Power:hover {
    background: #fb8f8f;
}
QPushButton#Power:pressed {
    background: #ef5a5a;
}
QPushButton#PowerOn {
    background: #34d399;
    color: #0b1f18;
}
QPushButton#PowerOn:hover {
    background: #5eead4;
}
QPushButton#PowerOn:pressed {
    background: #27b585;
}

QPushButton#Success {
    background: #34d399;
    color: #0b1f18;
}
QPushButton#Success:hover {
    background: #5eead4;
}
QPushButton#Success:pressed {
    background: #27b585;
}

/* Botones de la cuadricula de causas de paro. */
QPushButton#Causa {
    background: #232b39;
    color: #e7eaf0;
    border: 1px solid #2e3846;
    border-radius: 10px;
    padding: 8px 12px;
    font-weight: 600;
}
QPushButton#Causa:hover {
    background: #2e3846;
}
QPushButton#Causa:pressed {
    background: #3a4454;
}
QPushButton#CausaSel {
    background: #34d399;
    color: #0b1f18;
    border: 1px solid #5eead4;
    border-radius: 10px;
    padding: 8px 12px;
    font-weight: 700;
}

/* ---- Entradas ---- */
QLineEdit {
    background: #232b39;
    border: 1px solid #2e3846;
    border-radius: 10px;
    padding: 8px 12px;
    selection-background-color: #6d7cff;
    selection-color: #ffffff;
}
QLineEdit:focus {
    border: 1px solid #6d7cff;
}

/* ---- Combobox ---- */
QComboBox {
    background: #232b39;
    border: 1px solid #2e3846;
    border-radius: 10px;
    padding: 7px 12px;
    min-height: 20px;
}
QComboBox:hover {
    border: 1px solid #6d7cff;
}
QComboBox::drop-down {
    border: none;
    width: 26px;
}
QComboBox::down-arrow {
    image: none;
    border-left: 5px solid transparent;
    border-right: 5px solid transparent;
    border-top: 6px solid #9aa5b3;
    margin-right: 8px;
}
QComboBox QAbstractItemView {
    background: #1c232e;
    border: 1px solid #2e3846;
    selection-background-color: #6d7cff;
    selection-color: #ffffff;
    outline: 0;
}

/* ---- Tablas ---- */
QTableWidget, QTableView {
    background: #1c232e;
    alternate-background-color: #202835;
    border: 1px solid #2e3846;
    border-radius: 10px;
    gridline-color: transparent;
    selection-background-color: #6d7cff;
    selection-color: #ffffff;
    outline: 0;
}
QTableWidget::item {
    padding: 4px 8px;
}
QHeaderView::section {
    background: #232b39;
    color: #9aa5b3;
    border: none;
    padding: 8px 10px;
    font-weight: 600;
}
QTableCornerButton::section {
    background: #232b39;
    border: none;
}

/* ---- Listas (permisos con checkbox) ---- */
QListView, QListWidget {
    background: #1c232e;
    border: 1px solid #2e3846;
    border-radius: 10px;
    outline: 0;
}
QListView:disabled, QListWidget:disabled {
    background: #1a2029;
    color: #6b7686;
}
QCheckBox {
    background: transparent;
    spacing: 8px;
    color: #e7eaf0;
}

/* ---- Pestanas ---- */
QTabWidget::pane {
    border: 1px solid #2e3846;
    border-radius: 12px;
    background: #161b23;
    top: -1px;
}
QTabBar::tab {
    background: transparent;
    color: #9aa5b3;
    padding: 10px 24px;
    border-top-left-radius: 10px;
    border-top-right-radius: 10px;
    margin-right: 4px;
    font-weight: 600;
}
QTabBar::tab:hover {
    background: #202835;
    color: #e7eaf0;
}
QTabBar::tab:selected {
    background: #232b39;
    color: #e7eaf0;
}

/* ---- Modales ---- */
QDialog, QMessageBox {
    background: #14181f;
}

/* ---- Scrollbars ---- */
QScrollBar:vertical {
    background: transparent;
    width: 12px;
    margin: 2px;
}
QScrollBar::handle:vertical {
    background: #2e3846;
    border-radius: 6px;
    min-height: 30px;
}
QScrollBar::handle:vertical:hover {
    background: #3a4454;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    background: transparent;
}
QScrollBar:horizontal {
    background: transparent;
    height: 12px;
    margin: 2px;
}
QScrollBar::handle:horizontal {
    background: #2e3846;
    border-radius: 6px;
    min-width: 30px;
}
QScrollBar::handle:horizontal:hover {
    background: #3a4454;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0;
}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {
    background: transparent;
}

/* ---- Tooltips ---- */
QToolTip {
    background: #232b39;
    color: #e7eaf0;
    border: 1px solid #2e3846;
    padding: 4px 8px;
}
"""


def aplicar_estado(widget, estado):
    """Cambia el color de estado de un widget (pendiente/exito/error/...)."""
    widget.setObjectName(ESTILOS_ESTADO.get(estado, "EstadoInfo"))
    widget.style().unpolish(widget)
    widget.style().polish(widget)


def aplicar_estilo_boton(boton, nombre):
    """Asigna un estilo QSS a un boton por su objectName (ej. Power/PowerOn)."""
    boton.setObjectName(nombre)
    boton.style().unpolish(boton)
    boton.style().polish(boton)


def aplicar_estilo(app):
    """Aplica el tema completo al QApplication (Fusion + QSS + fuente)."""
    app.setStyle("Fusion")
    app.setFont(QFont(FAMILIA_FUENTE, 10))
    app.setStyleSheet(HOJA_ESTILOS)

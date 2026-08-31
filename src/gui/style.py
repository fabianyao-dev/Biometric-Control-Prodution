"""
style.py - Tema de la GUI en PySide6 (Qt): oscuro y claro intercambiables.

Define las paletas de colores, la plantilla QSS y helpers para aplicar
estados visuales a los widgets. Se aplica con `aplicar_estilo(app)` sobre el
QApplication (usa el estilo Fusion para que el QSS se renderice de forma
consistente en Windows). El tema activo se cambia EN CALIENTE con
`cambiar_tema(app, tema)`: Qt re-pinta todo al reaplicar la hoja de estilos;
los widgets pintados a mano consultan los colores con `color(...)` para que
el cambio les afecte tambien.
"""

from PySide6.QtGui import QFont

FAMILIA_FUENTE = "Segoe UI"

# ---------------------------------------------------------------------------
# Paletas
# ---------------------------------------------------------------------------
# Cada clave se usa tanto en la plantilla QSS (@clave@) como desde codigo via
# color(clave). Agregar un color nuevo = agregarlo aqui y usarlo donde haga
# falta; nada de hex sueltos en los widgets.
PALETAS = {
    "oscuro": {
        "fondo": "#14181f",
        "superficie": "#1c232e",
        "superficie_alt": "#202835",
        "elevada": "#232b39",
        "borde": "#2e3846",
        "texto": "#e7eaf0",
        "texto_sec": "#9aa5b3",
        "accento": "#6d7cff",
        "accento_hover": "#8b97ff",
        "accento_pressed": "#5a68e8",
        "exito": "#34d399",
        "exito_hover": "#5eead4",
        "exito_pressed": "#27b585",
        "sobre_exito": "#0b1f18",
        "advertencia": "#fbbf24",
        "advertencia_hover": "#fcd34d",
        "sobre_advertencia": "#14181f",
        "mantenimiento": "#fb923c",
        "mantenimiento_hover": "#fdba74",
        "amarillo": "#fde047",
        "error": "#f87171",
        "error_hover": "#fb8f8f",
        "error_pressed": "#ef5a5a",
        "deshabilitado_bg": "#3a4454",
        "deshabilitado_texto": "#6b7686",
        "lista_disabled_bg": "#1a2029",
        "tab_pane": "#161b23",
        "blanco": "#ffffff",
        # Tablero de contadores: marcador LED fisico (marco oscuro, pantalla
        # negra y digitos rojos de 7 segmentos), igual en ambos temas.
        "tablero_fondo": "#161b22",
        "tablero_borde": "#3a4450",
        "tablero_etiqueta": "#8fa0b5",
        "tablero_pantalla": "#000000",
        "tablero_segmento_on": "#ff453a",
        "tablero_segmento_off": "#2a100c",
        "tablero_info": "#ffb84d",
    },
    "claro": {
        "fondo": "#eef1f6",
        "superficie": "#ffffff",
        "superficie_alt": "#f2f5f9",
        "elevada": "#e9edf4",
        "borde": "#cdd5e0",
        "texto": "#1d2634",
        "texto_sec": "#5d6b80",
        "accento": "#5566f0",
        "accento_hover": "#7582ff",
        "accento_pressed": "#4050d8",
        "exito": "#0ea771",
        "exito_hover": "#23c48b",
        "exito_pressed": "#0b8a5e",
        "sobre_exito": "#ffffff",
        "advertencia": "#b45309",
        "advertencia_hover": "#d97706",
        "sobre_advertencia": "#ffffff",
        "mantenimiento": "#c2410c",
        "mantenimiento_hover": "#ea580c",
        "amarillo": "#ca8a04",
        "error": "#dc2626",
        "error_hover": "#ef4444",
        "error_pressed": "#b91c1c",
        "deshabilitado_bg": "#d7dde7",
        "deshabilitado_texto": "#93a0b4",
        "lista_disabled_bg": "#f3f5f9",
        "tab_pane": "#fafbfd",
        "blanco": "#ffffff",
        # Tablero de contadores: el marco cambia de tono, la pantalla y los
        # segmentos LED se mantienen (metofora del marcador fisico).
        "tablero_fondo": "#1e252f",
        "tablero_borde": "#46505f",
        "tablero_etiqueta": "#9aa8bb",
        "tablero_pantalla": "#000000",
        "tablero_segmento_on": "#ff5548",
        "tablero_segmento_off": "#2a100c",
        "tablero_info": "#ffc35c",
    },
}

TEMA_POR_DEFECTO = "oscuro"
tema_activo = TEMA_POR_DEFECTO


def color(clave):
    """Color del tema ACTIVO por nombre (los widgets pintados a mano deben
    consultar aqui DENTRO de paintEvent, no cachear el valor)."""
    return PALETAS[tema_activo].get(clave, PALETAS[TEMA_POR_DEFECTO][clave])


def temas_disponibles():
    return tuple(PALETAS.keys())


# Alias de compatibilidad con el tema oscuro original (codigo viejo que
# importaba constantes); el codigo NUEVO debe usar color(...).
_p = PALETAS["oscuro"]
COLOR_FONDO = _p["fondo"]
COLOR_SUPERFICIE = _p["superficie"]
COLOR_SUPERFICIE_ELEVADA = _p["elevada"]
COLOR_BORDE = _p["borde"]
COLOR_TEXTO = _p["texto"]
COLOR_TEXTO_SECUNDARIO = _p["texto_sec"]
COLOR_ACCENTE = _p["accento"]
COLOR_ACCENTE_CLARO = _p["accento_hover"]
COLOR_EXITO = _p["exito"]
COLOR_EXITO_CLARO = _p["exito_hover"]
COLOR_ADVERTENCIA = _p["advertencia"]
COLOR_ERROR = _p["error"]
COLOR_DESACTIVADO = _p["deshabilitado_bg"]

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

PLANTILLA_QSS = """
* {
    font-family: "@fuente@";
    font-size: 17px;
    color: @texto@;
}

QWidget {
    background: @fondo@;
}

/* ---- Encabezado y sidebar ---- */
QFrame#Header {
    background: @superficie@;
    border-bottom: 1px solid @borde@;
}
QFrame#Sidebar {
    background: @superficie@;
    border-right: 1px solid @borde@;
}
QFrame#Separador {
    background: @borde@;
    border: none;
    max-height: 1px;
}

/* ---- Etiquetas (jerarquia tipografica) ---- */
QLabel {
    background: transparent;
}
QLabel#Title {
    font-size: 32px;
    font-weight: 700;
    color: @texto@;
}
QLabel#Big {
    font-size: 64px;
    font-weight: 700;
    color: @texto@;
}
QLabel#HeaderLabel {
    font-size: 22px;
    font-weight: 600;
    color: @texto@;
}
QLabel#EstadoPendiente, QLabel#EstadoProcesando {
    color: @advertencia@;
    font-weight: 600;
}
QLabel#EstadoExito {
    color: @exito@;
    font-weight: 600;
}
QLabel#EstadoError {
    color: @error@;
    font-weight: 600;
}
QLabel#EstadoInfo {
    color: @texto_sec@;
}

/* ---- Tablero de contadores (marcador LED de planta) ---- */
QFrame#Tablero {
    background: @tablero_fondo@;
    border: 2px solid @tablero_borde@;
    border-radius: 16px;
}
QLabel#TableroEtiqueta {
    background: transparent;
    color: @tablero_etiqueta@;
    font-size: 20px;
    font-weight: 700;
}
QLabel#TableroInfo {
    background: transparent;
    color: @tablero_info@;
    font-family: "Consolas";
    font-size: 24px;
    font-weight: 700;
}

/* ---- Botones ---- */
QPushButton {
    background: @accento@;
    color: @blanco@;
    border: none;
    border-radius: 12px;
    padding: 14px 30px;
    font-size: 18px;
    font-weight: 700;
}
QPushButton:hover {
    background: @accento_hover@;
}
QPushButton:pressed {
    background: @accento_pressed@;
}
QPushButton:disabled {
    background: @deshabilitado_bg@;
    color: @deshabilitado_texto@;
}

QPushButton#Nav {
    background: transparent;
    color: @texto_sec@;
    text-align: left;
    padding: 12px 18px;
    border-radius: 10px;
    font-size: 18px;
    font-weight: 700;
}
QPushButton#Nav:hover {
    background: @elevada@;
    color: @texto@;
}
QPushButton#Nav:pressed {
    background: @borde@;
}

/* ---- Botones de ICONO del header (sesion, tema, hamburguesa): cuadrados
   y con contenido centrado; el #Nav del sidebar es texto a la izquierda. */
QPushButton#NavIcono {
    background: transparent;
    color: @texto_sec@;
    text-align: center;
    padding: 0px;
    border-radius: 10px;
}
QPushButton#NavIcono:hover {
    background: @elevada@;
    color: @texto@;
}
QPushButton#NavIcono:pressed {
    background: @borde@;
}

/* ---- Boton de SESION del header: icono + texto ("Iniciar sesion" o el
   nombre del operador) en una sola pieza. ---- */
QPushButton#NavSesion {
    background: transparent;
    color: @texto@;
    text-align: center;
    padding: 8px 14px;
    border-radius: 10px;
    font-size: 14px;
    font-weight: 600;
}
QPushButton#NavSesion:hover {
    background: @elevada@;
}
QPushButton#NavSesion:pressed {
    background: @borde@;
}

/* ---- Linea de ESTADO del pie de Inicio: discreta/difuminada, sin pastilla
   de color; solo texto secundario pequeno sobre el fondo. ---- */
QLabel#ResumenEstado {
    background: transparent;
    color: @texto_sec@;
    font-size: 13px;
    padding: 4px 10px;
}

/* ---- Boton de advertencias del header (notificaciones) ---- */
QPushButton#Aviso {
    background: transparent;
    color: @texto_sec@;
    border: 1px solid @borde@;
    border-radius: 10px;
    padding: 6px 8px;
    font-size: 18px;
    font-weight: 600;
}
QPushButton#Aviso:hover {
    background: @elevada@;
    color: @texto@;
}
QPushButton#AvisoActivo {
    background: @advertencia@;
    color: @sobre_advertencia@;
    border: 1px solid @advertencia@;
    border-radius: 10px;
    padding: 6px 8px;
    font-size: 18px;
    font-weight: 700;
}
QPushButton#AvisoActivo:hover {
    background: @advertencia_hover@;
}

/* Panel flotante de advertencias (dropdown del header). */
QFrame#PanelAvisos {
    background: @superficie@;
    border: 1px solid @borde@;
    border-radius: 12px;
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
    background: @error@;
    color: @blanco@;
}
QPushButton#Power:hover {
    background: @error_hover@;
}
QPushButton#Power:pressed {
    background: @error_pressed@;
}
QPushButton#PowerOn {
    background: @exito@;
    color: @sobre_exito@;
}
QPushButton#PowerOn:hover {
    background: @exito_hover@;
}
QPushButton#PowerOn:pressed {
    background: @exito_pressed@;
}

QPushButton#Success {
    background: @exito@;
    color: @sobre_exito@;
}
QPushButton#Success:hover {
    background: @exito_hover@;
}
QPushButton#Success:pressed {
    background: @exito_pressed@;
}

/* Accion peligrosa/destructiva (p. ej. "Salir de mantenimiento"). */
QPushButton#Danger {
    background: @error@;
    color: @blanco@;
    border: none;
}
QPushButton#Danger:hover {
    background: @error_hover@;
}
QPushButton#Danger:pressed {
    background: @error_pressed@;
}
QPushButton#Danger:disabled {
    background: @deshabilitado_bg@;
    color: @deshabilitado_texto@;
}

/* Botones de la cuadricula de causas de paro. */
QPushButton#Causa {
    background: @elevada@;
    color: @texto@;
    border: 1px solid @borde@;
    border-radius: 10px;
    padding: 8px 12px;
    font-weight: 600;
}
QPushButton#Causa:hover {
    background: @borde@;
}
QPushButton#Causa:pressed {
    background: @deshabilitado_bg@;
}
QPushButton#CausaSel {
    background: @exito@;
    color: @sobre_exito@;
    border: 1px solid @exito_hover@;
    border-radius: 10px;
    padding: 8px 12px;
    font-weight: 700;
}

/* ---- Entradas ---- */
QLineEdit {
    background: @elevada@;
    border: 1px solid @borde@;
    border-radius: 10px;
    padding: 8px 12px;
    selection-background-color: @accento@;
    selection-color: @blanco@;
}
QLineEdit:focus {
    border: 1px solid @accento@;
}

/* ---- Combobox ---- */
QComboBox {
    background: @elevada@;
    border: 1px solid @borde@;
    border-radius: 10px;
    padding: 7px 12px;
    min-height: 20px;
}
QComboBox:hover {
    border: 1px solid @accento@;
}
QComboBox::drop-down {
    border: none;
    width: 26px;
}
QComboBox::down-arrow {
    image: none;
    border-left: 5px solid transparent;
    border-right: 5px solid transparent;
    border-top: 6px solid @texto_sec@;
    margin-right: 8px;
}
QComboBox QAbstractItemView {
    background: @superficie@;
    border: 1px solid @borde@;
    selection-background-color: @accento@;
    selection-color: @blanco@;
    outline: 0;
}

/* ---- Tablas ---- */
QTableWidget, QTableView {
    background: @superficie@;
    alternate-background-color: @superficie_alt@;
    border: 1px solid @borde@;
    border-radius: 10px;
    gridline-color: transparent;
    selection-background-color: @accento@;
    selection-color: @blanco@;
    outline: 0;
}
QTableWidget::item {
    padding: 4px 8px;
}
QHeaderView::section {
    background: @elevada@;
    color: @texto_sec@;
    border: none;
    padding: 8px 10px;
    font-weight: 600;
}
QTableCornerButton::section {
    background: @elevada@;
    border: none;
}

/* ---- Listas (permisos con checkbox) ---- */
QListView, QListWidget {
    background: @superficie@;
    border: 1px solid @borde@;
    border-radius: 10px;
    outline: 0;
}
QListView:disabled, QListWidget:disabled {
    background: @lista_disabled_bg@;
    color: @deshabilitado_texto@;
}
QCheckBox {
    background: transparent;
    spacing: 8px;
    color: @texto@;
}

/* ---- Pestanas ---- */
QTabWidget::pane {
    border: 1px solid @borde@;
    border-radius: 12px;
    background: @tab_pane@;
    top: -1px;
}
QTabBar::tab {
    background: transparent;
    color: @texto_sec@;
    padding: 10px 24px;
    border-top-left-radius: 10px;
    border-top-right-radius: 10px;
    margin-right: 4px;
    font-weight: 600;
}
QTabBar::tab:hover {
    background: @superficie_alt@;
    color: @texto@;
}
QTabBar::tab:selected {
    background: @elevada@;
    color: @texto@;
}

/* ---- Modales ---- */
QDialog, QMessageBox {
    background: @fondo@;
}

/* ---- Scrollbars ---- */
QScrollBar:vertical {
    background: transparent;
    width: 12px;
    margin: 2px;
}
QScrollBar::handle:vertical {
    background: @borde@;
    border-radius: 6px;
    min-height: 30px;
}
QScrollBar::handle:vertical:hover {
    background: @deshabilitado_bg@;
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
    background: @borde@;
    border-radius: 6px;
    min-width: 30px;
}
QScrollBar::handle:horizontal:hover {
    background: @deshabilitado_bg@;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0;
}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {
    background: transparent;
}

/* ---- Tooltips ---- */
QToolTip {
    background: @elevada@;
    color: @texto@;
    border: 1px solid @borde@;
    padding: 4px 8px;
}
"""


def hoja_estilos(tema=None):
    """Genera la hoja QSS sustituyendo @claves@ por la paleta del tema."""
    paleta = dict(PALETAS.get(tema or tema_activo, PALETAS[tema_activo]))
    paleta.setdefault("fuente", FAMILIA_FUENTE)
    hoja = PLANTILLA_QSS
    for clave, valor in paleta.items():
        hoja = hoja.replace(f"@{clave}@", valor)
    return hoja


# Compatibilidad: la hoja del tema oscuro tal cual (quien la necesite como
# constante).
HOJA_ESTILOS = hoja_estilos("oscuro")


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


def aplicar_estilo(app, tema=None):
    """Aplica el tema completo al QApplication (Fusion + QSS + fuente)."""
    global tema_activo
    if tema in PALETAS:
        tema_activo = tema
    app.setStyle("Fusion")
    app.setFont(QFont(FAMILIA_FUENTE, 10))
    app.setStyleSheet(hoja_estilos())


def cambiar_tema(app, tema):
    """Cambia el tema EN CALIENTE y repinta todo el arbol de widgets."""
    return aplicar_estilo(app, tema)

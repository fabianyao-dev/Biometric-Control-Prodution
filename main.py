"""
main.py - Punto de entrada del sistema de control biometrico.

Orquesta:
    - Instancias compartidas: BiometricService, controlador HAL (Modbus TCP
      o SimulacionController) y la BD.
    - Header con boton hamburguesa que despliega un panel lateral con la
      navegacion: Inicio, Sesiones y Administracion.
    - Shutdown seguro: siempre llama controlador.cleanup() al salir (manual o
      error).

Los hilos secundarios nunca tocan los widgets; se comunican por
queue.Queue() drenada en el hilo principal (QTimer).
"""

import logging
import os
import sys

from PySide6.QtCore import QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from src.logging_config import configurar_logging

configurar_logging()

from src import config
from src.database import (
    init_db,
    listar_fmds,
    obtener_rol_operador,
    roles_con_permiso,
    rol_tiene_permiso_operador,
)
from src.gui.admin_view import AdminView
from src.gui.huella_modal import HuellaModal
from src.gui.inicio_view import InicioView
from src.gui.notificaciones import IndicadorAdvertencias
from src.gui.sessions_view import SessionsView
from src.gui import style
from src.gui.util import icono_svg
from src.hardware.biometric_service import BiometricService
from src.hardware.modbus_controller import ModbusController
from src.hardware.simulacion_controller import SimulacionController

log = logging.getLogger(__name__)

# Icono "light_mode" de Material Symbols (path oficial,
# google/material-design-icons): sol, para pasar a tema claro.
SVG_TEMA_CLARO = """\
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="22" height="22">\
<path fill="{color}" d="M12 7c-2.76 0-5 2.24-5 5s2.24 5 5 5 5-2.24 5-5-2.24-5-5-5zM2 \
13h2c.55 0 1-.45 1-1s-.45-1-1-1H2c-.55 0-1 .45-1 1s.45 1 1 1zm18 0h2c.55 0 1-.45 \
1-1s-.45-1-1-1h-2c-.55 0-1 .45-1 1s.45 1 1 1zM11 2v2c0 .55.45 1 1 1s1-.45 \
1-1V2c0-.55-.45-1-1-1s-1 .45-1 1zm0 18v2c0 .55.45 1 1 1s1-.45 1-1v-2c0-.55-.45-1-1-1s-1 \
.45-1 1zM5.99 4.58c-.39-.39-1.03-.39-1.41 0-.39.39-.39 1.03 0 1.41l1.06 1.06c.39.39 \
1.03.39 1.41 0s.39-1.03 0-1.41L5.99 4.58zm12.37 12.37c-.39-.39-1.03-.39-1.41 \
0-.39.39-.39 1.03 0 1.41l1.06 1.06c.39.39 1.03.39 1.41 0 .39-.39.39-1.03 0-1.41l-1.06-1.06zm1.06-10.96c.39-.39 \
.39-1.03 0-1.41-.39-.39-1.03-.39-1.41 0l-1.06 1.06c-.39.39-.39 1.03 0 1.41s1.03.39 \
1.41 0l1.06-1.06zM7.05 18.36c.39-.39.39-1.03 0-1.41-.39-.39-1.03-.39-1.41 \
0l-1.06 1.06c-.39.39-.39 1.03 0 1.41s1.03.39 1.41 0l1.06-1.06z"/></svg>
"""

# Icono "dark_mode" de Material Symbols: luna, para pasar a tema oscuro.
SVG_TEMA_OSCURO = """\
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="22" height="22">\
<path fill="{color}" d="M12.01 12c0-3.57 2.2-6.62 5.31-7.87.89-.36.75-1.69-.19-1.9-1.56-.35-3.23-.33-4.88.06C8.01 \
3.16 4.79 6.54 4.11 10.8c-.98 6.09 3.76 11.44 9.81 11.44 1.85 0 3.66-.51 5.23-1.47.82-.5.67-1.77-.29-2.05-4.02-1.17-6.85-4.9-6.85-9.22z"/></svg>
"""

def _ruta_recurso(nombre):
    """Ruta a un recurso empaquetado. Con PyInstaller los assets viven en
    el dir temporal (`_MEIPASS`) o junto al exe (onedir); en dev, en la raiz.
    """
    if getattr(sys, "frozen", False):
        # _MEIPASS es el directorio temporal donde PyInstaller descomprime todo
        base = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    else:
        # En desarrollo, la ruta es relativa a este script (main.py)
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, "assets", nombre)


def crear_controlador():
    """Fabrica del HAL: Modbus TCP si hay MODBUS_HOST, si no SimulacionController.

    En la PC Fanless Windows se configura MODBUS_HOST en .env y la planta
    maneja reles y contador via el modulo Advantech. Sin MODBUS_HOST (o en
    simulacion) se usa SimulacionController, que corre en simulacion (sin
    hardware).
    """
    if config.MODBUS_CONFIG["host"]:
        return ModbusController()
    return SimulacionController()


class App(QMainWindow):
    def __init__(self):
        super().__init__()
        log.info("Iniciando aplicacion biometria")
        self.setWindowTitle("Sistema de Control Biometrico - Planta de Corte")
        try:
            # Intenta cargar el ícono de la aplicación desde los assets.
            # Si falla (ej: no existe el archivo), usa el ícono por defecto de Qt.
            ruta_ico = _ruta_recurso("logo.ico")
            self.setWindowIcon(QIcon(ruta_ico))
            # Tambien establecerlo en la QApplication para el icono de la barra de tareas
            # y otros contextos del sistema.
            app.setWindowIcon(QIcon(ruta_ico))
        except Exception as e:
            log.warning("No se pudo cargar el ícono %s: %s", ruta_ico, e)
        self.resize(1152, 648)

        self.biometrico = BiometricService()
        self.controlador = crear_controlador()

        self.vistas = {}
        self.vista_actual = None
        self.btn_sidebar = {}

        self._crear_contenido()
        self._crear_header()
        self._crear_sidebar(opciones=[
            ("inicio", "Inicio"),
            ("sesiones", "Sesiones"),
            ("admin", "Administracion"),
        ])
        self.mostrar_vista("inicio")

        # Indicador de advertencias: estado de lector, HAL y operadores,
        # refrescado en segundo plano (no interfiere con la GUI).
        self._timer_avisos = QTimer(self)
        self._timer_avisos.setInterval(3000)
        self._timer_avisos.timeout.connect(self._revisar_avisos)
        self._timer_avisos.start()
        self._revisar_avisos()

        # Siempre en pantalla completa; desactivar con BIOMETRICO_KIOSKO=0.
        self.kiosko = os.environ.get("BIOMETRICO_KIOSKO") != "0"
        if self.kiosko:
            log.info("Modo kiosco activado")

    # ------------------------------------------------------------------
    # Header + hamburguesa
    # ------------------------------------------------------------------

    def _crear_header(self):
        lay = QHBoxLayout(self.header)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(8)

        self.btn_hamburguesa = QPushButton("\u2630", self.header)
        self.btn_hamburguesa.setObjectName("Nav")
        self.btn_hamburguesa.setFixedWidth(44)
        self.btn_hamburguesa.clicked.connect(self._toggle_sidebar)
        lay.addWidget(self.btn_hamburguesa)

        titulo = QLabel("Control Biometrico de Produccion", self.header)
        titulo.setObjectName("HeaderLabel")
        lay.addWidget(titulo)
        lay.addStretch(1)

        self.btn_advertencias = IndicadorAdvertencias(self.header)
        lay.addWidget(self.btn_advertencias)

        # Tema claro/oscuro: cambia en caliente y persiste en config.json.
        self.btn_tema = QPushButton(self.header)
        self.btn_tema.setObjectName("Nav")
        self.btn_tema.setFixedWidth(44)
        self.btn_tema.clicked.connect(self._alternar_tema)
        self._refrescar_boton_tema()
        lay.addWidget(self.btn_tema)

        btn_salir = QPushButton("Salir", self.header)
        btn_salir.setObjectName("Nav")
        btn_salir.clicked.connect(self._salir)
        lay.addWidget(btn_salir)

    # ------------------------------------------------------------------
    # Tema claro/oscuro
    # ------------------------------------------------------------------

    def _alternar_tema(self):
        nuevo = "claro" if style.tema_activo == "oscuro" else "oscuro"
        style.cambiar_tema(QApplication.instance(), nuevo)
        try:
            config.guardar_config("tema", nuevo)
        except Exception:  # noqa: BLE001 - el tema no debe tumbar la app
            log.warning("No se pudo guardar el tema en config.json",
                        exc_info=True)
        self._refrescar_boton_tema()
        # Regenera de inmediato los iconos SVG del indicador de avisos con
        # los colores del tema nuevo (si no, esperarian al siguiente poll).
        self._revisar_avisos()

    def _refrescar_boton_tema(self):
        # Iconos SVG (Material Symbols), nunca emojis: el glifo Unicode sale
        # distinto segun la fuente del sistema.
        if style.tema_activo == "oscuro":
            self.btn_tema.setIcon(icono_svg(SVG_TEMA_CLARO,
                                            style.color("texto_sec")))
            self.btn_tema.setToolTip("Cambiar a tema claro")
        else:
            self.btn_tema.setIcon(icono_svg(SVG_TEMA_OSCURO,
                                            style.color("texto")))
            self.btn_tema.setToolTip("Cambiar a tema oscuro")

    # ------------------------------------------------------------------
    # Advertencias del sistema (lector, HAL, operadores)
    # ------------------------------------------------------------------

    def _revisar_avisos(self):
        """Recalcula las advertencias operativas y actualiza el boton.

        Mismas condiciones que el resto de la app: biometria disponible,
        lector fisico detectado, HAL en simulacion y sin operadores reales
        (listar_fmds vacio, lo que deja entrar al 'Operador Temporal (dev)').
        """
        avisos = []

        # Lector: distinguir dos fallos distintos - driver/SDK ausente
        # (biometrico.disponible=False) y lector fisico desconectado del USB
        # (disponible=True pero sin dispositivo enumerado).
        if not getattr(self.biometrico, "disponible", False):
            avisos.append(
                ("Biometria no disponible",
                 "El SDK de DigitalPersona no esta disponible (driver "
                 "ausente).")
            )
        else:
            try:
                lector_ok = bool(
                    getattr(self.biometrico, "lector_presente", lambda: True)()
                )
            except Exception:  # noqa: BLE001 - nunca debe crashear la UI
                log.error("No se pudo consultar el lector biometrico",
                          exc_info=True)
                lector_ok = True
            if not lector_ok:
                avisos.append(
                    ("Lector biometrico no detectado",
                     "El lector no esta conectado; revisa el cable USB o el "
                     "driver de DigitalPersona.")
                )

        en_simulacion = getattr(
            self.controlador, "en_simulacion", lambda: True
        )()
        if en_simulacion:
            avisos.append(
                ("Control en simulacion",
                 "Sin modulo Modbus real (MODBUS_HOST vacio o "
                 "MODBUS_SIMULACION=1).")
            )
        else:
            conectado = getattr(self.controlador, "conectado", None)
            if conectado is not None and not conectado():
                avisos.append(
                    ("Sin comunicacion con el modulo Modbus",
                     "El modulo no responde; se reintenta en segundo plano.")
                )

        try:
            sin_operadores = not listar_fmds(activos_solo=True)
        except Exception:  # noqa: BLE001 - nunca debe crashear la UI
            sin_operadores = False
        if sin_operadores:
            avisos.append(
                ("Sin operadores registrados",
                 "Acceso automatico con 'Operador Temporal (dev)'.")
            )

        self.btn_advertencias.set_advertencias(avisos)

    # ------------------------------------------------------------------
    # Sidebar lateral (ocultable con la hamburguesa)
    # ------------------------------------------------------------------

    def _crear_sidebar(self, opciones):
        self.sidebar = QFrame(self._cuerpo)
        self.sidebar.setObjectName("Sidebar")
        self.sidebar.setFixedWidth(200)
        sv = QVBoxLayout(self.sidebar)
        sv.setContentsMargins(8, 12, 8, 12)
        sv.setSpacing(4)
        for nombre, texto in opciones:
            btn = QPushButton(texto, self.sidebar)
            btn.setObjectName("Nav")
            btn.clicked.connect(lambda checked=False, n=nombre: self._ir_a(n))
            sv.addWidget(btn)
            self.btn_sidebar[nombre] = btn
        sv.addStretch(1)

        # Se inserta antes del contenido para quedar a la izquierda.
        self._cuerpo_layout.insertWidget(0, self.sidebar)
        self._sidebar_visible = True
        self._actualizar_sidebar()

    def _toggle_sidebar(self):
        self._sidebar_visible = not self._sidebar_visible
        self._actualizar_sidebar()

    def _actualizar_sidebar(self):
        self.sidebar.setVisible(self._sidebar_visible)

    def _ir_a(self, nombre):
        # Vistas protegidas por permiso de rol: se valida la huella antes de
        # entrar. Los permisos se gestionan en Administracion, no en codigo.
        if nombre == "sesiones":
            self._navegar_con_huella(nombre, "acceso_sesiones")
            return
        if nombre == "admin":
            self._navegar_con_huella(nombre, "acceso_admin")
            return
        self.mostrar_vista(nombre)
        self._sidebar_visible = False
        self._actualizar_sidebar()

    def _navegar_con_huella(self, nombre, permiso):
        """Pide la huella y solo navega si el rol del operador tiene el
        permiso solicitado.

        Si la persona no tiene el permiso, el modal muestra el rechazo y
        sigue pidiendo huella hasta que ingrese alguien autorizado o se
        cancele.
        """
        etiqueta = {"sesiones": "SESIONES", "admin": "ADMINISTRACION"}.get(
            nombre, nombre
        )
        permitidos = " o ".join(roles_con_permiso(permiso)) or "ningun rol"

        def validador(op_id, nombre_op, causa_id):
            if rol_tiene_permiso_operador(op_id, permiso):
                return True, None
            rol = obtener_rol_operador(op_id)
            return False, (
                f"Acceso denegado para {nombre_op} (rol: {rol or 'sin rol'}). "
                f"Solo {permitidos} puede entrar a {etiqueta}."
            )

        def navegar(op_id, nombre_op, causa_id):
            log.info("Acceso concedido: %s (%s) entra a %s",
                     nombre_op, obtener_rol_operador(op_id), etiqueta)
            self.mostrar_vista(nombre)
            self._sidebar_visible = False
            self._actualizar_sidebar()

        modal = HuellaModal(
            self,
            self.biometrico,
            titulo=f"ACCESO {etiqueta}",
            mensaje="Coloca tu huella para verificar tu rol.",
            validador=validador,
            on_autenticado=navegar,
        )
        modal.exec()

    # ------------------------------------------------------------------
    # Contenido
    # ------------------------------------------------------------------

    def _crear_contenido(self):
        self._central = QWidget(self)
        self.setCentralWidget(self._central)

        # Layout vertical: header arriba, cuerpo (sidebar + contenido) abajo.
        self._body = QVBoxLayout(self._central)
        self._body.setContentsMargins(0, 0, 0, 0)
        self._body.setSpacing(0)

        self.header = QFrame(self._central)
        self.header.setObjectName("Header")
        self.header.setFixedHeight(64)
        self._body.addWidget(self.header)

        self._cuerpo = QWidget(self._central)
        self._cuerpo_layout = QHBoxLayout(self._cuerpo)
        self._cuerpo_layout.setContentsMargins(0, 0, 0, 0)
        self._cuerpo_layout.setSpacing(0)
        self._body.addWidget(self._cuerpo, stretch=1)

        self.content = QStackedWidget(self._cuerpo)
        self._cuerpo_layout.addWidget(self.content, stretch=1)

    # ------------------------------------------------------------------
    # Vistas
    # ------------------------------------------------------------------

    def mostrar_vista(self, nombre):
        vista = self.vistas.get(nombre)
        if vista is None:
            if nombre == "inicio":
                vista = InicioView(self.content, self, self.biometrico, self.controlador)
            elif nombre == "sesiones":
                vista = SessionsView(self.content, self)
            elif nombre == "admin":
                vista = AdminView(self.content, self, self.biometrico)
            else:
                return
            self.vistas[nombre] = vista
            self.content.addWidget(vista)

        self.content.setCurrentWidget(vista)
        self.vista_actual = vista
        log.info("Vista activa: %s", nombre)

    # ------------------------------------------------------------------
    # Cierre
    # ------------------------------------------------------------------

    def _salir(self):
        log.info("Cerrando aplicacion ...")
        self.controlador.cleanup()
        self.close()

    def closeEvent(self, evento):
        # Shutdown seguro: al cerrar la ventana tambien se libera el HAL.
        self.controlador.cleanup()
        log.info("Aplicacion cerrada.")
        evento.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    # Tema inicial: el guardado en config.json (produccion) o en el
    # config.json local de desarrollo; default oscuro.
    tema_guardado = config.leer_config("tema", style.TEMA_POR_DEFECTO)
    style.aplicar_estilo(
        app,
        tema_guardado if tema_guardado in style.PALETAS
        else style.TEMA_POR_DEFECTO,
    )
    init_db()
    # La sesion 'Activa' que quede tras un apagon se recupera en la vista
    # de Inicio (InicioView._revisar_sesion_interrumpida), no se borra.
    ventana = App()
    ventana.show()
    if ventana.kiosko:
        ventana.showFullScreen()
    try:
        app.exec()
    finally:
        ventana.controlador.cleanup()
        log.info("Controlador HAL liberado.")

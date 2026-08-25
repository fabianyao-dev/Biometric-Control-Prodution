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

import qtawesome as qta
from PySide6.QtCore import QSize, Qt, QTimer
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
from src.hardware.biometric_service import BiometricService
from src.hardware.modbus_controller import ModbusController
from src.hardware.simulacion_controller import SimulacionController

log = logging.getLogger(__name__)

# Iconos del header via qtawesome (fuentes incluidas en el paquete; ver
# requirements.txt). GOTCHA de empaquetado PyInstaller: incluir qtawesome
# con --collect-all (fuentes + charmap) o los iconos salen vacios en el exe.

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

        # Identidad mostrada en el header (la publica InicioView via la
        # senal `sesion_cambiada`): nombre y rol del operador de la sesion.
        self._sesion_nombre = ""
        self._rol_header = ""

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

        # Botones de ICONO del header: cuadrados (44x44) con el glifo
        # centrado; el estilo "Nav" del sidebar es para texto y descentraria
        # los iconos (padding asimetrico + text-align left).
        self.btn_hamburguesa = QPushButton(self.header)
        self.btn_hamburguesa.setObjectName("NavIcono")
        self.btn_hamburguesa.setFixedSize(44, 44)
        self.btn_hamburguesa.setIconSize(QSize(22, 22))
        self._refrescar_boton_menu()
        self.btn_hamburguesa.setToolTip("Mostrar/ocultar menu")
        self.btn_hamburguesa.clicked.connect(self._toggle_sidebar)
        lay.addWidget(self.btn_hamburguesa)

        titulo = QLabel("Control Biometrico de Produccion", self.header)
        titulo.setObjectName("HeaderLabel")
        lay.addWidget(titulo)
        lay.addStretch(1)

        # Sesion (esquina superior derecha): UN solo boton con icono +
        # texto; el texto alterna entre "Iniciar sesion" y el nombre del
        # operador, y el icono es persona (rol operador) o engranaje
        # (cualquier otro rol).
        self.btn_sesion = QPushButton("Iniciar sesion", self.header)
        self.btn_sesion.setObjectName("NavSesion")
        self.btn_sesion.setIconSize(QSize(20, 20))
        self.btn_sesion.clicked.connect(self._toggle_sesion_header)
        self._refrescar_boton_sesion()
        lay.addWidget(self.btn_sesion)

        self.btn_advertencias = IndicadorAdvertencias(self.header)
        lay.addWidget(self.btn_advertencias)

        # Tema claro/oscuro: cambia en caliente y persiste en config.json.
        self.btn_tema = QPushButton(self.header)
        self.btn_tema.setObjectName("NavIcono")
        self.btn_tema.setFixedSize(44, 44)
        self.btn_tema.setIconSize(QSize(20, 20))
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
        # Regenera de inmediato los iconos SVG con los colores del tema
        # nuevo (menu, indicador de avisos y boton de sesion).
        self._refrescar_boton_menu()
        self._revisar_avisos()
        self._refrescar_boton_sesion()

    def _refrescar_boton_menu(self):
        """Icono de la hamburguesa con el color del tema activo."""
        self.btn_hamburguesa.setIcon(
            qta.icon("mdi6.menu", color=style.color("texto_sec"))
        )

    def _refrescar_boton_tema(self):
        # Iconos por nombre (qtawesome); nunca emojis ni glifos Unicode:
        # salen distintos/rotos segun la fuente del sistema.
        if style.tema_activo == "oscuro":
            self.btn_tema.setIcon(qta.icon(
                "mdi6.weather-sunny", color=style.color("texto_sec")
            ))
            self.btn_tema.setToolTip("Cambiar a tema claro")
        else:
            self.btn_tema.setIcon(qta.icon(
                "mdi6.weather-night", color=style.color("texto")
            ))
            self.btn_tema.setToolTip("Cambiar a tema oscuro")

    # ------------------------------------------------------------------
    # Sesion (header): nombre + icono persona/engranaje segun rol
    # ------------------------------------------------------------------

    def _toggle_sesion_header(self):
        """Delega el toggle de sesion al InicioView (toda la logica vive
        alla: modal de huella, guards de maquina en marcha, etc.)."""
        vista = self.vistas.get("inicio")
        if vista is None:
            return
        vista.toggle_sesion()

    def _sesion_cambiada(self, nombre, rol):
        """Slot de InicioView.sesion_cambiada(nombre, rol).

        El texto del boton alterna: "Iniciar sesion" sin sesion, el nombre
        del operador con sesion. El icono: persona para el rol 'operador',
        engranaje para cualquier otro.
        """
        self._sesion_nombre = nombre or ""
        self._rol_header = rol or ""
        self.btn_sesion.setText(
            self._sesion_nombre if self._sesion_nombre else "Iniciar sesion"
        )
        self._refrescar_boton_sesion()

    def _refrescar_boton_sesion(self):
        if self._sesion_nombre:
            es_operador = (
                (self._rol_header or "").strip().lower() == "operador"
            )
            nombre_icono = "mdi6.account" if es_operador else "mdi6.cog"
            color = style.color("texto")
            rol_txt = self._rol_header or "sin rol"
            self.btn_sesion.setToolTip(
                f"Sesion de {self._sesion_nombre} ({rol_txt}) - clic para "
                "cerrar"
            )
        else:
            nombre_icono = "mdi6.account"
            color = style.color("texto_sec")
            self.btn_sesion.setToolTip("Iniciar sesion")
        self.btn_sesion.setIcon(
            qta.icon(nombre_icono, color=color)
        )

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
                # El header refleja la identidad de la sesion (nombre +
                # icono persona/engranaje) via esta senal. Se re-publica el
                # estado actual porque la recuperacion de sesion interrumpida
                # corre DENTRO del constructor (antes de esta conexion).
                vista.sesion_cambiada.connect(self._sesion_cambiada)
                vista._refrescar_operador()
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
        self.close()

    def closeEvent(self, evento):
        # Shutdown seguro: guard de seguridad + liberacion del HAL. El guard
        # vive AQUI (no en _salir) para cubrir tambien Alt+F4 y el cierre del
        # sistema: con la maquina EN MARCHA la ventana no se cierra.
        vista = self.vistas.get("inicio")
        if vista is not None and not vista.aplicacion_puede_cerrarse():
            evento.ignore()
            return
        # cleanup() deja el coil PAUSE en paro sostenido si hay enlace, para
        # que la maquina nunca quede cortando sin supervision (7.2.2).
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

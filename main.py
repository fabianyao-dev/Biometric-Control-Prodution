"""
main.py - Punto de entrada del sistema de control biometrico.

Orquesta:
    - Instancias compartidas: BiometricService, GpioController y la BD.
    - Header con boton hamburguesa que despliega un panel lateral con la
      navegacion: Inicio, Sesiones y Administracion.
    - Shutdown seguro: siempre llama gpio.cleanup() al salir (manual o error).

NO se llama XInitThreads(): en esta RPi causaba abort de XCB (ver
main_original.py). Los hilos secundarios nunca tocan los widgets; se
comunican por queue.Queue() drenada en el hilo principal.
"""

import logging
import os
import tkinter as tk
from tkinter import ttk

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s.%(msecs)03d [%(levelname)s] (%(threadName)s) %(message)s",
    datefmt="%H:%M:%S",
)

from src import config
from src.database import init_db, obtener_rol_operador
from src.gui.admin_view import AdminView
from src.gui.huella_modal import HuellaModal
from src.gui.inicio_view import InicioView
from src.gui.sessions_view import SessionsView
from src.gui.style import aplicar_estilo
from src.hardware.biometric_service import BiometricService
from src.hardware.gpio_controller import GpioController

log = logging.getLogger(__name__)


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        log.info("Iniciando aplicacion biometria")
        self.title("Sistema de Control Biometrico - Planta de Corte")

        # Siempre en pantalla completa; desactivar con BIOMETRICO_KIOSKO=0
        if os.environ.get("BIOMETRICO_KIOSKO") != "0":
            self.attributes("-fullscreen", True)
            self.geometry("800x480")
            log.info("Modo kiosco activado")

        aplicar_estilo(self)
        init_db()
        # La sesion 'Activa' que quede tras un apagon se recupera en la vista
        # de Inicio (InicioView._revisar_sesion_interrumpida), no se borra.

        # Inyeccion de dependencias (HAL + biometria)
        self.biometrico = BiometricService()
        self.gpio = GpioController()

        self.vistas = {}
        self.vista_actual = None
        self.btn_sidebar = {}

        self._crear_header()
        self._crear_contenido()
        self._crear_sidebar(opciones=[
            ("inicio", "Inicio"),
            ("sesiones", "Sesiones"),
            ("admin", "Administracion"),
        ])
        self.mostrar_vista("inicio")

        # Shutdown seguro
        self.protocol("WM_DELETE_WINDOW", self._salir)

    # ------------------------------------------------------------------
    # Header + hamburguesa
    # ------------------------------------------------------------------

    def _crear_header(self):
        self.header = ttk.Frame(self, style="Header.TFrame")
        self.header.pack(fill="x", side="top")

        self.btn_hamburguesa = ttk.Button(
            self.header, text="\u2630", width=3, style="Nav.TButton",
            command=self._toggle_sidebar,
        )
        self.btn_hamburguesa.pack(side="left", padx=(16, 8), pady=10)

        ttk.Label(
            self.header, text="Control Biometrico de Produccion",
            style="Header.TLabel",
        ).pack(side="left", padx=8, pady=10)

        ttk.Button(
            self.header, text="Salir", style="Nav.TButton", command=self._salir,
        ).pack(side="right", padx=16, pady=10)

    # ------------------------------------------------------------------
    # Sidebar lateral (ocultable con la hamburguesa)
    # ------------------------------------------------------------------

    def _crear_sidebar(self, opciones):
        # Se crea despues del contenido para que quede a la izquierda
        self.sidebar = ttk.Frame(self, style="Sidebar.TFrame")
        for nombre, texto in opciones:
            btn = ttk.Button(
                self.sidebar, text=texto, style="Sidebar.TButton",
                command=lambda n=nombre: self._ir_a(n),
            )
            btn.pack(fill="x", padx=8, pady=6)
            self.btn_sidebar[nombre] = btn

        self._sidebar_visible = True
        self._actualizar_sidebar()

    def _toggle_sidebar(self):
        self._sidebar_visible = not self._sidebar_visible
        self._actualizar_sidebar()

    def _actualizar_sidebar(self):
        if self._sidebar_visible:
            self.sidebar.pack(in_=self, before=self.content, side="left", fill="y")
        else:
            self.sidebar.pack_forget()

    def _ir_a(self, nombre):
        # Vistas protegidas por rol: se valida la huella antes de entrar.
        if nombre == "sesiones":
            self._navegar_con_huella(nombre, config.ROLES_ACCESO_SESIONES)
            return
        if nombre == "admin":
            self._navegar_con_huella(nombre, config.ROLES_ACCESO_ADMIN)
            return
        self.mostrar_vista(nombre)
        self._sidebar_visible = False
        self._actualizar_sidebar()

    def _navegar_con_huella(self, nombre, roles_permitidos):
        """Pide la huella y solo navega si el rol del operador esta permitido.

        Si la persona no tiene el rol, el modal muestra el rechazo y sigue
        pidiendo huella hasta que ingrese alguien autorizado o se cancele.
        """
        etiqueta = {"sesiones": "SESIONES", "admin": "ADMINISTRACION"}.get(
            nombre, nombre
        )
        permitidos = " o ".join(roles_permitidos)

        def validador(op_id, nombre_op, causa_id):
            rol = obtener_rol_operador(op_id)
            if rol and rol in roles_permitidos:
                return True, None
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
        modal.grab_set()
        modal.wait_window()

    # ------------------------------------------------------------------
    # Contenido
    # ------------------------------------------------------------------

    def _crear_contenido(self):
        self.content = ttk.Frame(self, style="TFrame")
        self.content.pack(side="left", fill="both", expand=True)

    # ------------------------------------------------------------------
    # Vistas
    # ------------------------------------------------------------------

    def mostrar_vista(self, nombre):
        if self.vista_actual is not None:
            self.vista_actual.pack_forget()

        vista = self.vistas.get(nombre)
        if vista is None:
            if nombre == "inicio":
                vista = InicioView(self.content, self, self.biometrico, self.gpio)
            elif nombre == "sesiones":
                vista = SessionsView(self.content, self)
            elif nombre == "admin":
                vista = AdminView(self.content, self, self.biometrico)
            else:
                return
            self.vistas[nombre] = vista

        vista.pack(fill="both", expand=True)
        self.vista_actual = vista
        log.info("Vista activa: %s", nombre)

    # ------------------------------------------------------------------
    # Cierre
    # ------------------------------------------------------------------

    def _salir(self):
        log.info("Cerrando aplicacion ...")
        self.gpio.cleanup()
        self.destroy()


if __name__ == "__main__":
    app = App()
    try:
        app.mainloop()
    finally:
        app.gpio.cleanup()
        log.info("GPIO desenergizado y liberado.")
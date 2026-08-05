import os
import tkinter as tk
from tkinter import ttk

from src.database import init_db
from src.gui.identify_view import IdentifyView
from src.gui.register_view import RegisterView
from src.gui.style import aplicar_estilo


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Sistema de Control Biométrico - Planta de Corte")
        self.geometry("800x480")

        if os.environ.get("BIOMETRICO_KIOSKO") == "1":
            self.attributes("-fullscreen", True)

        aplicar_estilo(self)
        init_db()

        self.vistas = {}
        self.vista_actual = None

        self._crear_navegacion()
        self._crear_contenido()
        self.mostrar_vista("registro")

    def _crear_navegacion(self):
        header = ttk.Frame(self, style="Header.TFrame")
        header.pack(fill="x", side="top")

        self.btn_registro = ttk.Button(
            header,
            text="Registrar",
            style="Nav.TButton",
            command=lambda: self.mostrar_vista("registro"),
        )
        self.btn_registro.pack(side="left", padx=(20, 8), pady=10)

        self.btn_identificar = ttk.Button(
            header,
            text="Identificar",
            style="Nav.TButton",
            command=lambda: self.mostrar_vista("identificar"),
        )
        self.btn_identificar.pack(side="left", padx=8, pady=10)

    def _crear_contenido(self):
        self.content = ttk.Frame(self, style="TFrame")
        self.content.pack(fill="both", expand=True)

    def mostrar_vista(self, nombre):
        if self.vista_actual is not None:
            self.vista_actual.pack_forget()

        vista = self.vistas.get(nombre)
        if vista is None:
            if nombre == "identificar":
                vista = IdentifyView(self.content, self)
            else:
                vista = RegisterView(self.content, self)
            self.vistas[nombre] = vista

        vista.pack(fill="both", expand=True)
        self.vista_actual = vista


if __name__ == "__main__":
    app = App()
    app.mainloop()

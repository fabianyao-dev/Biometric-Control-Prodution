import sys
import os
import platform

# Los hilos secundarios jamás tocan Tk
# (se comunican por colas thread-safe drenadas en el hilo principal).

# 2. AHORA SÍ IMPORTAR CUSTOMTKINTER Y EL RESTO DEL PROYECTO
import customtkinter as ctk

from src.database import init_db
from src.gui.identify_view import IdentifyView
from src.gui.register_view import RegisterView


class App(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("Sistema de Control Biométrico - Planta de Corte")
        self.geometry("800x600")

        ctk.set_appearance_mode("Dark")
        ctk.set_default_color_theme("blue")

        init_db()

        self.vistas = {}
        self.vista_actual = None

        self._crear_navegacion()
        self._crear_contenido()
        self.mostrar_vista("registro")

    def _crear_navegacion(self):
        header = ctk.CTkFrame(self, height=64, corner_radius=0)
        header.pack(fill="x", side="top")
        header.pack_propagate(False)

        self.btn_registro = ctk.CTkButton(
            header,
            text="Registrar",
            command=lambda: self.mostrar_vista("registro"),
            width=140,
            height=36,
        )
        self.btn_registro.pack(side="left", padx=(20, 8), pady=14)

        self.btn_identificar = ctk.CTkButton(
            header,
            text="Identificar",
            command=lambda: self.mostrar_vista("identificar"),
            width=140,
            height=36,
        )
        self.btn_identificar.pack(side="left", padx=8, pady=14)

    def _crear_contenido(self):
        self.content = ctk.CTkFrame(self, corner_radius=0)
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

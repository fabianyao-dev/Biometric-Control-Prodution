import queue
import threading
import tkinter as tk
from tkinter import ttk

from src.database import guardar_operador
from src.gui.style import ESTILOS_ESTADO
from src.hardware.biometric_service import BiometricService


class RegisterView(ttk.Frame):
    def __init__(self, parent, controller):
        super().__init__(parent, style="TFrame")
        self.controller = controller
        self.servicio = BiometricService()
        self.huella_cap_data = None
        self._capturando = False

        self.cola_eventos = queue.Queue()
        self._crear_interfaz()
        self._revisar_cola()

    def _crear_interfaz(self):
        ttk.Label(
            self, text="Registro de Operador", style="Title.TLabel"
        ).pack(pady=(30, 10))

        self.var_nombre = tk.StringVar()
        self.entry_nombre = ttk.Entry(
            self, textvariable=self.var_nombre, width=32, justify="center"
        )
        self.entry_nombre.pack(pady=12)

        self.lbl_estado_huella = ttk.Label(
            self, text="Huella: Pendiente de captura", style="Pendiente.TLabel"
        )
        self.lbl_estado_huella.pack(pady=12)

        self.btn_capturar = ttk.Button(
            self, text="Colocar y Leer Huella", command=self._capturar_huella
        )
        self.btn_capturar.pack(pady=8)

        self.btn_guardar = ttk.Button(
            self, text="Guardar Operador", command=self._guardar, style="Success.TButton"
        )
        self.btn_guardar.pack(pady=(8, 20))

        self.lbl_mensaje = ttk.Label(self, text="", style="Info.TLabel")
        self.lbl_mensaje.pack(pady=(0, 10))

    def _cambiar_estado(self, etiqueta, texto, estado):
        etiqueta.configure(text=texto, style=ESTILOS_ESTADO[estado])

    def _capturar_huella(self):
        if self._capturando:
            return
        self._capturando = True
        self.btn_capturar.configure(state="disabled")
        self._cambiar_estado(
            self.lbl_estado_huella, "⏳ Coloca tu huella en el sensor...", "procesando"
        )
        self.lbl_mensaje.configure(text="")
        threading.Thread(target=self._capturar_en_hilo, daemon=True).start()

    def _capturar_en_hilo(self):
        """Hilo secundario: solo trabajo pesado, sin tocar widgets."""
        try:
            data = self.servicio.capturar_huella()
            self.cola_eventos.put(("HUELVA_REGISTRADA", data))
        except Exception as e:
            self.cola_eventos.put(("CAPTURA_ERROR", str(e)))

    def _revisar_cola(self):
        """Revisa la cola periódicamente desde el hilo principal."""
        try:
            while True:
                evento, data = self.cola_eventos.get_nowait()
                if evento == "HUELVA_REGISTRADA":
                    self._mostrar_captura(data)
                elif evento == "CAPTURA_ERROR":
                    self._mostrar_error(data)
        except queue.Empty:
            pass
        self.after(50, self._revisar_cola)

    def _mostrar_captura(self, data):
        self._capturando = False
        self.btn_capturar.configure(state="normal")
        if data:
            self.huella_cap_data = data
            self._cambiar_estado(
                self.lbl_estado_huella, "✅ Huella Capturada Correctamente", "exito"
            )
        else:
            self.huella_cap_data = None
            self._cambiar_estado(
                self.lbl_estado_huella, "❌ Error o tiempo agotado. Reintenta.", "error"
            )

    def _mostrar_error(self, mensaje):
        self._capturando = False
        self.btn_capturar.configure(state="normal")
        self.huella_cap_data = None
        self._cambiar_estado(self.lbl_estado_huella, f"❌ Error al capturar: {mensaje}", "error")

    def _guardar(self):
        nombre = self.var_nombre.get().strip()

        if not nombre:
            self._cambiar_estado(self.lbl_mensaje, "Escribe el nombre del operador.", "error")
            return

        if not self.huella_cap_data:
            self._cambiar_estado(self.lbl_mensaje, "Debes capturar la huella antes de guardar.", "error")
            return

        exito, msg = guardar_operador(nombre, self.huella_cap_data["fmd"])
        if exito:
            self._cambiar_estado(self.lbl_mensaje, msg, "exito")
            self.var_nombre.set("")
            self._cambiar_estado(
                self.lbl_estado_huella, "Huella: Pendiente de captura", "pendiente"
            )
            self.huella_cap_data = None
        else:
            self._cambiar_estado(self.lbl_mensaje, msg, "error")

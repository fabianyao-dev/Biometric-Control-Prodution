import queue
import threading
import customtkinter as ctk
from tkinter import messagebox

from src.database import guardar_operador
from src.hardware.biometric_service import BiometricService


class RegisterView(ctk.CTkFrame):
    def __init__(self, parent, controller):
        super().__init__(parent)
        self.controller = controller
        self.servicio = BiometricService()
        self.huella_cap_data = None
        self._capturando = False

        self.cola_eventos = queue.Queue()
        self._crear_interfaz()
        # COMENTADO TEMPORALMENTE (diagnóstico XCB/X11):
        # self._revisar_cola()

    def _crear_interfaz(self):
        lbl_titulo = ctk.CTkLabel(
            self,
            text="Registro de Operador",
            font=ctk.CTkFont(size=24, weight="bold"),
        )
        lbl_titulo.pack(pady=(30, 10))

        self.entry_nombre = ctk.CTkEntry(
            self,
            placeholder_text="Nombre Completo",
            width=320,
            height=44,
            font=ctk.CTkFont(size=16),
        )
        self.entry_nombre.pack(pady=12)

        self.lbl_estado_huella = ctk.CTkLabel(
            self,
            text="Huella: Pendiente de captura",
            text_color="orange",
            font=ctk.CTkFont(size=14),
        )
        self.lbl_estado_huella.pack(pady=12)

        self.btn_capturar = ctk.CTkButton(
            self,
            text="Colocar y Leer Huella",
            command=self._capturar_huella,
            width=220,
            height=44,
            font=ctk.CTkFont(size=15),
            fg_color="#1f538d",
        )
        self.btn_capturar.pack(pady=8)

        self.btn_guardar = ctk.CTkButton(
            self,
            text="Guardar Operador",
            command=self._guardar,
            width=220,
            height=44,
            font=ctk.CTkFont(size=15),
            fg_color="#2fa572",
        )
        self.btn_guardar.pack(pady=(8, 20))

    def _capturar_huella(self):
        if self._capturando:
            return
        self._capturando = True
        self.btn_capturar.configure(state="disabled")
        self.lbl_estado_huella.configure(
            text="⏳ Coloca tu huella en el sensor...", text_color="yellow"
        )
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
            self.lbl_estado_huella.configure(
                text="✅ Huella Capturada Correctamente", text_color="green"
            )
        else:
            self.huella_cap_data = None
            self.lbl_estado_huella.configure(
                text="❌ Error o tiempo agotado. Reintenta.", text_color="red"
            )

    def _mostrar_error(self, mensaje):
        self._capturando = False
        self.btn_capturar.configure(state="normal")
        self.huella_cap_data = None
        self.lbl_estado_huella.configure(text=f"❌ Error al capturar: {mensaje}", text_color="red")

    def _guardar(self):
        nombre = self.entry_nombre.get().strip()

        if not nombre:
            messagebox.showwarning("Campo Incompleto", "Por favor escribe el nombre del operador.")
            return

        if not self.huella_cap_data:
            messagebox.showwarning("Falta Huella", "Debes capturar la huella del operador antes de guardar.")
            return

        éxito, msg = guardar_operador(nombre, self.huella_cap_data["fmd"])
        if éxito:
            messagebox.showinfo("Éxito", msg)
            self.entry_nombre.delete(0, "end")
            self.lbl_estado_huella.configure(
                text="Huella: Pendiente de captura", text_color="orange"
            )
            self.huella_cap_data = None
        else:
            messagebox.showerror("Error", msg)

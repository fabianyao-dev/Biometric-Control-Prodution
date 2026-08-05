import threading
import customtkinter as ctk

from src.database import listar_fmds
from src.hardware.biometric_service import BiometricService


class IdentifyView(ctk.CTkFrame):
    def __init__(self, parent, controller):
        super().__init__(parent)
        self.controller = controller
        self.servicio = BiometricService()
        self._identificando = False

        self._crear_interfaz()

    def _crear_interfaz(self):
        lbl_titulo = ctk.CTkLabel(
            self,
            text="Identificación de Operador",
            font=ctk.CTkFont(size=24, weight="bold"),
        )
        lbl_titulo.pack(pady=(30, 10))

        self.lbl_estado = ctk.CTkLabel(
            self,
            text="Coloca tu huella para identificarte",
            text_color="lightgray",
            font=ctk.CTkFont(size=16),
        )
        self.lbl_estado.pack(pady=20)

        self.lbl_resultado = ctk.CTkLabel(
            self,
            text="",
            font=ctk.CTkFont(size=22, weight="bold"),
        )
        self.lbl_resultado.pack(pady=20)

        self.btn_identificar = ctk.CTkButton(
            self,
            text="Colocar Huella e Identificar",
            command=self._identificar,
            width=240,
            height=46,
            font=ctk.CTkFont(size=15),
            fg_color="#1f538d",
        )
        self.btn_identificar.pack(pady=20)

    def _identificar(self):
        if self._identificando:
            return
        self._identificando = True
        self.btn_identificar.configure(state="disabled")
        self.lbl_resultado.configure(text="")
        self.lbl_estado.configure(
            text="⏳ Coloca tu huella en el sensor...", text_color="yellow"
        )
        threading.Thread(target=self._identificar_en_hilo, daemon=True).start()

    def _identificar_en_hilo(self):
        captura = self.servicio.capturar_huella()
        self.after(0, lambda: self._procesar(captura))

    def _procesar(self, captura):
        self._identificando = False
        self.btn_identificar.configure(state="normal")

        if not captura:
            self.lbl_estado.configure(
                text="❌ Error o tiempo agotado. Reintenta.", text_color="red"
            )
            self.lbl_resultado.configure(text="")
            return

        filas = listar_fmds()
        if not filas:
            self.lbl_estado.configure(
                text="⚠️ No hay operadores registrados. Regístralo primero.",
                text_color="orange",
            )
            self.lbl_resultado.configure(text="")
            return

        fmds = [fila[2] for fila in filas]
        resultado = self.servicio.identificar(captura["fmd"], fmds)

        if resultado:
            idx, _score = resultado
            nombre = filas[idx][1]
            self.lbl_estado.configure(
                text="✅ Identificación exitosa", text_color="green"
            )
            self.lbl_resultado.configure(
                text=f"Bienvenido, {nombre}", text_color="#2fa572"
            )
        else:
            self.lbl_estado.configure(
                text="❌ Huella no reconocida", text_color="red"
            )
            self.lbl_resultado.configure(text="Operador no encontrado", text_color="red")

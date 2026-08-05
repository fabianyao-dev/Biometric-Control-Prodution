import logging
import queue
import threading
from tkinter import ttk

from src.database import listar_fmds
from src.gui.style import ESTILOS_ESTADO
from src.hardware.biometric_service import BiometricService

log = logging.getLogger(__name__)


class IdentifyView(ttk.Frame):
    def __init__(self, parent, controller):
        super().__init__(parent, style="TFrame")
        self.controller = controller
        self.servicio = BiometricService()
        self._identificando = False

        self.cola_eventos = queue.Queue()
        self._crear_interfaz()
        self._revisar_cola()

    def _crear_interfaz(self):
        ttk.Label(
            self, text="Identificación de Operador", style="Title.TLabel"
        ).pack(pady=(30, 10))

        self.lbl_estado = ttk.Label(
            self, text="Coloca tu huella para identificarte", style="Info.TLabel"
        )
        self.lbl_estado.pack(pady=20)

        self.lbl_resultado = ttk.Label(
            self, text="", style="ResultadoInfo.TLabel"
        )
        self.lbl_resultado.pack(pady=20)

        self.btn_identificar = ttk.Button(
            self, text="Colocar Huella e Identificar", command=self._identificar
        )
        self.btn_identificar.pack(pady=20)

    def _cambiar_estado(self, etiqueta, texto, estado):
        etiqueta.configure(text=texto, style=ESTILOS_ESTADO[estado])

    def _cambiar_resultado(self, texto, estado):
        self.lbl_resultado.configure(
            text=texto, style=f"Resultado{estado.capitalize()}.TLabel"
        )

    def _identificar(self):
        if self._identificando:
            return
        self._identificando = True
        self.btn_identificar.configure(state="disabled")
        self._cambiar_resultado("", "info")
        self._cambiar_estado(
            self.lbl_estado, "⏳ Coloca tu huella en el sensor...", "procesando"
        )
        log.info("Solicitando identificación")
        threading.Thread(target=self._identificar_en_hilo, daemon=True).start()

    def _identificar_en_hilo(self):
        """Hilo secundario: solo trabajo pesado, sin tocar widgets."""
        try:
            filas = listar_fmds()
            if not filas:
                self.cola_eventos.put(("SIN_OPERADORES", None))
                return

            plantillas = [fila[2] for fila in filas]
            resultado = self.servicio.identificar_en_lector(
                plantillas, on_progress=self._progreso_identificar
            )
            log.info("Resultado de identificación: %s", resultado)
            self.cola_eventos.put(("IDENTIFICACION", (filas, resultado)))
        except Exception as e:
            log.error("Error en identificación: %s", e, exc_info=True)
            self.cola_eventos.put(("CAPTURA_ERROR", str(e)))

    def _progreso_identificar(self, mensaje):
        self.cola_eventos.put(("IDENT_PROGRESO", mensaje))

    def _revisar_cola(self):
        """Revisa la cola periódicamente desde el hilo principal."""
        try:
            while True:
                evento, data = self.cola_eventos.get_nowait()
                if evento == "IDENTIFICACION":
                    filas, resultado = data
                    self._procesar_resultado(filas, resultado)
                elif evento == "SIN_OPERADORES":
                    self._identificando = False
                    self.btn_identificar.configure(state="normal")
                    self._cambiar_estado(
                        self.lbl_estado,
                        "⚠️ No hay operadores registrados. Regístralo primero.",
                        "pendiente",
                    )
                    self._cambiar_resultado("", "info")
                elif evento == "IDENT_PROGRESO":
                    self._cambiar_estado(
                        self.lbl_estado, data or "Coloca la huella en el sensor...", "procesando"
                    )
                elif evento == "CAPTURA_ERROR":
                    self._mostrar_error(data)
        except queue.Empty:
            pass
        self.after(50, self._revisar_cola)

    def _procesar_resultado(self, filas, resultado):
        self._identificando = False
        self.btn_identificar.configure(state="normal")

        if resultado:
            idx, _score = resultado
            if 0 <= idx < len(filas):
                nombre = filas[idx][1]
                self._cambiar_estado(self.lbl_estado, "✅ Identificación exitosa", "exito")
                self._cambiar_resultado(f"Bienvenido, {nombre}", "exito")
                return

        self._cambiar_estado(self.lbl_estado, "❌ Huella no reconocida", "error")
        self._cambiar_resultado("Operador no encontrado", "error")

    def _mostrar_error(self, mensaje):
        self._identificando = False
        self.btn_identificar.configure(state="normal")
        log.error("Error al identificar: %s", mensaje)
        self._cambiar_estado(self.lbl_estado, "❌ Error al capturar", "error")
        self._cambiar_resultado(mensaje, "error")

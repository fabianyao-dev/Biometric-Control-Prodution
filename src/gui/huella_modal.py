"""
huella_modal.py - Ventana modal reutilizable de autenticacion por huella.

Al abrirse, EMPIEZA a pedir la huella de inmediato (sin botones extras).
Se usa para:
    - Arranque de maquina (validar operador antes de encender).
    - Autorizacion de paro (elegir causa + confirmar con el dedo).

Con `pedir_causa=True` muestra el SelectorCausas: cuadricula con las causas
mas usadas y un boton para buscar. Al autenticar con exito invoca
`on_autenticado(operador_id, nombre, causa_id)`.

Con `validador=(operador_id, nombre, causa_id) -> (bool, mensaje)` se puede
restringir quien puede autenticarse: si el validador devuelve (False, msg),
el modal NO se cierra, muestra `msg` como error y vuelve a pedir la huella
(se usa para que solo el operador de la sesion o un rol autorizado pueda
autorizar la reanudacion de un paro).

El tamano de la ventana se calcula en funcion del contenido (vease
`centrar_y_ajustar`), asi el modal crece o encoge segun la causa.
"""

import logging
import queue
import threading
import tkinter as tk
from tkinter import ttk

from src.gui.selector_causas import SelectorCausas
from src.gui.style import (
    ESTILOS_ESTADO,
    COLOR_EXITO,
    COLOR_TEXTO,
    COLOR_FONDO,
    COLOR_FONDO_INTERIOR,
)
from src.gui.util import centrar_y_ajustar

log = logging.getLogger(__name__)


class HuellaModal(tk.Toplevel):
    def __init__(self, parent, biometrico, titulo, mensaje,
                 on_autenticado=None, on_cancelar=None,
                 mostrar_cancelar=True, cerrable=True, pedir_causa=False,
                 validador=None):
        super().__init__(parent)
        self.biometrico = biometrico
        self.titulo = titulo
        self.mensaje = mensaje
        self.on_autenticado = on_autenticado
        self.on_cancelar = on_cancelar
        self.mostrar_cancelar = mostrar_cancelar
        self.cerrable = cerrable
        self.validador = validador

        self._autenticado = False
        self.cola = queue.Queue()
        self.selector_causas = None

        self.title(titulo)
        self.resizable(False, False)
        self.transient(parent)
        self.configure(bg=COLOR_FONDO)

        if not self.cerrable:
            # La ventana de paro NO puede cerrarse (X/ESC) hasta autenticar.
            self.protocol("WM_DELETE_WINDOW", self._bloquear_cierre)
            self.bind("<Escape>", lambda e: None)

        self._crear_interfaz(pedir_causa)
        centrar_y_ajustar(self, parent)
        self._revisar_cola()
        self._empezar()

    def _bloquear_cierre(self):
        if self._autenticado:
            self.destroy()
            return
        self._estado("No se puede cerrar. Identifica tu huella.", "error")

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _crear_interfaz(self, pedir_causa):
        ttk.Label(self, text=self.titulo, style="Title.TLabel").pack(pady=(20, 6))

        # Huella dactilar dibujada (no depende de fuentes de emoji)
        self.canvas = tk.Canvas(
            self, width=88, height=88, bg=COLOR_FONDO_INTERIOR, highlightthickness=0
        )
        self.canvas.pack(pady=4)
        self._dibujar_huella()

        ttk.Label(self, text=self.mensaje, style="Info.TLabel").pack(pady=4)

        if pedir_causa:
            self.selector_causas = SelectorCausas(self)
            self.selector_causas.pack(fill="x", padx=12, pady=4)

        self.lbl_estado = ttk.Label(self, text="Coloca tu huella...", style="Info.TLabel")
        self.lbl_estado.pack(pady=12)

        if self.mostrar_cancelar:
            ttk.Button(self, text="Cancelar", command=self._cancelar).pack(pady=6)

    def _dibujar_huella(self):
        c = self.canvas
        c.delete("all")
        tono = COLOR_EXITO if not self._autenticado else COLOR_TEXTO
        cx, cy = 44, 44
        c.create_oval(cx - 30, cy - 34, cx + 30, cy + 34,
                      outline=tono, width=3)
        c.create_oval(cx - 22, cy - 26, cx + 22, cy + 26,
                      outline=tono, width=2)
        c.create_oval(cx - 11, cy - 14, cx + 11, cy + 14,
                      outline=tono, width=2)
        c.create_line(cx, cy + 26, cx, cy + 40, fill=tono, width=3)
        for dx in (-10, 10):
            c.create_line(cx, cy + 40, cx + dx, cy + 46, fill=tono, width=3)

    # ------------------------------------------------------------------
    # Captura automatica
    # ------------------------------------------------------------------

    def _empezar(self):
        threading.Thread(target=self._escanea, daemon=True).start()

    def _escanea(self):
        try:
            resultado = self.biometrico.autenticar_operador(
                on_progress=self._progreso
            )
            self.cola.put(("RESULTADO", resultado))
        except Exception as e:  # noqa: BLE001
            log.error("Autenticacion fallo: %s", e, exc_info=True)
            self.cola.put(("ERROR", str(e)))

    def _progreso(self, mensaje):
        self.cola.put(("PROGRESO", mensaje))

    # ------------------------------------------------------------------
    # Cola (hilo principal)
    # ------------------------------------------------------------------

    def _revisar_cola(self):
        try:
            while True:
                ev, data = self.cola.get_nowait()
                try:
                    if ev == "PROGRESO":
                        self._estado(data or "Coloca tu huella...", "procesando")
                    elif ev == "RESULTADO":
                        self._procesar_resultado(data)
                    elif ev == "ERROR":
                        self._estado(f"Intenta de nuevo: {data}", "error")
                        self.after(2500, self._reintentar)
                except Exception as e:  # noqa: BLE001
                    # Un fallo puntual no debe apagar el bucle de mensajes.
                    log.error("Error procesando evento %s: %s", ev, e, exc_info=True)
        except queue.Empty:
            pass
        if self.winfo_exists():
            self.after(60, self._revisar_cola)

    def _procesar_resultado(self, resultado):
        if resultado:
            op_id, nombre = resultado
            causa_id = None
            if self.selector_causas is not None:
                causa_id = self.selector_causas.seleccion_id
            if self.validador is not None:
                valido, mensaje = self.validador(op_id, nombre, causa_id)
                if not valido:
                    log.warning(
                        "Huella %s (%s) SIN autorizacion: %s", op_id, nombre, mensaje
                    )
                    self._estado(mensaje or "Sin autorizacion para reanudar.", "error")
                    self.after(2500, self._reintentar)
                    return
            self._autenticado = True
            self._estado(f"\u2713 {nombre} autenticado.", "exito")
            if self.on_autenticado:
                self.on_autenticado(op_id, nombre, causa_id)
            self.after(300, self.destroy)
        else:
            log.warning("Huella no reconocida; reintentando.")
            self._estado("Huella NO reconocida. Intenta de nuevo.", "error")
            self.after(2500, self._reintentar)

    def _reintentar(self):
        if not self._autenticado and self.winfo_exists():
            threading.Thread(target=self._escanea, daemon=True).start()

    def _cancelar(self):
        if self.on_cancelar and not self._autenticado:
            self.on_cancelar()
        self.destroy()

    def _estado(self, texto, estado):
        self.lbl_estado.configure(
            text=texto, style=ESTILOS_ESTADO.get(estado, "Info.TLabel")
        )

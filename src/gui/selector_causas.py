"""
selector_causas.py - Widget reutilizable para elegir una causa de paro.

Muestra una cuadricula con las causas activas mas usadas (por numero de
paros registrados) y un boton "Buscar caso" que abre un modal con todas las
causas activas y un filtro por texto. Se usa en el modal de autorizacion de
paros (HuellaModal).
"""

import logging
import tkinter as tk
from tkinter import ttk

from src import config
from src.database import listar_causas_frecuentes, listar_causas_paro
from src.gui.style import (
    FAMILIA_FUENTE,
    COLOR_ACCENTE,
    COLOR_ACCENTE_CLARO,
    COLOR_EXITO,
    COLOR_FONDO,
    COLOR_FONDO_INTERIOR,
)
from src.gui.util import centrar_y_ajustar

log = logging.getLogger(__name__)


class SelectorCausas(ttk.Frame):
    """Cuadricula de causas frecuentes + boton de busqueda."""

    def __init__(self, master, on_seleccion=None,
                 limite=config.CAUSAS_FRECUENTES_LIMITE,
                 columnas=config.CAUSAS_GRID_COLUMNAS):
        super().__init__(master, style="TFrame")
        self.on_seleccion = on_seleccion
        self.columnas = max(1, columnas)

        self.seleccion_id = None
        self.seleccion_descripcion = None
        self._botones = {}

        self._crear_interfaz()
        self._cargar_frecuentes(limite)

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _crear_interfaz(self):
        ttk.Label(
            self, text="Causas mas usadas:", style="Info.TLabel"
        ).pack(anchor="w")

        self._contenedor = tk.Frame(self, bg=COLOR_FONDO_INTERIOR)
        self._contenedor.pack(fill="x", pady=4)

        self.btn_buscar = ttk.Button(
            self, text="Buscar caso", command=self._buscar
        )
        self.btn_buscar.pack(pady=(6, 2))

        self.lbl_vacio = ttk.Label(
            self, text="", style="Info.TLabel"
        )

    def _cargar_frecuentes(self, limite):
        causas = listar_causas_frecuentes(limite)
        for i, causa in enumerate(causas):
            fila, col = divmod(i, self.columnas)
            boton = self._crear_boton(causa["id"], causa["descripcion"])
            boton.grid(row=fila, column=col, padx=3, pady=3, sticky="ew")
            self._contenedor.grid_columnconfigure(col, weight=1)

        if causas:
            self._seleccionar(causas[0]["id"], causas[0]["descripcion"])
        else:
            self.lbl_vacio.configure(
                text="Aun sin causas frecuentes; usa 'Buscar caso'."
            )
            self.lbl_vacio.pack(pady=4)

    def _crear_boton(self, causa_id, descripcion):
        boton = tk.Button(
            self._contenedor,
            text=descripcion,
            bg=COLOR_ACCENTE,
            fg="white",
            activebackground=COLOR_ACCENTE_CLARO,
            activeforeground="white",
            relief="flat",
            font=(FAMILIA_FUENTE, 13, "bold"),
            wraplength=180,
            justify="center",
            padx=12,
            pady=8,
            command=lambda c=causa_id, d=descripcion: self._seleccionar(c, d),
        )
        self._botones[causa_id] = (boton, descripcion)
        return boton

    # ------------------------------------------------------------------
    # Seleccion
    # ------------------------------------------------------------------

    def _seleccionar(self, causa_id, descripcion):
        """Marca la causa elegida (boton en verde) y notifica al oyente."""
        self.seleccion_id = causa_id
        self.seleccion_descripcion = descripcion
        for i, (boton, _desc) in self._botones.items():
            boton.configure(bg=COLOR_EXITO if i == causa_id else COLOR_ACCENTE)
        if self.on_seleccion:
            self.on_seleccion(causa_id, descripcion)

    def _buscar(self):
        BuscarCausaModal(self, on_seleccion=self._seleccionar)


class BuscarCausaModal(tk.Toplevel):
    """Modal de busqueda de causa sobre todas las causas activas."""

    def __init__(self, parent, on_seleccion):
        super().__init__(parent)
        self.on_seleccion = on_seleccion
        self._todas = listar_causas_paro(activas_solo=True)

        self.title("Buscar causa de paro")
        self.resizable(False, False)
        self.transient(parent)
        self.configure(bg=COLOR_FONDO)

        self._crear_interfaz()
        self._filtrar()
        centrar_y_ajustar(self, parent)
        self.grab_set()
        self.entry.focus_set()

    def _crear_interfaz(self):
        ttk.Label(
            self, text="Escribe para filtrar o selecciona una causa:",
            style="Info.TLabel",
        ).pack(pady=(16, 4), padx=14)

        self.var_filtro = tk.StringVar()
        self.entry = ttk.Entry(self, textvariable=self.var_filtro)
        self.entry.pack(fill="x", padx=14, pady=4)
        self.var_filtro.trace_add("write", self._filtrar)

        contenedor = ttk.Frame(self)
        contenedor.pack(fill="both", expand=True, padx=14, pady=6)
        self.lista = ttk.Treeview(
            contenedor, columns=("id", "descripcion"), show="headings", height=8
        )
        self.lista.heading("id", text="ID")
        self.lista.heading("descripcion", text="Descripcion")
        self.lista.column("id", width=50, stretch=False)
        self.lista.column("descripcion", width=340)
        scroll = ttk.Scrollbar(contenedor, orient="vertical",
                               command=self.lista.yview)
        self.lista.configure(yscrollcommand=scroll.set)
        self.lista.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        barra = ttk.Frame(self)
        barra.pack(pady=10)
        ttk.Button(
            barra, text="Seleccionar", style="Success.TButton",
            command=self._aceptar,
        ).grid(row=0, column=0, padx=6)
        ttk.Button(barra, text="Cancelar", command=self.destroy).grid(
            row=0, column=1, padx=6
        )

        self.lista.bind("<Double-1>", lambda e: self._aceptar())
        self.lista.bind("<Return>", lambda e: self._aceptar())

    # ------------------------------------------------------------------
    # Logica
    # ------------------------------------------------------------------

    def _filtrar(self, *_args):
        texto = self.var_filtro.get().strip().lower()
        self.lista.delete(*self.lista.get_children())
        for causa in self._todas:
            if texto in causa["descripcion"].lower():
                self.lista.insert(
                    "", "end", values=(causa["id"], causa["descripcion"])
                )

    def _aceptar(self):
        sel = self.lista.selection()
        if not sel:
            return
        causa_id, descripcion = self.lista.item(sel[0])["values"]
        self.on_seleccion(int(causa_id), descripcion)
        self.destroy()

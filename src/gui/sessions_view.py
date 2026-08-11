"""
sessions_view.py - Consulta de sesiones de produccion y sus paros.

Lista todas las sesiones registradas y, al seleccionar una, muestra los paros
de esa sesion (motivo, inicio, fin) para el historial del turno.
"""

import logging
from tkinter import ttk

from src.database import listar_sesiones, obtener_paros_de_sesion

log = logging.getLogger(__name__)


class SessionsView(ttk.Frame):
    def __init__(self, parent, controller):
        super().__init__(parent, style="TFrame")
        self.controller = controller
        self._crear_interfaz()
        self._recargar_sesiones()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _crear_interfaz(self):
        ttk.Label(self, text="Historial de Sesiones", style="Title.TLabel").pack(
            pady=(24, 8)
        )
        ttk.Label(
            self, text="Selecciona una sesion para ver sus paros:", style="Info.TLabel"
        ).pack()

        self.tree_sesiones = ttk.Treeview(
            self,
            columns=("id", "operador", "inicio", "cortes", "estado", "minutos", "paros"),
            show="headings", height=8,
        )
        columnas = {
            "id": ("ID", 50),
            "operador": ("Operador", 140),
            "inicio": ("Inicio", 130),
            "cortes": ("Cortes", 70),
            "estado": ("Estado", 90),
            "minutos": ("Min", 60),
            "paros": ("Paros", 60),
        }
        for col, (titulo, ancho) in columnas.items():
            self.tree_sesiones.heading(col, text=titulo)
            self.tree_sesiones.column(col, width=ancho)
        self.tree_sesiones.pack(fill="both", expand=True, padx=16, pady=10)
        self.tree_sesiones.bind("<<TreeviewSelect>>", self._on_select_sesion)

        ttk.Label(self, text="Paros de la sesion:", style="Header.TLabel").pack(
            anchor="w", padx=16
        )

        self.tree_paros = ttk.Treeview(
            self, columns=("causa", "inicio", "fin"), show="headings", height=4,
        )
        self.tree_paros.heading("causa", text="Causa")
        self.tree_paros.heading("inicio", text="Inicio")
        self.tree_paros.heading("fin", text="Fin")
        self.tree_paros.column("causa", width=220)
        self.tree_paros.column("inicio", width=130)
        self.tree_paros.column("fin", width=130)
        self.tree_paros.pack(fill="both", padx=16, pady=6)

        ttk.Button(self, text="Actualizar", command=self._recargar_sesiones).pack(pady=8)

    # ------------------------------------------------------------------
    # Datos
    # ------------------------------------------------------------------

    def _recargar_sesiones(self):
        for row in self.tree_sesiones.get_children():
            self.tree_sesiones.delete(row)
        for s in listar_sesiones():
            self.tree_sesiones.insert(
                "", "end",
                values=(
                    s["id"], s["nombre"], s["fecha_inicio"], s["total_cortes"],
                    s["estado"], s["minutos"], s["num_paros"],
                ),
            )
        self._limpiar_paros()

    def _on_select_sesion(self, _event=None):
        sel = self.tree_sesiones.selection()
        if not sel:
            return
        sesion_id = int(self.tree_sesiones.item(sel[0])["values"][0])
        self._recargar_paros(sesion_id)

    def _recargar_paros(self, sesion_id):
        for row in self.tree_paros.get_children():
            self.tree_paros.delete(row)
        for p in obtener_paros_de_sesion(sesion_id):
            causa = p["descripcion"] if p["descripcion"] else "(sin causa registrada)"
            self.tree_paros.insert(
                "", "end",
                values=(causa, p["inicio_paro"], p["fin_paro"] or "En curso"),
            )

    def _limpiar_paros(self):
        for row in self.tree_paros.get_children():
            self.tree_paros.delete(row)
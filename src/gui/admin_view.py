"""
admin_view.py - Panel de administracion (CRUD).

Tres pestanas:
    - Operadores: registro con rol (captura de huella) y eliminacion (soft),
      cambio de rol y lista con su columna de rol.
    - Causas de paro: agregar / eliminar motivos (soft).
    - Roles: agregar, renombrar y desactivar roles.

El trabajo de captura de huella para registrar operadores corre en un hilo
secundario; los resultados se drenan por `queue.Queue()` en el hilo principal.
"""

import logging
import queue
import threading
import tkinter as tk
from tkinter import ttk

from src.database import (
    actualizar_rol_operador,
    agregar_causa_paro,
    agregar_rol,
    eliminar_causa_paro,
    eliminar_operador,
    eliminar_rol,
    guardar_operador,
    listar_causas_paro,
    listar_operadores_admin,
    listar_roles,
    renombrar_rol,
)
from src.gui.style import ESTILOS_ESTADO
from src.gui.util import preguntar_texto

log = logging.getLogger(__name__)


class AdminView(ttk.Frame):
    def __init__(self, parent, controller, biometrico):
        super().__init__(parent, style="TFrame")
        self.controller = controller
        self.biometrico = biometrico

        self._capturando = False
        self.huella_cap = None
        self.cola = queue.Queue()
        self._roles_por_nombre = {}

        self._crear_interfaz()
        self._revisar_cola()

    def _crear_interfaz(self):
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True, padx=20, pady=20)

        self.tab_operadores = ttk.Frame(self.notebook, style="TFrame")
        self.tab_causas = ttk.Frame(self.notebook, style="TFrame")
        self.tab_roles = ttk.Frame(self.notebook, style="TFrame")
        self.notebook.add(self.tab_operadores, text="Operadores")
        self.notebook.add(self.tab_causas, text="Causas de Paro")
        self.notebook.add(self.tab_roles, text="Roles")

        self._crear_tab_operadores()
        self._crear_tab_causas()
        self._crear_tab_roles()

    # ------------------------------------------------------------------
    # Roles (combo compartido por operadores)
    # ------------------------------------------------------------------

    def _recargar_roles_combo(self):
        """Actualiza los combos de rol y recuerda la seleccion por defecto."""
        self._roles_por_nombre = {
            r["nombre"]: r["id"] for r in listar_roles(activas_solo=True)
        }
        nombres = list(self._roles_por_nombre.keys())
        for var in (self.var_rol, self.var_rol_cambio):
            var.set("")  # ttk.Combobox readonly: limpiar antes de actualizar
            combo = self.combo_rol if var is self.var_rol else self.combo_rol_cambio
            combo["values"] = nombres
        # Seleccion por defecto: operador (si existe), si no el primer rol.
        predeterminado = "operador" if "operador" in self._roles_por_nombre else (
            nombres[0] if nombres else "")
        self.var_rol.set(predeterminado)

    # ------------------------------------------------------------------
    # Tab Operadores
    # ------------------------------------------------------------------

    def _crear_tab_operadores(self):
        ttk.Label(
            self.tab_operadores, text="Registro de Operador", style="Title.TLabel"
        ).pack(pady=(20, 8))

        self.var_nombre = tk.StringVar()
        self.entry_nombre = ttk.Entry(
            self.tab_operadores, textvariable=self.var_nombre, width=32
        )
        self.entry_nombre.pack(pady=6)

        fila_rol = ttk.Frame(self.tab_operadores, style="TFrame")
        fila_rol.pack(pady=4)
        ttk.Label(fila_rol, text="Rol:", style="Info.TLabel").pack(side="left", padx=6)
        self.var_rol = tk.StringVar()
        self.combo_rol = ttk.Combobox(
            fila_rol, textvariable=self.var_rol, state="readonly", width=22
        )
        self.combo_rol.pack(side="left", padx=6)

        self.lbl_huella = ttk.Label(
            self.tab_operadores, text="Huella: pendiente", style="Info.TLabel"
        )
        self.lbl_huella.pack(pady=6)

        frame_botones = ttk.Frame(self.tab_operadores, style="TFrame")
        frame_botones.pack(pady=6)

        ttk.Button(
            frame_botones, text="Capturar Huella", command=self._capturar_huella,
        ).grid(row=0, column=0, padx=6)
        ttk.Button(
            frame_botones, text="Guardar Operador",
            style="Success.TButton", command=self._guardar_operador,
        ).grid(row=0, column=1, padx=6)

        self.lbl_mensaje = ttk.Label(self.tab_operadores, text="", style="Info.TLabel")
        self.lbl_mensaje.pack(pady=6)

        ttk.Separator(self.tab_operadores).pack(fill="x", pady=10)

        ttk.Label(
            self.tab_operadores, text="Operadores registrados:", style="Header.TLabel"
        ).pack(anchor="w", padx=10)

        self.lista_operadores = ttk.Treeview(
            self.tab_operadores, columns=("id", "nombre", "rol", "estado"),
            show="headings", height=6,
        )
        self.lista_operadores.heading("id", text="ID")
        self.lista_operadores.heading("nombre", text="Nombre")
        self.lista_operadores.heading("rol", text="Rol")
        self.lista_operadores.heading("estado", text="Estado")
        self.lista_operadores.column("id", width=50)
        self.lista_operadores.column("nombre", width=180)
        self.lista_operadores.column("rol", width=100)
        self.lista_operadores.column("estado", width=80)
        self.lista_operadores.pack(fill="both", expand=True, padx=10, pady=6)

        fila_acciones = ttk.Frame(self.tab_operadores, style="TFrame")
        fila_acciones.pack(fill="x", padx=10, pady=4)
        ttk.Button(
            fila_acciones, text="Eliminar Operador",
            command=self._eliminar_operador,
        ).pack(side="left", padx=4)
        ttk.Label(
            fila_acciones, text="Cambiar rol:", style="Info.TLabel"
        ).pack(side="left", padx=(16, 4))
        self.var_rol_cambio = tk.StringVar()
        self.combo_rol_cambio = ttk.Combobox(
            fila_acciones, textvariable=self.var_rol_cambio,
            state="readonly", width=16,
        )
        self.combo_rol_cambio.pack(side="left", padx=4)
        ttk.Button(
            fila_acciones, text="Aplicar", command=self._aplicar_cambio_rol,
        ).pack(side="left", padx=4)

        self._recargar_roles_combo()
        self._recargar_operadores()

    def _capturar_huella(self):
        if self._capturando:
            return
        if not self.var_nombre.get().strip():
            self._lbl(
                "Escribe el nombre antes de capturar la huella.", "error"
            )
            return
        self._capturando = True
        self._lbl_huella("Coloca tu huella...", "procesando")
        threading.Thread(target=self._hilo_captura, daemon=True).start()

    def _hilo_captura(self):
        try:
            data = self.biometrico.enrollar(on_progress=self._progreso)
            self.cola.put(("ENROLL", data))
        except Exception as e:  # noqa: BLE001
            log.error("Captura admin fallo: %s", e, exc_info=True)
            self.cola.put(("ERROR", str(e)))

    def _progreso(self, mensaje):
        self.cola.put(("PROGRESO", mensaje))

    def _guardar_operador(self):
        if self._capturando:
            return
        nombre = self.var_nombre.get().strip()
        if not nombre:
            self._lbl("Escribe el nombre.", "error")
            return
        if self.huella_cap is None:
            self._lbl("Captura la huella primero.", "error")
            return
        rol_id = self._roles_por_nombre.get(self.var_rol.get())
        ok, res = guardar_operador(nombre, self.huella_cap, rol_id)
        if ok:
            self._lbl(f"Operador '{nombre}' registrado.", "exito")
            self.var_nombre.set("")
            self.huella_cap = None
            self._lbl_huella("Huella: pendiente", "info")
            self._recargar_operadores()
        else:
            self._lbl(str(res), "error")

    def _eliminar_operador(self):
        sel = self.lista_operadores.selection()
        if not sel:
            self._lbl("Selecciona un operador de la lista.", "error")
            return
        item = self.lista_operadores.item(sel[0])
        op_id = int(item["values"][0])
        eliminar_operador(op_id)
        self._lbl("Operador eliminado (desactivado).", "exito")
        self._recargar_operadores()

    def _aplicar_cambio_rol(self):
        sel = self.lista_operadores.selection()
        if not sel:
            self._lbl("Selecciona un operador de la lista.", "error")
            return
        rol_id = self._roles_por_nombre.get(self.var_rol_cambio.get())
        if rol_id is None:
            self._lbl("Selecciona un rol valido.", "error")
            return
        op_id = int(self.lista_operadores.item(sel[0])["values"][0])
        actualizar_rol_operador(op_id, rol_id)
        self._lbl("Rol actualizado.", "exito")
        self._recargar_operadores()

    def _recargar_operadores(self):
        for row in self.lista_operadores.get_children():
            self.lista_operadores.delete(row)
        for op in listar_operadores_admin():
            estado = "Activo" if op["activo"] else "Eliminado"
            rol = op["rol"] or "Sin rol"
            self.lista_operadores.insert(
                "", "end", values=(op["id"], op["nombre"], rol, estado)
            )

    # ------------------------------------------------------------------
    # Tab Causas de paro
    # ------------------------------------------------------------------

    def _crear_tab_causas(self):
        ttk.Label(
            self.tab_causas, text="Causas de Paro", style="Title.TLabel"
        ).pack(pady=(20, 8))

        self.var_causa = tk.StringVar()
        entry = ttk.Entry(self.tab_causas, textvariable=self.var_causa, width=32)
        entry.pack(pady=6)

        ttk.Button(
            self.tab_causas, text="Agregar Causa", command=self._agregar_causa,
        ).pack(pady=6)

        self.lbl_causa_msg = ttk.Label(
            self.tab_causas, text="", style="Info.TLabel"
        )
        self.lbl_causa_msg.pack(pady=6)

        self.lista_causas = ttk.Treeview(
            self.tab_causas, columns=("id", "descripcion"),
            show="headings", height=8,
        )
        self.lista_causas.heading("id", text="ID")
        self.lista_causas.heading("descripcion", text="Descripcion")
        self.lista_causas.column("id", width=50)
        self.lista_causas.column("descripcion", width=280)
        self.lista_causas.pack(fill="both", expand=True, padx=10, pady=6)

        ttk.Button(
            self.tab_causas, text="Eliminar Causa", command=self._eliminar_causa,
        ).pack(pady=6)

        self._recargar_causas()

    def _agregar_causa(self):
        desc = self.var_causa.get().strip()
        if not desc:
            self._lbl_causa("Escribe una descripcion.", "error")
            return
        if agregar_causa_paro(desc):
            self.var_causa.set("")
            self._lbl_causa("Causa agregada.", "exito")
            self._recargar_causas()
        else:
            self._lbl_causa("Descripcion vacia.", "error")

    def _eliminar_causa(self):
        sel = self.lista_causas.selection()
        if not sel:
            self._lbl_causa("Selecciona una causa de la lista.", "error")
            return
        item = self.lista_causas.item(sel[0])
        causa_id = int(item["values"][0])
        eliminar_causa_paro(causa_id)
        self._lbl_causa("Causa eliminada (desactivada).", "exito")
        self._recargar_causas()

    def _recargar_causas(self):
        for row in self.lista_causas.get_children():
            self.lista_causas.delete(row)
        for causa in listar_causas_paro(activas_solo=True):
            self.lista_causas.insert("", "end", values=(causa["id"], causa["descripcion"]))

    # ------------------------------------------------------------------
    # Tab Roles
    # ------------------------------------------------------------------

    def _crear_tab_roles(self):
        ttk.Label(
            self.tab_roles, text="Roles", style="Title.TLabel"
        ).pack(pady=(20, 8))

        fila_nuevo = ttk.Frame(self.tab_roles, style="TFrame")
        fila_nuevo.pack(pady=6)
        self.var_rol_nombre = tk.StringVar()
        ttk.Entry(
            fila_nuevo, textvariable=self.var_rol_nombre, width=24
        ).pack(side="left", padx=6)
        ttk.Button(
            fila_nuevo, text="Agregar Rol", command=self._agregar_rol,
        ).pack(side="left", padx=6)

        self.lbl_rol_msg = ttk.Label(self.tab_roles, text="", style="Info.TLabel")
        self.lbl_rol_msg.pack(pady=6)

        self.lista_roles = ttk.Treeview(
            self.tab_roles, columns=("id", "nombre", "estado"),
            show="headings", height=6,
        )
        self.lista_roles.heading("id", text="ID")
        self.lista_roles.heading("nombre", text="Nombre")
        self.lista_roles.heading("estado", text="Estado")
        self.lista_roles.column("id", width=60)
        self.lista_roles.column("nombre", width=180)
        self.lista_roles.column("estado", width=90)
        self.lista_roles.pack(fill="both", expand=True, padx=10, pady=6)

        fila_acciones = ttk.Frame(self.tab_roles, style="TFrame")
        fila_acciones.pack(pady=6)
        ttk.Button(
            fila_acciones, text="Renombrar Rol", command=self._renombrar_rol,
        ).pack(side="left", padx=6)
        ttk.Button(
            fila_acciones, text="Eliminar Rol", command=self._eliminar_rol,
        ).pack(side="left", padx=6)

        self._recargar_roles()

    def _agregar_rol(self):
        nombre = self.var_rol_nombre.get().strip()
        if not nombre:
            self._lbl_rol("Escribe un nombre de rol.", "error")
            return
        if agregar_rol(nombre):
            self.var_rol_nombre.set("")
            self._lbl_rol("Rol agregado.", "exito")
            self._recargar_roles()
            self._recargar_roles_combo()
        else:
            self._lbl_rol("Nombre vacio.", "error")

    def _renombrar_rol(self):
        sel = self.lista_roles.selection()
        if not sel:
            self._lbl_rol("Selecciona un rol de la lista.", "error")
            return
        rol_id, nombre_actual = self.lista_roles.item(sel[0])["values"][:2]
        nuevo = preguntar_texto(
            self, "Renombrar rol", "Nuevo nombre del rol:", str(nombre_actual)
        )
        if nuevo is None:
            return
        if renombrar_rol(int(rol_id), nuevo):
            self._lbl_rol("Rol renombrado.", "exito")
            self._recargar_roles()
            self._recargar_roles_combo()
        else:
            self._lbl_rol("Nombre invalido o ya existe.", "error")

    def _eliminar_rol(self):
        sel = self.lista_roles.selection()
        if not sel:
            self._lbl_rol("Selecciona un rol de la lista.", "error")
            return
        rol_id = int(self.lista_roles.item(sel[0])["values"][0])
        eliminar_rol(rol_id)
        self._lbl_rol("Rol eliminado (desactivado).", "exito")
        self._recargar_roles()
        self._recargar_roles_combo()

    def _recargar_roles(self):
        for row in self.lista_roles.get_children():
            self.lista_roles.delete(row)
        for rol in listar_roles(activas_solo=False):
            estado = "Activo" if rol["activo"] else "Desactivado"
            self.lista_roles.insert(
                "", "end", values=(rol["id"], rol["nombre"], estado)
            )

    # ------------------------------------------------------------------
    # Helpers / cola
    # ------------------------------------------------------------------

    def _lbl(self, texto, estado):
        self.lbl_mensaje.configure(
            text=texto, style=ESTILOS_ESTADO.get(estado, "Info.TLabel")
        )

    def _lbl_huella(self, texto, estado):
        self.lbl_huella.configure(
            text=texto, style=ESTILOS_ESTADO.get(estado, "Info.TLabel")
        )

    def _lbl_causa(self, texto, estado):
        self.lbl_causa_msg.configure(
            text=texto, style=ESTILOS_ESTADO.get(estado, "Info.TLabel")
        )

    def _lbl_rol(self, texto, estado):
        self.lbl_rol_msg.configure(
            text=texto, style=ESTILOS_ESTADO.get(estado, "Info.TLabel")
        )

    def _revisar_cola(self):
        try:
            while True:
                ev, data = self.cola.get_nowait()
                if ev == "PROGRESO":
                    self._lbl_huella(data or "Procesando...", "procesando")
                elif ev == "ENROLL":
                    self._capturando = False
                    if data and data.get("fmd"):
                        self.huella_cap = data["fmd"]
                        self._lbl_huella("Huella capturada.", "exito")
                    else:
                        self.huella_cap = None
                        status = data.get("status") if data else "?"
                        self._lbl_huella(
                            f"Captura sin plantilla ({status}).", "error"
                        )
                elif ev == "ERROR":
                    self._capturando = False
                    self._lbl_huella(f"Error: {data}", "error")
        except queue.Empty:
            pass
        self.after(50, self._revisar_cola)

"""
util.py - Utilidades de GUI reutilizables.

Funciones de apoyo para ventanas emergentes: ajustar el Toplevel a su
contenido (tamano dinamico), centrarlo sobre su ventana padre y un dialogo
generico para pedir texto (usado por el CRUD de roles).
"""

import tkinter as tk
from tkinter import ttk


def centrar_y_ajustar(ventana, parent=None, margen=20,
                      max_ancho=None, max_alto=None):
    """Ajusta un Toplevel a su contenido y lo centra sobre `parent`.

    El tamano final se limita a la pantalla menos `margen` en cada borde,
    de modo que las ventanas crezcan/encogan segun el contenido (modales
    con muchas causas vs. sin causas) sin salirse de la pantalla.
    """
    ventana.update_idletasks()
    ancho = ventana.winfo_reqwidth()
    alto = ventana.winfo_reqheight()

    pantalla_ancho = ventana.winfo_screenwidth()
    pantalla_alto = ventana.winfo_screenheight()

    if max_ancho is None:
        max_ancho = pantalla_ancho - 2 * margen
    if max_alto is None:
        max_alto = pantalla_alto - 2 * margen

    ancho = min(ancho, max_ancho)
    alto = min(alto, max_alto)

    if parent is not None and parent.winfo_exists():
        try:
            x0, y0 = parent.winfo_rootx(), parent.winfo_rooty()
            pw, ph = parent.winfo_width(), parent.winfo_height()
            x = x0 + (pw - ancho) // 2
            y = y0 + (ph - alto) // 2
        except tk.TclError:
            x = (pantalla_ancho - ancho) // 2
            y = (pantalla_alto - alto) // 2
    else:
        x = (pantalla_ancho - ancho) // 2
        y = (pantalla_alto - alto) // 2

    x = max(margen, min(x, pantalla_ancho - ancho - margen))
    y = max(margen, min(y, pantalla_alto - alto - margen))
    ventana.geometry(f"{ancho}x{alto}+{x}+{y}")


def preguntar_texto(parent, titulo, etiqueta, valor_inicial=""):
    """Dialogo modal que pide un texto. Devuelve el texto o None al cancelar."""
    resultado = {"valor": None}
    dialogo = tk.Toplevel(parent)
    dialogo.title(titulo)
    dialogo.resizable(False, False)
    dialogo.transient(parent)

    ttk.Label(dialogo, text=etiqueta, style="Info.TLabel").pack(
        pady=(16, 6), padx=16
    )
    var = tk.StringVar(value=valor_inicial)
    entrada = ttk.Entry(dialogo, textvariable=var, width=28)
    entrada.pack(padx=16, pady=4)

    barra = ttk.Frame(dialogo)
    barra.pack(pady=12)

    def aceptar():
        resultado["valor"] = var.get().strip()
        dialogo.destroy()

    ttk.Button(barra, text="Aceptar", command=aceptar).grid(
        row=0, column=0, padx=6
    )
    ttk.Button(barra, text="Cancelar", command=dialogo.destroy).grid(
        row=0, column=1, padx=6
    )

    dialogo.bind("<Return>", lambda e: aceptar())
    dialogo.bind("<Escape>", lambda e: dialogo.destroy())
    dialogo.grab_set()
    centrar_y_ajustar(dialogo, parent)
    entrada.focus_set()
    dialogo.wait_window()
    return resultado["valor"]

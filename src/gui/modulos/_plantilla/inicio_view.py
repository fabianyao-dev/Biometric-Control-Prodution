# -*- coding: utf-8 -*-
"""Plantilla para un modulo nuevo.

Copiar esta carpeta como `src/gui/modulos/<clave>/` y ajustar los metadatos y
la vista. El loader (`src/gui/modulos/loader.py`) descubre la carpeta sola: no
hay que registrar nada a mano ni crear `__init__.py`.
"""

MODULO_INFO = {
    "clave": "plantilla",
    "nombre": "Plantilla",
    "icono": "",
    "orden": 99,
    "permiso": None,
    "predeterminado": False,
}


def crear_vista(contexto):
    # Reemplazar por la vista real del modulo.
    from PySide6.QtWidgets import QLabel

    return QLabel("Modulo nuevo", contexto.content)


def admin_tabs(contexto):
    return []

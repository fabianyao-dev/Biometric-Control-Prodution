# -*- coding: utf-8 -*-
"""Base para modulos de la aplicacion."""

from dataclasses import dataclass, field
from typing import Callable, List, Optional, Tuple

from PySide6.QtWidgets import QWidget


@dataclass
class Modulo:
    """Describe un modulo disponible en la app."""
    clave: str
    nombre: str
    icono: str = ""
    orden: int = 0
    permiso: Optional[str] = None
    predeterminado: bool = False
    crear_vista: Callable = None
    admin_tabs: Callable = None

    def crear(self, contexto):
        if self.crear_vista is None:
            raise RuntimeError("Modulo %s sin crear_vista" % (self.clave,))
        return self.crear_vista(contexto)

    def tabs_admin(self, contexto):
        if self.admin_tabs is None:
            return []
        return self.admin_tabs(contexto) or []


@dataclass
class ContextoApp:
    """Dependencias compartidas entre modulos."""
    app: object
    content: QWidget
    biometrico: object
    controlador: object
    config: object = None
    inicio_shell: object = None
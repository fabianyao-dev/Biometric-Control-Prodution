# -*- coding: utf-8 -*-
"""Descubrimiento automatico de modulos (sin __init__.py en los subpaquetes).

Cada subcarpeta de `src/gui/modulos/` (que no empiece con `_`) se considera
un modulo si contiene un archivo de vista (`inicio_view.py` o `view.py`). Ese
archivo debe exponer:

- `MODULO_INFO` (dict, opcional): clave, nombre, icono, orden, permiso,
  predeterminado.
- `crear_vista(contexto)` (obligatorio) o una clase `*View` cuyo constructor
  acepte `(content, app, biometrico, controlador)`.
- `admin_tabs(contexto)` (opcional).
"""

import importlib
import logging
import os

from .base import Modulo
from .registro import registrar

_CARPETA = os.path.dirname(os.path.abspath(__file__))
_LOG = logging.getLogger(__name__)


def _buscar_vista(modulo_view, nombre):
    vista_cls = getattr(modulo_view, "InicioView", None)
    if vista_cls is not None:
        return vista_cls
    for attr in dir(modulo_view):
        obj = getattr(modulo_view, attr)
        if isinstance(obj, type) and attr.endswith("View"):
            return obj
    return None


def _cargar_modulo(nombre):
    ruta = os.path.join(_CARPETA, nombre)
    view_name = None
    for candidato in ("inicio_view", "view"):
        if os.path.isfile(os.path.join(ruta, candidato + ".py")):
            view_name = candidato
            break
    if view_name is None:
        return None

    try:
        modulo_view = importlib.import_module(
            ".%s.%s" % (nombre, view_name), package="src.gui.modulos"
        )
    except Exception:  # noqa: BLE001
        _LOG.exception("No se pudo importar la vista del modulo %r", nombre)
        return None

    crear = getattr(modulo_view, "crear_vista", None)
    if not callable(crear):
        vista_cls = _buscar_vista(modulo_view, nombre)
        if vista_cls is None:
            _LOG.warning(
                "Modulo %r: sin crear_vista ni clase *View", nombre
            )
            return None

        def crear(contexto, _cls=vista_cls):
            return _cls(
                contexto.content,
                contexto.app,
                contexto.biometrico,
                contexto.controlador,
            )

    admin_tabs = getattr(modulo_view, "admin_tabs", None)
    if not callable(admin_tabs):
        admin_tabs = lambda contexto: []  # noqa: E731

    info = getattr(modulo_view, "MODULO_INFO", None) or {}
    return Modulo(
        clave=info.get("clave", nombre),
        nombre=info.get("nombre", nombre.capitalize()),
        icono=info.get("icono", ""),
        orden=info.get("orden", 99),
        permiso=info.get("permiso"),
        predeterminado=bool(info.get("predeterminado", False)),
        crear_vista=crear,
        admin_tabs=admin_tabs,
    )


def descubrir():
    """Importa y registra todos los modulos encontrados."""
    encontrados = []
    for nombre in sorted(os.listdir(_CARPETA)):
        if nombre.startswith("_") or nombre.startswith("."):
            continue
        if not os.path.isdir(os.path.join(_CARPETA, nombre)):
            continue
        modulo = _cargar_modulo(nombre)
        if modulo is not None:
            registrar(modulo)
            encontrados.append(modulo.clave)
    _LOG.info("Modulos descubiertos: %s", encontrados or "(ninguno)")
    return encontrados

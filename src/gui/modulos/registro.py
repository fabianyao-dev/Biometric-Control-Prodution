# -*- coding: utf-8 -*-
"""Registro de modulos disponibles en la app."""

from .base import Modulo

_MODULOS = []


def registrar(modulo):
    if not isinstance(modulo, Modulo):
        raise TypeError("se esperaba un Modulo")
    # evitar duplicados por clave
    for existente in _MODULOS:
        if existente.clave == modulo.clave:
            return existente
    _MODULOS.append(modulo)
    _MODULOS.sort(key=lambda m: (m.orden, m.clave))
    return modulo


def modulos_registrados():
    return list(_MODULOS)


def modulos_activos():
    return [m for m in _MODULOS]


def obtener(clave):
    for m in _MODULOS:
        if m.clave == clave:
            return m
    return None


def modulo_predeterminado():
    for m in _MODULOS:
        if m.predeterminado:
            return m
    return _MODULOS[0] if _MODULOS else None


def limpiar():
    _MODULOS[:] = []
# -*- coding: utf-8 -*-
"""Dominio puro para rutinas de Easy (control remoto de estacion).

Sin dependencias de Qt, SQLite ni red. Solo valida, renderiza y arma
peticiones. El servidor de la estacion (Python 3.8) reimplementa la
validacion de forma independiente (defensa en profundidad).
"""

from typing import Mapping

ACCIONES_PERMITIDAS = frozenset({
    "click", "doble_click", "click_derecho", "mover",
    "texto", "tecla", "atajo", "esperar",
})

ANCHO_MAX = 1023
ALTO_MAX = 767
PASOS_MAX = 200
SEGUNDOS_MAX = 600.0
TEXTO_MAX = 1000

PARAMETROS_REQUERIDOS = {
    "click": ("x", "y"),
    "doble_click": ("x", "y"),
    "click_derecho": ("x", "y"),
    "mover": ("x", "y"),
    "texto": ("valor",),
    "tecla": ("valor",),
    "atajo": ("teclas",),
    "esperar": ("segundos",),
}

PARAMETROS_OPCIONALES = {
    "click": ("boton", "clicks", "intervalo"),
    "doble_click": (),
    "click_derecho": (),
    "mover": (),
    "texto": ("normalizar",),
    "tecla": (),
    "atajo": (),
    "esperar": (),
}

PARAMETROS_PLANTILLA = {"valor"}


class ErrorRutinaEasy(ValueError):
    """Error de validacion de una rutina Easy."""


def _es_entero(valor):
    return isinstance(valor, int) and not isinstance(valor, bool)


def _validar_coordenada(x, y):
    if not (_es_entero(x) and _es_entero(y)):
        raise ErrorRutinaEasy("coordenadas deben ser enteros")
    if x < 0 or x > ANCHO_MAX or y < 0 or y > ALTO_MAX:
        raise ErrorRutinaEasy(
            "coordenada fuera de rango (0..%d x 0..%d)" % (ANCHO_MAX, ALTO_MAX)
        )


def validar_paso(paso):
    """Valida un paso y devuelve su copia normalizada. Lanza ErrorRutinaEasy."""
    if not isinstance(paso, Mapping):
        raise ErrorRutinaEasy("el paso debe ser un objeto")
    accion = paso.get("accion")
    if not isinstance(accion, str) or accion not in ACCIONES_PERMITIDAS:
        raise ErrorRutinaEasy("accion no permitida: %r" % (accion,))

    resultado = {"accion": accion}
    for nombre in PARAMETROS_REQUERIDOS[accion]:
        if nombre not in paso:
            raise ErrorRutinaEasy(
                "falta el parametro %r en la accion %s" % (nombre, accion)
            )
        resultado[nombre] = paso[nombre]
    for nombre in PARAMETROS_OPCIONALES[accion]:
        if nombre in paso:
            resultado[nombre] = paso[nombre]
    if "comentario" in paso and paso["comentario"] is not None:
        comentario = paso["comentario"]
        if not isinstance(comentario, str):
            raise ErrorRutinaEasy("comentario debe ser texto")
        resultado["comentario"] = comentario

    if accion in ("click", "doble_click", "click_derecho", "mover"):
        _validar_coordenada(resultado["x"], resultado["y"])
        if "boton" in resultado:
            if resultado["boton"] not in (
                "izq", "der", "medio", "left", "right", "middle",
            ):
                raise ErrorRutinaEasy("boton invalido")
        if "clicks" in resultado:
            if (not _es_entero(resultado["clicks"])
                    or resultado["clicks"] < 1):
                raise ErrorRutinaEasy("clicks debe ser entero >= 1")
        if "intervalo" in resultado:
            if (isinstance(resultado["intervalo"], bool)
                    or not isinstance(resultado["intervalo"], (int, float))):
                raise ErrorRutinaEasy("intervalo debe ser numero")
            if resultado["intervalo"] < 0:
                raise ErrorRutinaEasy("intervalo no puede ser negativo")
    if accion in ("texto", "tecla"):
        if not isinstance(resultado["valor"], str):
            raise ErrorRutinaEasy("valor debe ser texto")
        if len(resultado["valor"]) > TEXTO_MAX:
            raise ErrorRutinaEasy("texto demasiado largo")
    if accion == "atajo":
        teclas = resultado["teclas"]
        if not isinstance(teclas, list) or not teclas:
            raise ErrorRutinaEasy("teclas debe ser lista no vacia")
        if not all(isinstance(t, str) and t.strip() for t in teclas):
            raise ErrorRutinaEasy("cada tecla debe ser texto")
    if accion == "esperar":
        seg = resultado["segundos"]
        if (isinstance(seg, bool)
                or not isinstance(seg, (int, float))):
            raise ErrorRutinaEasy("segundos debe ser numero")
        if seg < 0 or seg > SEGUNDOS_MAX:
            raise ErrorRutinaEasy("segundos fuera de rango")

    permitidas = (
        set(PARAMETROS_REQUERIDOS[accion])
        | set(PARAMETROS_OPCIONALES[accion])
        | {"comentario"}
    )
    desconocidas = set(paso.keys()) - ({"accion"} | permitidas)
    if desconocidas:
        raise ErrorRutinaEasy(
            "parametros no permitidos: %s" % sorted(desconocidas)
        )
    return resultado


def validar_rutina(pasos):
    """Valida una lista de pasos. Devuelve la lista normalizada."""
    if not isinstance(pasos, list):
        raise ErrorRutinaEasy("los pasos deben ser una lista")
    if not pasos:
        raise ErrorRutinaEasy("la rutina debe tener al menos un paso")
    if len(pasos) > PASOS_MAX:
        raise ErrorRutinaEasy("demasiados pasos (maximo %d)" % PASOS_MAX)
    normalizados = [validar_paso(p) for p in pasos]
    total = 0.0
    for p in normalizados:
        if p["accion"] == "esperar":
            total += float(p["segundos"])
    if total > SEGUNDOS_MAX:
        raise ErrorRutinaEasy(
            "tiempo de espera acumulado excede %s s" % SEGUNDOS_MAX
        )
    return normalizados


def _renderizar_valor(valor, variables):
    if not isinstance(valor, str):
        return valor
    resultado = valor
    for clave, val in (variables or {}).items():
        marcador = "{" + str(clave) + "}"
        if marcador in resultado:
            resultado = resultado.replace(marcador, str(val))
    return resultado


def renderizar_pasos(pasos, variables=None):
    """Devuelve copia de los pasos con las plantillas {variable} sustituidas."""
    variables = variables or {}
    salida = []
    for paso in pasos:
        copia = dict(paso)
        for clave in PARAMETROS_PLANTILLA:
            if clave in copia:
                copia[clave] = _renderizar_valor(copia[clave], variables)
        if "teclas" in copia and isinstance(copia["teclas"], list):
            copia["teclas"] = [
                _renderizar_valor(t, variables) if isinstance(t, str) else t
                for t in copia["teclas"]
            ]
        salida.append(copia)
    return salida


def construir_peticion(rutina, pasos, variables=None, token=None):
    """Arma el dict listo para enviar al servidor."""
    if not isinstance(rutina, str) or not rutina.strip():
        raise ErrorRutinaEasy("nombre de rutina invalido")
    normalizados = validar_rutina(pasos)
    renderizados = renderizar_pasos(normalizados, variables)
    peticion = {
        "version": 2,
        "rutina": rutina.strip(),
        "variables": dict(variables or {}),
        "pasos": renderizados,
    }
    if token:
        peticion["token"] = token
    return peticion

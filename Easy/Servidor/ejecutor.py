# -*- coding: utf-8 -*-
"""Ejecutor de pasos dinamicos para el agente Easy.

Recibe una lista de pasos (dicts) y los ejecuta en orden sobre las primitivas
de `acciones`. No carga archivos .py ni ejecuta codigo arbitrario: solo un
conjunto cerrado (allowlist) de acciones con sus parametros validados.

Compatible con Python 3.8.10 de 32 bits. Sin dependencias fuera de la stdlib
y de `acciones`.

Uso:
    from ejecutor import validar_pasos, ejecutar_pasos

    pasos = [{"accion": "click", "x": 10, "y": 20}]
    pasos_validados = validar_pasos(pasos, variables={"num_part": "ABC"})
    resultado = ejecutar_pasos(pasos, variables={"num_part": "ABC"})
    # resultado: {"ok": True/False, "pasos": N, "error": ..., "paso": i, ...}
"""

import time
import logging
log = logging.getLogger(__name__)

from acciones import (
    Abortado,
    ErrorAccion,
    atajo,
    click,
    click_derecho,
    doble_click,
    esperar,
    mover,
    pasos_ejecutados,
    reiniciar_contador,
    reiniciar_aborto,
    tecla,
    texto,
)

ACCIONES_PERMITIDAS = set([
    "click", "doble_click", "click_derecho", "mover",
    "texto", "tecla", "atajo", "esperar",
])

ANCHO_MAX = 1023
ALTO_MAX = 767
PASOS_MAX = 200
SEGUNDOS_MAX = 600.0
TEXTO_MAX = 1000

PARAMETROS_REQUERIDOS = {
    "click": ["x", "y"],
    "doble_click": ["x", "y"],
    "click_derecho": ["x", "y"],
    "mover": ["x", "y"],
    "texto": ["valor"],
    "tecla": ["valor"],
    "atajo": ["teclas"],
    "esperar": ["segundos"],
}

PARAMETROS_OPCIONALES = {
    "click": ["boton", "clicks", "intervalo"],
    "doble_click": [],
    "click_derecho": [],
    "mover": [],
    "texto": ["normalizar"],
    "tecla": [],
    "atajo": [],
    "esperar": [],
}


class ErrorPaso(ErrorAccion):
    """Error de validacion de un paso dinamico."""


def _es_entero(valor):
    return isinstance(valor, int) and not isinstance(valor, bool)


def _validar_coordenada(x, y):
    if not (_es_entero(x) and _es_entero(y)):
        raise ErrorPaso("coordenadas deben ser enteros")
    if x < 0 or x > ANCHO_MAX or y < 0 or y > ALTO_MAX:
        raise ErrorPaso(
            "coordenada fuera de rango: (%d, %d)" % (x, y)
        )


def _renderizar_valor(valor, variables):
    if not isinstance(valor, str):
        return valor
    resultado = valor
    for clave, val in (variables or {}).items():
        marcador = "{" + str(clave) + "}"
        if marcador in resultado:
            resultado = resultado.replace(marcador, str(val))
    return resultado


def _normalizar_paso(paso, variables):
    if not isinstance(paso, dict):
        raise ErrorPaso("el paso debe ser un objeto")
    accion = paso.get("accion")
    if not isinstance(accion, str) or accion not in ACCIONES_PERMITIDAS:
        raise ErrorPaso("accion no permitida: %r" % (accion,))

    resultado = {"accion": accion}
    for nombre in PARAMETROS_REQUERIDOS[accion]:
        if nombre not in paso:
            raise ErrorPaso(
                "falta el parametro %r en la accion %s" % (nombre, accion)
            )
        resultado[nombre] = paso[nombre]
    for nombre in PARAMETROS_OPCIONALES[accion]:
        if nombre in paso:
            resultado[nombre] = paso[nombre]
    if "comentario" in paso and paso["comentario"] is not None:
        if not isinstance(paso["comentario"], str):
            raise ErrorPaso("comentario debe ser texto")
        resultado["comentario"] = paso["comentario"]

    # rechazar claves desconocidas
    permitidas = set(PARAMETROS_REQUERIDOS[accion]) | set(
        PARAMETROS_OPCIONALES[accion]
    ) | {"comentario"}
    desconocidas = set(paso.keys()) - ({"accion"} | permitidas)
    if desconocidas:
        raise ErrorPaso(
            "parametros no permitidos: %s" % sorted(desconocidas)
        )

    # validaciones por accion
    if accion in ("click", "doble_click", "click_derecho", "mover"):
        _validar_coordenada(resultado["x"], resultado["y"])
        if "boton" in resultado:
            if str(resultado["boton"]).lower() not in (
                "izq", "der", "medio", "left", "right", "middle",
            ):
                raise ErrorPaso("boton invalido")
        if "clicks" in resultado:
            if (not _es_entero(resultado["clicks"])
                    or resultado["clicks"] < 1):
                raise ErrorPaso("clicks debe ser entero >= 1")
        if "intervalo" in resultado:
            if (isinstance(resultado["intervalo"], bool)
                    or not isinstance(resultado["intervalo"], (int, float))):
                raise ErrorPaso("intervalo debe ser numero")
            if resultado["intervalo"] < 0:
                raise ErrorPaso("intervalo no puede ser negativo")
    if accion in ("texto", "tecla"):
        if not isinstance(resultado["valor"], str):
            raise ErrorPaso("valor debe ser texto")
        if len(resultado["valor"]) > TEXTO_MAX:
            raise ErrorPaso("texto demasiado largo")
    if accion == "atajo":
        teclas = resultado["teclas"]
        if not isinstance(teclas, list) or not teclas:
            raise ErrorPaso("teclas debe ser lista no vacia")
        if not all(isinstance(t, str) and str(t).strip() for t in teclas):
            raise ErrorPaso("cada tecla debe ser texto")
    if accion == "esperar":
        seg = resultado["segundos"]
        if (isinstance(seg, bool)
                or not isinstance(seg, (int, float))):
            raise ErrorPaso("segundos debe ser numero")
        if seg < 0 or seg > SEGUNDOS_MAX:
            raise ErrorPaso("segundos fuera de rango")

    # renderizar plantillas {variable} en strings
    for clave in ("valor",):
        if clave in resultado:
            resultado[clave] = _renderizar_valor(resultado[clave], variables)
    if "teclas" in resultado and isinstance(resultado["teclas"], list):
        resultado["teclas"] = [
            _renderizar_valor(t, variables) if isinstance(t, str) else t
            for t in resultado["teclas"]
        ]
    return resultado


def validar_pasos(pasos, variables=None):
    """Valida y normaliza una lista de pasos. Lanza ErrorPaso si invalido."""
    if not isinstance(pasos, list):
        raise ErrorPaso("los pasos deben ser una lista")
    if not pasos:
        raise ErrorPaso("la rutina debe tener al menos un paso")
    if len(pasos) > PASOS_MAX:
        raise ErrorPaso("demasiados pasos (maximo %d)" % PASOS_MAX)
    normalizados = []
    for indice, p in enumerate(pasos, start=1):
        try:
            normalizados.append(_normalizar_paso(p, variables))
        except (ErrorPaso, ErrorAccion) as error:
            setattr(error, "paso", indice)
            if isinstance(p, dict):
                setattr(error, "accion", p.get("accion"))
            raise
    total = 0.0
    for p in normalizados:
        if p["accion"] == "esperar":
            total += float(p["segundos"])
    if total > SEGUNDOS_MAX:
        err = ErrorPaso(
            "tiempo de espera acumulado excede %s s" % SEGUNDOS_MAX
        )
        raise err
    return normalizados


def ejecutar_pasos(pasos, variables=None):
    """Valida y ejecuta los pasos en orden. Devuelve un dict listo para JSON.

    No lanza: los errores se devuelven en el dict con 'paso' (1-based) y
    'accion' cuando aplica.
    """
    inicio = time.monotonic()
    reiniciar_aborto()
    reiniciar_contador()
    try:
        normalizados = validar_pasos(pasos, variables)
    except (ErrorPaso, ErrorAccion) as error:
        respuesta = {
            "ok": False,
            "error": str(error),
            "segundos": round(time.monotonic() - inicio, 2),
        }
        if getattr(error, "paso", None) is not None:
            respuesta["paso"] = error.paso
        if getattr(error, "accion", None) is not None:
            respuesta["accion"] = error.accion
        return respuesta

    try:
        for indice, paso in enumerate(normalizados, start=1):
            accion = paso["accion"]
            log.info("Ejecutando paso %d/%d: accion=%s", indice, len(normalizados), accion)
            if accion == "click":
                x, y = paso["x"], paso["y"]
                boton = paso.get("boton", "izq")
                clicks = paso.get("clicks", 1)
                intervalo = paso.get("intervalo", 0.1)
                log.info(f"Ejecutando paso {indice}/{len(normalizados)}: click en ({x},{y}), boton={boton}, clicks={clicks}, intervalo={intervalo}")
                click(
                    x, y,
                    boton=boton,
                    clicks=clicks,
                    intervalo=intervalo,
                )
            elif accion == "doble_click":
                x, y = paso["x"], paso["y"]
                log.info(f"Ejecutando paso {indice}/{len(normalizados)}: doble_click en ({x},{y})")
                doble_click(x, y)
            elif accion == "click_derecho":
                x, y = paso["x"], paso["y"]
                log.info(f"Ejecutando paso {indice}/{len(normalizados)}: click_derecho en ({x},{y})")
                click_derecho(x, y)
            elif accion == "mover":
                x, y = paso["x"], paso["y"]
                log.info(f"Ejecutando paso {indice}/{len(normalizados)}: mover a ({x},{y})")
                mover(x, y)
            elif accion == "texto":
                valor = paso["valor"]
                log.info(f"Ejecutando paso {indice}/{len(normalizados)}: texto '{valor}'")
                texto(
                    valor,
                    normalizar=paso.get("normalizar", True),
                )
            elif accion == "tecla":
                valor = paso["valor"]
                log.info(f"Ejecutando paso {indice}/{len(normalizados)}: tecla '{valor}'")
                tecla(valor)
            elif accion == "atajo":
                teclas = paso["teclas"]
                log.info(f"Ejecutando paso {indice}/{len(normalizados)}: atajo '{', '.join(teclas)}'")
                atajo(*teclas)
            elif accion == "esperar":
                segundos = paso["segundos"]
                log.info(f"Ejecutando paso {indice}/{len(normalizados)}: esperar {segundos} segundos")
                esperar(segundos)
            else:  # no deberia ocurrir tras validar
                log.error(f"Ejecutando paso {indice}/{len(normalizados)}: accion no permitida: {accion}")
                raise ErrorPaso("accion no permitida: %r" % (accion,))
    except Abortado as error:
        return {
            "ok": False,
            "abortado": True,
            "error": str(error),
            "paso": indice,
            "accion": accion,
            "segundos": round(time.monotonic() - inicio, 2),
        }
    except ErrorAccion as error:
        return {
            "ok": False,
            "error": str(error),
            "paso": indice,
            "accion": accion,
            "segundos": round(time.monotonic() - inicio, 2),
        }
    except Exception as error:
        return {
            "ok": False,
            "error": "%s: %s" % (error.__class__.__name__, error),
            "paso": indice,
            "accion": accion,
            "segundos": round(time.monotonic() - inicio, 2),
        }

    return {
        "ok": True,
        "pasos": pasos_ejecutados(),
        "segundos": round(time.monotonic() - inicio, 2),
    }
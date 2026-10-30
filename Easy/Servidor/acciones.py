# -*- coding: utf-8 -*-
"""Primitivas de automatizacion para la estacion de trabajo.

Compatible con Python 3.8.10 de 32 bits. No importa pyautogui al cargar el
modulo: se importa la primera vez que se ejecuta una accion. Asi la otra
aplicacion puede importar este archivo sin necesidad de escritorio.

Uso tipico desde una rutina:

    from acciones import click, texto, tecla, esperar

    def ejecutar(texto_busqueda):
        click(312, 208)
        texto(texto_busqueda)
        tecla("enter")

La tecla Esc aborta la ejecucion (se comprueba antes de cada accion y dentro
de las esperas).
"""

import logging
import os
import platform
import struct
import sys
import time

log = logging.getLogger("acciones")

# Resolucion esperada de la estacion de trabajo.
ANCHO = 1024
ALTO = 768

# Tiempo que se deja al programa destino para leer el portapapeles.
PAUSA_PEGADO = 0.2

_backend = None
_pasos = 0
_abortado = False

ALIAS_BOTONES = {
    "izq": "left",
    "izquierdo": "left",
    "left": "left",
    "der": "right",
    "derecho": "right",
    "right": "right",
    "medio": "middle",
    "middle": "middle",
}

ALIAS_TECLAS = {
    "intro": "enter",
    "enter": "enter",
    "tabulador": "tab",
    "tab": "tab",
    "espacio": "space",
    "space": "space",
    "retroceso": "backspace",
    "backspace": "backspace",
    "supr": "delete",
    "suprimir": "delete",
    "delete": "delete",
    "escape": "esc",
    "esc": "esc",
    "inicio": "home",
    "home": "home",
    "fin": "end",
    "end": "end",
    "repan": "pageup",
    "repag": "pageup",
    "pageup": "pageup",
    "avpag": "pagedown",
    "pagedown": "pagedown",
    "arriba": "up",
    "abajo": "down",
    "izquierda": "left",
    "derecha": "right",
    "insertar": "insert",
    "insert": "insert",
    "imprimir": "printscreen",
    "printscreen": "printscreen",
}


class ErrorAccion(Exception):
    """Error controlado de una accion (coordenada, tecla, texto, etc.)."""


class Abortado(ErrorAccion):
    """La ejecucion se interrumpio con Esc o con el FailSafe de pyautogui."""


def configurar_backend(backend):
    """Inyecta un backend falso para pruebas sin escritorio."""
    global _backend
    _backend = backend


def configurar_pantalla(ancho, alto):
    """Fija la resolucion esperada de la estacion."""
    global ANCHO, ALTO
    ancho = int(ancho)
    alto = int(alto)
    if ancho <= 0 or alto <= 0:
        raise ValueError("resolucion no valida")
    ANCHO = ancho
    ALTO = alto


def configurar_pausa(segundos):
    """Ajusta la pausa interna de pyautogui entre acciones."""
    _pg().PAUSE = max(0.0, float(segundos))


def _pg():
    global _backend
    if _backend is not None:
        return _backend
    import pyautogui

    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0.05
    _backend = pyautogui
    return pyautogui


def _invocar(funcion, *args, **kwargs):
    """Ejecuta una funcion de pyautogui traduciendo el FailSafe a Abortado."""
    try:
        return funcion(*args, **kwargs)
    except Exception as error:
        if error.__class__.__name__ == "FailSafeException":
            raise Abortado("FailSafe activado: el raton esta en una esquina")
        raise


def _contar():
    global _pasos
    _pasos += 1


def pasos_ejecutados():
    return _pasos


def reiniciar_contador():
    global _pasos
    _pasos = 0


def abortar():
    global _abortado
    _abortado = True


def reiniciar_aborto():
    global _abortado
    _abortado = False


def _esc_presionada():
    if os.name != "nt":
        return False
    try:
        import ctypes

        return bool(ctypes.windll.user32.GetAsyncKeyState(0x1B) & 0x8000)
    except Exception:
        return False


def _comprobar_aborto():
    if _abortado:
        raise Abortado("abortado por el operador")
    if _esc_presionada():
        raise Abortado("abortado con Esc")


def _entero(valor, nombre):
    try:
        return int(valor)
    except (TypeError, ValueError):
        raise ErrorAccion("%s debe ser un numero entero, no %r" % (nombre, valor))


def _validar_coordenada(x, y):
    x = _entero(x, "x")
    y = _entero(y, "y")
    if x < 0 or x >= ANCHO or y < 0 or y >= ALTO:
        raise ErrorAccion(
            "coordenada fuera de pantalla: (%d, %d); se esperaba 0..%d x 0..%d"
            % (x, y, ANCHO - 1, ALTO - 1)
        )
    return x, y


def tamano():
    ancho, alto = _pg().size()
    return int(ancho), int(alto)


def posicion():
    actual = _pg().position()
    return int(actual[0]), int(actual[1])


def verificar_pantalla(forzar=False):
    """Comprueba que la pantalla real coincida con la resolucion esperada.

    Devuelve un mensaje de advertencia si hay diferencia y forzar=True.
    Lanza ErrorAccion si hay diferencia y forzar=False.
    """
    ancho, alto = tamano()
    if (ancho, alto) == (ANCHO, ALTO):
        return None
    mensaje = "pantalla %dx%d, se esperaba %dx%d" % (ancho, alto, ANCHO, ALTO)
    if forzar:
        log.warning(mensaje)
        return mensaje
    raise ErrorAccion(mensaje + " (usa --forzar solo para pruebas)")


def info_entorno():
    """Datos utiles para el log de arranque del agente."""
    return {
        "python": sys.version.split()[0],
        "bits": struct.calcsize("P") * 8,
        "plataforma": platform.platform(),
        "pantalla": tamano(),
        "esperada": (ANCHO, ALTO),
    }


def click(x, y, boton="izq", clicks=1, intervalo=0.1):
    """Clic en coordenadas absolutas."""
    x, y = _validar_coordenada(x, y)
    boton_normal = ALIAS_BOTONES.get(str(boton).lower())
    if boton_normal is None:
        raise ErrorAccion("boton no valido: %r" % (boton,))
    clicks = _entero(clicks, "clicks")
    if clicks < 1:
        raise ErrorAccion("clicks debe ser mayor que cero")
    _comprobar_aborto()
    _invocar(
        _pg().click,
        x=x,
        y=y,
        clicks=clicks,
        interval=float(intervalo),
        button=boton_normal,
    )
    _contar()
    log.debug("click x=%d y=%d boton=%s clicks=%d", x, y, boton_normal, clicks)


def doble_click(x, y):
    click(x, y, boton="izq", clicks=2, intervalo=0.1)


def click_derecho(x, y):
    click(x, y, boton="der")


def mover(x, y):
    x, y = _validar_coordenada(x, y)
    _comprobar_aborto()
    _invocar(_pg().moveTo, x, y)
    _contar()
    log.debug("mover x=%d y=%d", x, y)


def _normalizar_texto(cadena):
    return " ".join(str(cadena).split())


def texto(cadena, normalizar=True, intervalo=0.0):
    """Escribe texto letra por letra (tecleo directo).

    Usa pyautogui.write, que simula pulsaciones de teclado una por una.
    Fiable solo con caracteres ASCII; los caracteres no ASCII pueden fallar
    segun el layout del teclado de la estacion.
    """
    valor = _normalizar_texto(cadena) if normalizar else str(cadena)
    if not valor:
        raise ErrorAccion("texto vacio")
    _comprobar_aborto()
    pg = _pg()
    _invocar(pg.write, valor, interval=intervalo)
    _contar()
    log.debug("texto de %d caracteres", len(valor))


def _normalizar_tecla(nombre):
    clave = str(nombre).strip().lower()
    return ALIAS_TECLAS.get(clave, clave)


def tecla(nombre):
    """Pulsa una tecla suelta (nombres de pyautogui)."""
    clave = _normalizar_tecla(nombre)
    pg = _pg()
    if clave not in pg.KEYBOARD_KEYS:
        raise ErrorAccion("tecla no valida: %r" % (nombre,))
    _comprobar_aborto()
    _invocar(pg.press, clave)
    _contar()
    log.debug("tecla %s", clave)


def atajo(*teclas):
    """Pulsa una combinacion. Acepta atajo("ctrl", "s") o atajo("ctrl+s")."""
    pg = _pg()
    partes = []
    for elemento in teclas:
        if isinstance(elemento, (list, tuple)):
            candidatos = list(elemento)
        else:
            valor = str(elemento).strip()
            if valor == "+":
                candidatos = ["+"]
            else:
                candidatos = valor.replace("+", " ").split()
        for candidato in candidatos:
            clave = _normalizar_tecla(candidato)
            if clave not in pg.KEYBOARD_KEYS:
                raise ErrorAccion("tecla no valida en atajo: %r" % (candidato,))
            partes.append(clave)
    if not partes:
        raise ErrorAccion("atajo vacio")
    _comprobar_aborto()
    _invocar(pg.hotkey, *partes)
    _contar()
    log.debug("atajo %s", "+".join(partes))


def esperar(segundos):
    """Espera interrumpible con Esc."""
    try:
        total = float(segundos)
    except (TypeError, ValueError):
        raise ErrorAccion("espera no valida: %r" % (segundos,))
    if total < 0:
        total = 0.0
    fin = time.monotonic() + total
    while True:
        _comprobar_aborto()
        restante = fin - time.monotonic()
        if restante <= 0:
            return
        time.sleep(min(0.05, restante))

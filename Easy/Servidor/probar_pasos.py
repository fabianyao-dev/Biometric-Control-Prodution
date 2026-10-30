# -*- coding: utf-8 -*-
"""Prueba segura del ejecutor de pasos dinamicos (sin raton ni teclado).

Usa el backend falso de `acciones` para validar el orden, la sustitucion de
variables, el rechazo de pasos invalidos (sin ejecutar nada) y el aborto.

Compatible con Python 3.8.10. Ejecutar:
    python Servidor\\probar_pasos.py
"""

import sys

BASE = None
import os
BASE = os.path.dirname(os.path.abspath(__file__))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

from acciones import configurar_backend, configurar_pantalla, reiniciar_aborto
import ejecutor


class BackendFalso(object):
    KEYBOARD_KEYS = set(["enter", "ctrl", "v", "a", "esc"])

    def __init__(self):
        self.llamadas = []

    def size(self):
        return (1024, 768)

    def position(self):
        return (0, 0)

    def click(self, x=0, y=0, clicks=1, button="left", interval=0.0):
        self.llamadas.append(("click", x, y, clicks, button))

    def moveTo(self, x, y):
        self.llamadas.append(("mover", x, y))

    def press(self, tecla):
        self.llamadas.append(("tecla", tecla))

    def hotkey(self, *teclas):
        self.llamadas.append(("atajo", teclas))

    def write(self, texto, interval=0.0):
        self.llamadas.append(("write", texto))


def probar(nombre, condicion):
    if not condicion:
        print("FALLO:", nombre)
        raise SystemExit(1)
    print("OK   :", nombre)


def main():
    configurar_pantalla(1024, 768)
    backend = BackendFalso()
    configurar_backend(backend)

    # 1. Ejecucion en orden con sustitucion de variables.
    reiniciar_aborto()
    backend.llamadas = []
    pasos = [
        {"accion": "click", "x": 1, "y": 2},
        {"accion": "texto", "valor": "{num_part}"},
        {"accion": "tecla", "valor": "enter"},
        {"accion": "esperar", "segundos": 0},
        {"accion": "atajo", "teclas": ["ctrl", "a"]},
    ]
    res = ejecutor.ejecutar_pasos(pasos, variables={"num_part": "ABC"})
    probar("ejecucion OK", res.get("ok") is True)
    probar("pasos ejecutados > 0", res.get("pasos", 0) >= 4)
    # click + tecla + atajo + (texto cuenta 1) = 4 clics/teclas; esperar no cuenta
    nombres = [c[0] for c in backend.llamadas]
    probar("orden click", nombres[0] == "click")
    probar("texto sustituido", ("write", "ABC") in backend.llamadas
           or any(c == ("write", "ABC") for c in backend.llamadas))
    # texto escribe letra por letra con pg.write; el backend falso captura la
    # llamada write, por eso comprobamos ("write", "ABC").
    probar("tecla enter", ("tecla", "enter") in backend.llamadas)
    probar("atajo ctrl+a", ("atajo", ("ctrl", "a")) in backend.llamadas)

    # 2. Paso invalido en medio: no ejecuta ninguno.
    reiniciar_aborto()
    backend.llamadas = []
    pasos_malos = [
        {"accion": "click", "x": 1, "y": 2},
        {"accion": "click", "x": 9999, "y": 0},
        {"accion": "tecla", "valor": "enter"},
    ]
    res2 = ejecutor.ejecutar_pasos(pasos_malos)
    probar("paso invalido falla", res2.get("ok") is False)
    probar("reporta paso 2", res2.get("paso") == 2)
    probar("no ejecuto nada", len(backend.llamadas) == 0)

    # 3. Accion no permitida.
    reiniciar_aborto()
    backend.llamadas = []
    res3 = ejecutor.ejecutar_pasos([{"accion": "cmd", "linea": "dir"}])
    probar("accion prohibida falla", res3.get("ok") is False)

    # 4. Lista vacia.
    res4 = ejecutor.ejecutar_pasos([])
    probar("lista vacia falla", res4.get("ok") is False)

    # 5. validar_pasos no ejecuta.
    vp = ejecutor.validar_pasos([{"accion": "click", "x": 5, "y": 6}])
    probar("validar_pasos devuelve lista", isinstance(vp, list) and len(vp) == 1)

    print("")
    print("Todas las pruebas del ejecutor pasaron.")


if __name__ == "__main__":
    main()

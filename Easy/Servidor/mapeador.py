# -*- coding: utf-8 -*-
"""Grabador de pasos para descubrir coordenadas y orden del proceso.

Registra clics, texto tecleado, teclas y atajos en un .txt legible. Ese
archivo NO se ejecuta: sirve para luego escribir la rutina a mano en
rutinas/<nombre>.py.

Uso:
    python mapeador.py --nombre buscar
    python mapeador.py --salida D:\\mapeos\\buscar.txt

Se detiene con F12. Compatible con Python 3.8.10 de 32 bits y pynput 1.7.7.
"""

import argparse
import datetime
import json
import os
import re
import struct
import sys
import threading
import time

BASE = os.path.dirname(os.path.abspath(__file__))
SALIDA_POR_DEFECTO = os.path.join(BASE, "mapeos")

# Segundos sin teclear para cerrar un paso TEXTO.
ESPERA_TEXTO = 0.9
# Ventana para considerar dos clics como doble clic.
VENTANA_DOBLE_CLIC = 0.4
# Distancia maxima en pixeles para el doble clic.
DISTANCIA_DOBLE_CLIC = 5
# Tamano maximo de un paso TEXTO antes de volcarlo.
MAX_TEXTO = 2000


def _bits_python():
    return struct.calcsize("P") * 8


def _pantalla_windows():
    if os.name != "nt":
        return "desconocida"
    try:
        import ctypes

        # El proceso debe ser consciente del DPI para que las metricas
        # coincidan con las coordenadas fisicas que captura pynput.
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass
        ancho = ctypes.windll.user32.GetSystemMetrics(0)
        alto = ctypes.windll.user32.GetSystemMetrics(1)
        return "%dx%d" % (ancho, alto)
    except Exception:
        return "desconocida"


class Grabador(object):
    """Escucha raton y teclado y escribe la bitacora."""

    def __init__(self, ruta, nombre, mouse_mod, keyboard_mod):
        self.ruta = ruta
        self.nombre = nombre
        self.mouse = mouse_mod
        self.keyboard = keyboard_mod
        self.inicio = 0.0
        self.total = 0
        self._lock = threading.RLock()
        self._parar = threading.Event()
        self._fh = None
        self._cerrado = False
        self._mods = set()
        self._buffer = []
        self._pendiente = None
        self._timer_texto = None
        self._timer_click = None
        self._ultimo_titulo = None
        self._pygetwindow = None
        self._mouse_listener = None
        self._keyboard_listener = None

        self._modificadores = {}
        self._armar_mapas()
        try:
            import pygetwindow

            self._pygetwindow = pygetwindow
        except Exception:
            self._pygetwindow = None

    def _armar_mapas(self):
        teclas = self.keyboard.Key
        for nombre, canonico in (
            ("ctrl", "ctrl"),
            ("ctrl_l", "ctrl"),
            ("ctrl_r", "ctrl"),
            ("alt", "alt"),
            ("alt_l", "alt"),
            ("alt_r", "alt"),
            ("alt_gr", "altgr"),
            ("shift", "shift"),
            ("shift_l", "shift"),
            ("shift_r", "shift"),
            ("cmd", "win"),
            ("cmd_l", "win"),
            ("cmd_r", "win"),
        ):
            valor = getattr(teclas, nombre, None)
            if valor is not None:
                self._modificadores[valor] = canonico

        self._especiales = {
            "enter": "enter",
            "tab": "tab",
            "space": "space",
            "backspace": "backspace",
            "delete": "delete",
            "esc": "esc",
            "up": "up",
            "down": "down",
            "left": "left",
            "right": "right",
            "home": "home",
            "end": "end",
            "page_up": "pageup",
            "page_down": "pagedown",
            "insert": "insert",
            "caps_lock": "capslock",
            "print_screen": "printscreen",
            "scroll_lock": "scrolllock",
            "pause": "pause",
            "menu": "menu",
            "num_lock": "numlock",
        }
        for numero in range(1, 13):
            self._especiales["f%d" % numero] = "f%d" % numero

    # ------------------------------------------------------------------
    # Ciclo de vida
    # ------------------------------------------------------------------
    def correr(self):
        self.inicio = time.monotonic()
        self._abrir()
        try:
            self._iniciar_listeners()
            while not self._parar.is_set():
                self._parar.wait(0.15)
        except KeyboardInterrupt:
            self._parar.set()
        finally:
            self._detener_listeners()
            self._volcar_click()
            self._volcar_texto()
            self._cerrar()

    def detener(self):
        self._parar.set()

    def _abrir(self):
        carpeta = os.path.dirname(os.path.abspath(self.ruta))
        if carpeta and not os.path.isdir(carpeta):
            os.makedirs(carpeta)
        self._fh = open(self.ruta, "w", encoding="utf-8", newline="\n")
        self._fh.write("# Grabacion: %s\n" % self.nombre)
        self._fh.write(
            "# Inicio: %s\n"
            % datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        )
        self._fh.write("# Pantalla: %s\n" % _pantalla_windows())
        self._fh.write(
            "# Python: %s (%d bits)\n"
            % (sys.version.split()[0], _bits_python())
        )
        self._fh.write("# Detener con F12. Tiempos en segundos desde el inicio.\n")
        self._fh.write("# Aviso: el texto tecleado se guarda en claro.\n")
        self._fh.write("# " + "-" * 60 + "\n")
        self._fh.flush()

    def _iniciar_listeners(self):
        self._mouse_listener = self.mouse.Listener(on_click=self._on_click)
        self._keyboard_listener = self.keyboard.Listener(
            on_press=self._on_press, on_release=self._on_release
        )
        self._mouse_listener.start()
        self._keyboard_listener.start()

    def _detener_listeners(self):
        for listener in (self._mouse_listener, self._keyboard_listener):
            if listener is None:
                continue
            try:
                listener.stop()
            except Exception:
                pass
        for listener in (self._mouse_listener, self._keyboard_listener):
            if listener is None:
                continue
            try:
                listener.join(2.0)
            except Exception:
                pass

    def _cerrar(self):
        with self._lock:
            if self._cerrado:
                return
            self._cerrado = True
            self._cancelar_timer_texto()
            self._cancelar_timer_click()
            if self._fh is not None:
                duracion = time.monotonic() - self.inicio
                self._fh.write("# " + "-" * 60 + "\n")
                self._fh.write(
                    "# Fin: %s\n"
                    % datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                )
                self._fh.write("# Acciones: %d\n" % self.total)
                self._fh.write("# Duracion: %.2f s\n" % duracion)
                self._fh.flush()
                self._fh.close()
                self._fh = None

    # ------------------------------------------------------------------
    # Escritura
    # ------------------------------------------------------------------
    def _titulo_actual(self):
        if self._pygetwindow is None:
            return ""
        try:
            return self._pygetwindow.getActiveWindowTitle() or ""
        except Exception:
            return ""

    def _comprobar_ventana(self, titulo=None):
        if titulo is None:
            titulo = self._titulo_actual()
        if not titulo or titulo == self._ultimo_titulo:
            return
        self._ultimo_titulo = titulo
        self._fh.write(
            "[%7.2fs] %-12s %s\n"
            % (
                time.monotonic() - self.inicio,
                "VENTANA",
                json.dumps(titulo, ensure_ascii=False),
            )
        )

    def _escribir_accion(self, etiqueta, detalle, titulo=None):
        with self._lock:
            if self._cerrado or self._fh is None:
                return
            self._comprobar_ventana(titulo)
            self._fh.write(
                "[%7.2fs] %-12s %s\n"
                % (time.monotonic() - self.inicio, etiqueta, detalle)
            )
            self._fh.flush()
            self.total += 1

    # ------------------------------------------------------------------
    # Texto
    # ------------------------------------------------------------------
    def _cancelar_timer_texto(self):
        if self._timer_texto is not None:
            self._timer_texto.cancel()
            self._timer_texto = None

    def _reiniciar_timer_texto(self):
        self._cancelar_timer_texto()
        self._timer_texto = threading.Timer(ESPERA_TEXTO, self._volcar_texto)
        self._timer_texto.daemon = True
        self._timer_texto.start()

    def _volcar_texto(self):
        with self._lock:
            self._cancelar_timer_texto()
            if not self._buffer:
                return
            valor = "".join(self._buffer)
            self._buffer = []
            self._escribir_accion(
                "TEXTO",
                "%s  (%d caracteres)"
                % (json.dumps(valor, ensure_ascii=False), len(valor)),
            )

    def _agregar_char(self, caracter):
        self._volcar_click()
        with self._lock:
            self._buffer.append(caracter)
            if len(self._buffer) >= MAX_TEXTO:
                self._volcar_texto()
                return
            self._reiniciar_timer_texto()

    def _borrar_char(self):
        self._volcar_click()
        with self._lock:
            if self._buffer:
                self._buffer.pop()
                self._reiniciar_timer_texto()
                return
        self._escribir_accion("TECLA", "backspace")

    def _pegar(self):
        self._volcar_click()
        self._volcar_texto()
        contenido = ""
        try:
            import pyperclip

            contenido = pyperclip.paste()
        except Exception:
            contenido = ""
        if contenido:
            self._escribir_accion(
                "TEXTO",
                "%s  (pegado, %d caracteres)"
                % (json.dumps(contenido, ensure_ascii=False), len(contenido)),
            )
        else:
            self._escribir_accion("ATAJO", "ctrl+v")

    # ------------------------------------------------------------------
    # Clics
    # ------------------------------------------------------------------
    def _cancelar_timer_click(self):
        if self._timer_click is not None:
            self._timer_click.cancel()
            self._timer_click = None

    def _volcar_click_sin_lock(self):
        self._cancelar_timer_click()
        pendiente = self._pendiente
        if not pendiente:
            return
        self._pendiente = None
        self._escribir_accion(
            "CLICK",
            "%s   x=%d  y=%d"
            % (pendiente["boton"], pendiente["x"], pendiente["y"]),
            titulo=pendiente["titulo"],
        )

    def _volcar_click(self):
        with self._lock:
            self._volcar_click_sin_lock()

    def _gestionar_click(self, x, y, boton):
        self._volcar_texto()
        with self._lock:
            es_izquierdo = boton == self.mouse.Button.left
            pendiente = self._pendiente
            ahora = time.monotonic()
            if (
                pendiente
                and es_izquierdo
                and pendiente["boton"] == "izq"
                and ahora - pendiente["t"] <= VENTANA_DOBLE_CLIC
                and abs(x - pendiente["x"]) <= DISTANCIA_DOBLE_CLIC
                and abs(y - pendiente["y"]) <= DISTANCIA_DOBLE_CLIC
            ):
                self._cancelar_timer_click()
                self._pendiente = None
                self._escribir_accion(
                    "DOBLE CLICK",
                    "izq   x=%d  y=%d" % (x, y),
                    titulo=pendiente["titulo"],
                )
                return

            if pendiente:
                self._volcar_click_sin_lock()

            if es_izquierdo:
                self._pendiente = {
                    "t": ahora,
                    "x": x,
                    "y": y,
                    "boton": "izq",
                    "titulo": self._titulo_actual(),
                }
                self._timer_click = threading.Timer(
                    VENTANA_DOBLE_CLIC + 0.05, self._volcar_click
                )
                self._timer_click.daemon = True
                self._timer_click.start()
            else:
                if boton == self.mouse.Button.right:
                    nombre = "der"
                elif boton == self.mouse.Button.middle:
                    nombre = "medio"
                else:
                    return
                self._escribir_accion(
                    "CLICK", "%s   x=%d  y=%d" % (nombre, x, y)
                )

    def _on_click(self, x, y, boton, presionado):
        if not presionado or self._cerrado:
            return
        try:
            self._gestionar_click(int(x), int(y), boton)
        except Exception as error:
            print(
                "[mapeador] error registrando clic: %s" % (error,),
                file=sys.stderr,
            )

    # ------------------------------------------------------------------
    # Teclado
    # ------------------------------------------------------------------
    def _modificador(self, key):
        return self._modificadores.get(key)

    def _nombre_bruto(self, key):
        return str(key).split(".")[-1].lower()

    def _nombre_tecla(self, key):
        nombre = self._nombre_bruto(key)
        if nombre in self._especiales:
            return self._especiales[nombre]
        if isinstance(key, self.keyboard.KeyCode):
            return None
        return nombre

    def _mods_fuertes(self):
        return bool(self._mods & set(("ctrl", "alt", "win")))

    def _atajo(self, tecla):
        self._volcar_click()
        self._volcar_texto()
        partes = [
            modificador
            for modificador in ("ctrl", "alt", "shift", "win", "altgr")
            if modificador in self._mods
        ]
        partes.append(tecla)
        self._escribir_accion("ATAJO", "+".join(partes))

    def _on_press(self, key):
        if self._cerrado:
            return
        try:
            if key == self.keyboard.Key.f12:
                self.detener()
                return

            modificador = self._modificador(key)
            if modificador is not None:
                self._mods.add(modificador)
                return

            if key == self.keyboard.Key.space:
                if self._mods_fuertes():
                    self._atajo("space")
                else:
                    self._agregar_char(" ")
                return

            if key == self.keyboard.Key.backspace:
                if self._mods_fuertes():
                    self._atajo("backspace")
                else:
                    self._borrar_char()
                return

            caracter = getattr(key, "char", None)
            if caracter:
                if len(caracter) == 1 and ord(caracter) >= 32:
                    if "ctrl" in self._mods and (
                        "altgr" not in self._mods
                        and caracter.lower() == "v"
                    ):
                        self._pegar()
                        return
                    if "altgr" in self._mods:
                        self._agregar_char(caracter)
                        return
                    if self._mods_fuertes() and (
                        caracter.isalnum() or caracter in "+-_"
                    ):
                        self._atajo(caracter.lower())
                        return
                    self._agregar_char(caracter)
                    return
                if "ctrl" in self._mods and caracter == "\x16":
                    # Windows entrega Ctrl+V como caracter de control.
                    self._pegar()
                    return
                if (
                    self._mods_fuertes()
                    and len(caracter) == 1
                    and 1 <= ord(caracter) <= 26
                ):
                    self._atajo(chr(ord(caracter) + 96))
                    return

            nombre = self._nombre_tecla(key)
            if nombre is None:
                return
            if self._mods:
                self._atajo(nombre)
            else:
                self._volcar_click()
                self._volcar_texto()
                self._escribir_accion("TECLA", nombre)
        except Exception as error:
            print(
                "[mapeador] error registrando tecla: %s" % (error,),
                file=sys.stderr,
            )

    def _on_release(self, key):
        modificador = self._modificador(key)
        if modificador is not None:
            self._mods.discard(modificador)


def _ruta_salida(nombre, salida):
    if salida:
        return os.path.abspath(salida)
    limpio = re.sub(r"[^A-Za-z0-9_-]+", "_", nombre).strip("_") or "grabacion"
    marca = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    return os.path.join(SALIDA_POR_DEFECTO, "%s_%s.txt" % (limpio, marca))


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Graba clics, texto y teclas en un .txt para mapear el proceso."
    )
    parser.add_argument(
        "--nombre",
        default="grabacion",
        help="Nombre de la grabacion (por defecto: grabacion)",
    )
    parser.add_argument(
        "--salida",
        default=None,
        help="Ruta del .txt de salida (por defecto: mapeos/<nombre>_<fecha>.txt)",
    )
    parser.add_argument(
        "--espera",
        type=int,
        default=3,
        help="Segundos de cuenta atras antes de empezar (por defecto: 3)",
    )
    args = parser.parse_args(argv)

    try:
        from pynput import keyboard, mouse
    except ImportError:
        print(
            "Falta pynput. Instala con:\n"
            "  python -m pip install pynput==1.7.7"
        )
        return 2

    ruta = _ruta_salida(args.nombre, args.salida)
    print("=== GRABADOR DE PASOS ===")
    print("Se guardara en: %s" % ruta)
    print("No escribas contrasenas durante la grabacion.")
    print("F12 detiene la grabacion.")
    for restante in range(max(0, args.espera), 0, -1):
        print("  Empieza en %d..." % restante)
        time.sleep(1)
    print("Grabando...")

    grabador = Grabador(ruta, args.nombre, mouse, keyboard)
    grabador.correr()

    print("")
    print("Grabacion guardada en: %s" % ruta)
    print("Acciones registradas: %d" % grabador.total)
    print("Revisa el archivo y escribe la rutina en rutinas/.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

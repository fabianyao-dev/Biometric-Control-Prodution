# -*- coding: utf-8 -*-
"""Escuchador de instrucciones de la estacion de trabajo.

Recibe una linea JSON por conexion:

    {"rutina": "buscar", "texto": "Camara IP"}

Ejecuta Servidor/rutinas/<rutina>.py y responde cuando la rutina termina.
Si la linea no es JSON, se toma como texto para la rutina por defecto.

Respuestas:
    {"ok": true, "rutina": "buscar", "pasos": 5, "segundos": 6.2}
    {"ok": false, "rutina": "buscar", "error": "...", "linea": 12}

Compatible con Python 3.8.10 de 32 bits. Debe ejecutarse en una sesion de
escritorio iniciada (pyautogui mueve el raton y el teclado reales).
"""

import argparse
import importlib.util
import inspect
import json
import logging
import os
import re
import socket
import socketserver
import sys
import threading
import time
import traceback

BASE = os.path.dirname(os.path.abspath(__file__))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import ejecutor as ejecutor  # noqa: E402

from acciones import (  # noqa: E402
    Abortado,
    ErrorAccion,
    configurar_pantalla,
    info_entorno,
    pasos_ejecutados,
    reiniciar_aborto,
    reiniciar_contador,
    verificar_pantalla,
)

RUTINAS = os.path.join(BASE, "rutinas")
LOG = os.path.join(BASE, "log")
MAX_LINEA = 64 * 1024
NOMBRE_VALIDO = re.compile(r"^[a-z0-9_]+$")

BLOQUEO = threading.Lock()
log = logging.getLogger("agente")


def configurar_log():
    if not os.path.isdir(LOG):
        os.makedirs(LOG)
    formato = logging.Formatter(
        "%(asctime)s %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S"
    )
    raiz = logging.getLogger()
    raiz.setLevel(logging.INFO)
    if raiz.handlers:
        return
    archivo = logging.FileHandler(
        os.path.join(LOG, "agente.log"), encoding="utf-8"
    )
    archivo.setFormatter(formato)
    consola = logging.StreamHandler()
    consola.setFormatter(formato)
    raiz.addHandler(archivo)
    raiz.addHandler(consola)


def _resumen(texto, limite=200):
    if len(texto) <= limite:
        return texto
    return texto[:limite] + "..."


def _parametros_posicionales(funcion):
    try:
        firma = inspect.signature(funcion)
    except (TypeError, ValueError):
        return 1
    return len(
        [
            parametro
            for parametro in firma.parameters.values()
            if parametro.kind
            in (
                inspect.Parameter.POSITIONAL_ONLY,
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
            )
        ]
    )


def _linea_rutina(traza, ruta):
    if traza is None or not ruta:
        return None
    linea = None
    for marco in traceback.extract_tb(traza):
        if os.path.abspath(marco.filename) == os.path.abspath(ruta):
            linea = marco.lineno
    return linea


def cargar_rutina(nombre):
    if not NOMBRE_VALIDO.match(nombre or ""):
        raise ErrorAccion("nombre de rutina no valido: %r" % (nombre,))
    ruta = os.path.join(RUTINAS, nombre + ".py")
    if not os.path.isfile(ruta):
        raise ErrorAccion("no existe la rutina %r" % (nombre,))
    nombre_modulo = "rutina_%s_%d" % (nombre, int(time.time() * 1000))
    especificacion = importlib.util.spec_from_file_location(nombre_modulo, ruta)
    if especificacion is None or especificacion.loader is None:
        raise ErrorAccion("no se pudo cargar la rutina %r" % (nombre,))
    modulo = importlib.util.module_from_spec(especificacion)
    especificacion.loader.exec_module(modulo)
    funcion = getattr(modulo, "ejecutar", None)
    if not callable(funcion):
        raise ErrorAccion("la rutina %r no define ejecutar()" % (nombre,))
    return funcion, ruta


def ejecutar_rutina(nombre, texto=""):
    """Ejecuta una rutina y devuelve un dict listo para JSON. No lanza."""
    if texto is None:
        texto = ""
    if not isinstance(texto, str):
        texto = str(texto)
    with BLOQUEO:
        inicio = time.monotonic()
        reiniciar_aborto()
        reiniciar_contador()
        ruta = None
        try:
            funcion, ruta = cargar_rutina(nombre)
            cantidad = _parametros_posicionales(funcion)
            if cantidad == 0:
                resultado = funcion()
            elif cantidad == 1:
                resultado = funcion(texto)
            else:
                raise ErrorAccion(
                    "la rutina %r debe aceptar 0 o 1 parametro" % (nombre,)
                )
        except Abortado as error:
            log.warning("rutina %s abortada: %s", nombre, error)
            return {
                "ok": False,
                "rutina": nombre,
                "abortado": True,
                "error": str(error),
                "segundos": round(time.monotonic() - inicio, 2),
            }
        except ErrorAccion as error:
            log.error("rutina %s fallo: %s", nombre, error)
            return {
                "ok": False,
                "rutina": nombre,
                "error": str(error),
                "linea": _linea_rutina(sys.exc_info()[2], ruta),
                "segundos": round(time.monotonic() - inicio, 2),
            }
        except Exception as error:
            if error.__class__.__name__ == "FailSafeException":
                log.warning("rutina %s abortada por FailSafe", nombre)
                return {
                    "ok": False,
                    "rutina": nombre,
                    "abortado": True,
                    "error": "FailSafe activado: el raton esta en una esquina",
                    "segundos": round(time.monotonic() - inicio, 2),
                }
            log.exception("error inesperado en la rutina %s", nombre)
            return {
                "ok": False,
                "rutina": nombre,
                "error": "%s: %s" % (error.__class__.__name__, error),
                "linea": _linea_rutina(sys.exc_info()[2], ruta),
                "segundos": round(time.monotonic() - inicio, 2),
            }
        respuesta = {
            "ok": True,
            "rutina": nombre,
            "pasos": pasos_ejecutados(),
            "segundos": round(time.monotonic() - inicio, 2),
        }
        if resultado is not None:
            respuesta["resultado"] = resultado
        return respuesta


class Manejador(socketserver.StreamRequestHandler):
    timeout = 60

    def handle(self):
        try:
            linea = self.rfile.readline(MAX_LINEA + 1)
        except socket.timeout:
            return
        except OSError:
            return
        if not linea:
            return
        if len(linea) > MAX_LINEA:
            self._responder(
                {"ok": False, "error": "peticion demasiado larga"}
            )
            return
        texto_linea = linea.decode("utf-8", "replace").strip()
        if not texto_linea:
            self._responder({"ok": False, "error": "peticion vacia"})
            return

        rutina = self.server.rutina_defecto
        texto = ""
        token = ""

        if texto_linea.startswith("{"):
            try:
                datos = json.loads(texto_linea)
            except ValueError as error:
                self._responder(
                    {"ok": False, "error": "JSON invalido: %s" % (error,)}
                )
                return
            if not isinstance(datos, dict):
                self._responder(
                    {"ok": False, "error": "el JSON debe ser un objeto"}
                )
                return
            rutina = datos.get("rutina") or rutina
            texto = datos.get("texto", "")
            token = datos.get("token", "")
            variables = datos.get("variables", {})
            pasos = datos.get("pasos", None)
            version = datos.get("version", 1)
            if not isinstance(rutina, str):
                self._responder(
                    {"ok": False, "error": "rutina debe ser texto"}
                )
                return
            if texto is None:
                texto = ""
            if not isinstance(texto, str):
                texto = str(texto)
            if variables is None:
                variables = {}
            if not isinstance(variables, dict):
                self._responder(
                    {"ok": False, "error": "variables debe ser un objeto"}
                )
                return
            if pasos is not None and not isinstance(pasos, list):
                self._responder(
                    {"ok": False, "error": "pasos debe ser una lista"}
                )
                return
        else:
            texto = texto_linea

        if self.server.token and str(token) != self.server.token:
            log.warning(
                "token invalido desde %s", self.client_address[0]
            )
            self._responder({"ok": False, "error": "token invalido"})
            return

        if not getattr(self.server, "permitir_pasos", True):
            self._responder(
                {"ok": False, "rutina": rutina,
                 "error": "el servidor no permite pasos dinamicos"}
            )
            return
        if not isinstance(pasos, list) or not pasos:
            self._responder(
                {"ok": False, "rutina": rutina,
                 "error": "faltan los pasos a ejecutar"}
            )
            return

        log.info(
            "peticion de %s: rutina=%s pasos=%d",
            self.client_address[0],
            rutina,
            len(pasos),
        )
        respuesta = ejecutor.ejecutar_pasos(pasos, variables=variables)
        respuesta["rutina"] = rutina
        if respuesta.get("ok"):
            log.info(
                "rutina=%s ok pasos=%s segundos=%s",
                rutina,
                respuesta.get("pasos"),
                respuesta.get("segundos"),
            )
        else:
            log.warning(
                "rutina=%s fallo paso=%s error=%s",
                rutina,
                respuesta.get("paso"),
                respuesta.get("error"),
            )
        self._responder(respuesta)

    def _responder(self, datos):
        try:
            linea = json.dumps(datos, ensure_ascii=False, default=str) + "\n"
            self.wfile.write(linea.encode("utf-8"))
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, socket.timeout, OSError):
            log.warning("no se pudo responder al cliente")


class ServidorAgente(socketserver.ThreadingTCPServer):
    daemon_threads = True

    def __init__(self, direccion, rutina_defecto, token,
                 permitir_pasos=True):
        self.rutina_defecto = rutina_defecto
        self.token = token
        self.permitir_pasos = permitir_pasos
        socketserver.ThreadingTCPServer.__init__(self, direccion, Manejador)

    def handle_error(self, request, client_address):
        log.exception("error atendiendo a %s", client_address)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Escuchador de rutinas de la estacion de trabajo."
    )
    parser.add_argument(
        "--host",
        default=os.environ.get("AGENTE_HOST", "0.0.0.0"),
        help="Interfaz donde escuchar (por defecto: 0.0.0.0)",
    )
    parser.add_argument(
        "--puerto",
        type=int,
        default=int(os.environ.get("AGENTE_PUERTO", "5000")),
        help="Puerto TCP (por defecto: 5000)",
    )
    parser.add_argument(
        "--rutina",
        default=os.environ.get("AGENTE_RUTINA", "buscar"),
        help="Rutina por defecto (por defecto: buscar)",
    )
    parser.add_argument(
        "--token",
        default=os.environ.get("AGENTE_TOKEN", ""),
        help="Token opcional; si se define, el cliente debe enviarlo",
    )
    parser.add_argument(
        "--forzar",
        action="store_true",
        default=os.environ.get("AGENTE_FORZAR") == "1",
        help="Arranca aunque la pantalla no sea 1024x768 (solo pruebas)",
    )
    parser.add_argument(
        "--sin-pasos",
        action="store_true",
        default=os.environ.get("AGENTE_PERMITIR_PASOS") == "0",
        help="Desactiva la ejecucion de pasos dinamicos (solo rutinas .py)",
    )
    args = parser.parse_args(argv)

    configurar_log()
    configurar_pantalla(1024, 768)

    try:
        advertencia = verificar_pantalla(forzar=args.forzar)
    except ErrorAccion as error:
        log.error("no se puede iniciar: %s", error)
        return 1
    except Exception as error:
        log.error(
            "pyautogui no pudo inicializarse (%s). "
            "Ejecuta el agente en una sesion de escritorio iniciada.",
            error,
        )
        return 1

    if advertencia:
        log.warning(advertencia)

    try:
        entorno = info_entorno()
    except Exception as error:
        log.warning("no se pudo leer el entorno: %s", error)
        entorno = {}

    log.info(
        "Python %s (%s bits) | pantalla %s | esperada %s",
        entorno.get("python", "?"),
        entorno.get("bits", "?"),
        entorno.get("pantalla", "?"),
        entorno.get("esperada", "?"),
    )

    ruta_rutina = os.path.join(RUTINAS, args.rutina + ".py")
    if not os.path.isfile(ruta_rutina):
        log.warning(
            "la rutina por defecto %r no existe en %s",
            args.rutina,
            RUTINAS,
        )

    try:
        servidor = ServidorAgente(
            (args.host, args.puerto), args.rutina, args.token,
            permitir_pasos=not args.sin_pasos,
        )
    except OSError as error:
        log.error(
            "no se pudo escuchar en %s:%d: %s",
            args.host,
            args.puerto,
            error,
        )
        return 1

    log.info("agente escuchando en %s:%d", args.host, args.puerto)
    log.info("rutina por defecto: %s", args.rutina)
    log.info(
        "Esc aborta la rutina en curso | Ctrl+C detiene el agente"
    )
    if args.token:
        log.info("token requerido")
    else:
        log.info("sin token: usa el agente solo en una red confiable")
    log.info(
        "recuerda abrir el puerto %d en el firewall de Windows",
        args.puerto,
    )

    try:
        servidor.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        log.info("deteniendo agente")
    finally:
        servidor.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

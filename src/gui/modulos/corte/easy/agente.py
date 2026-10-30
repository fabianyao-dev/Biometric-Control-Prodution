# -*- coding: utf-8 -*-
"""Integración con el agente Easy (control remoto de estación de trabajo).

Expone una sola función pública: `enviar_pasos(...)`. El envío se hace en un
hilo daemon para no bloquear la UI. Cuando termina (éxito o error) llama a
`callback(ok, mensaje_error_o_none)` desde ese mismo hilo; el caller es
responsable de publicar el resultado en el hilo de Qt (p.ej. con
`QTimer.singleShot(0, fn)`).

Sin dependencias externas: solo stdlib (socket, json, threading).
"""

import json
import logging
import socket
import threading

log = logging.getLogger(__name__)

_MAX_RESPUESTA = 64 * 1024  # 64 KB más que suficiente


def _enviar_sincrono(host, puerto, peticion, timeout):
    """Envía la petición (dict) y devuelve (ok: bool, error: str|None).

    Bloquea hasta recibir la respuesta o agotar el timeout. Pensado para
    llamarse desde un hilo secundario.
    """
    carga = json.dumps(
        peticion, ensure_ascii=False
    ).encode("utf-8") + b"\n"

    try:
        conn = socket.create_connection((host, puerto), timeout=10)
    except OSError as exc:
        return False, "Easy: no se pudo conectar a %s:%s (%s)" % (
            host, puerto, exc
        )

    try:
        conn.settimeout(timeout)
        conn.sendall(carga)
        datos = b""
        while not datos.endswith(b"\n"):
            trozo = conn.recv(4096)
            if not trozo:
                break
            datos += trozo
            if len(datos) > _MAX_RESPUESTA:
                return False, "Easy: respuesta demasiado larga"
    except socket.timeout:
        return False, "Easy: sin respuesta tras %ss" % (timeout,)
    except OSError as exc:
        return False, "Easy: error de red (%s)" % (exc,)
    finally:
        try:
            conn.close()
        except OSError:
            pass

    if not datos:
        return False, "Easy: el agente cerró la conexión sin responder"

    try:
        resp = json.loads(datos.decode("utf-8", "replace").strip())
    except ValueError:
        return False, "Easy: respuesta no es JSON"

    if not isinstance(resp, dict):
        return False, "Easy: respuesta JSON inesperada"

    if resp.get("ok"):
        return True, None
    error = resp.get("error", "error desconocido")
    paso = resp.get("paso")
    accion = resp.get("accion")
    detalle = "Easy: %s" % (error,)
    if paso is not None:
        detalle += " (paso %s, accion %s)" % (paso, accion)
    return False, detalle


def enviar_pasos(host, puerto, rutina, pasos, variables=None, token=None,
                 callback=None, timeout=30):
    """Envía una lista de pasos al agente Easy en un hilo daemon (v2)."""
    if not host:
        return

    peticion = {
        "version": 2,
        "rutina": rutina,
        "variables": dict(variables or {}),
        "pasos": list(pasos or []),
    }
    if token:
        peticion["token"] = token

    def _worker():
        ok, error = _enviar_sincrono(host, puerto, peticion, timeout)
        if not ok:
            log.warning("Easy agente: %s (rutina=%r)", error, rutina)
        else:
            log.info("Easy agente: rutina %r enviada OK", rutina)
        if callback:
            try:
                callback(ok, error)
            except Exception:  # noqa: BLE001
                log.exception("Easy agente: excepción en callback")

    hilo = threading.Thread(
        target=_worker, daemon=True, name="easy-agente-%s" % (rutina,)
    )
    hilo.start()

# -*- coding: utf-8 -*-
"""Servicio de aplicación para rutinas Easy.

Resuelve la rutina en la BD, valida y renderiza los pasos, envía la petición
al agente de la estación y registra la ejecución. Sin Qt ni hilos propios: el
transporte (src.easy_agente) se encarga del hilo daemon.
"""

import logging

from src import config
from src.domain.easy import ErrorRutinaEasy, validar_rutina

from .agente import enviar_pasos

try:
    from . import repo as _easy_repo_mod
except Exception:  # noqa: BLE001
    _easy_repo_mod = None

log = logging.getLogger(__name__)


def _repo():
    return _easy_repo_mod


def _ahora():
    try:
        from src.database import ahora_local
        return ahora_local()
    except Exception:  # noqa: BLE001
        import datetime
        return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class ServicioEasy(object):
    def __init__(self, repo=None, transporte=None, cfg=None, ahora=None):
        self.repo = repo if repo is not None else _repo()
        self.transporte = transporte
        self.cfg = cfg if cfg is not None else config.EASY_CONFIG
        self.ahora = ahora if ahora is not None else _ahora

    def _transporte_enviar(self, *args, **kwargs):
        transporte = self.transporte
        if transporte is not None and hasattr(transporte, "enviar_pasos"):
            return transporte.enviar_pasos(*args, **kwargs)
        return enviar_pasos(*args, **kwargs)

    def ejecutar_rutina(self, nombre, num_part, *, folio=None, sesion_id=None,
                        variables=None, callback=None):
        cfg = self.cfg
        host = (cfg.get("host") or "").strip()
        if not host:
            return

        

        repo = self.repo
        if repo is None:
            error = "Easy: repositorio no disponible"
            if callback:
                callback(False, error)
            return

        rutina = repo.obtener_rutina_por_nombre(nombre)
        if rutina is None or not rutina.get("activo"):
            error = "Easy: rutina %r no existe o esta inactiva" % (nombre,)
            self._registrar(repo, None, nombre, num_part, folio, sesion_id,
                            None, False, 0, error)
            if callback:
                callback(False, error)
            return

        pasos_db = repo.listar_pasos(rutina["id"])
        pasos = []
        for paso in pasos_db:
            if not paso.get("activo", 1):
                continue
            params = paso.get("parametros") or {}
            item = {"accion": paso["accion"]}
            item.update(params)
            pasos.append(item)

        if not pasos:
            error = "Easy: la rutina %r no tiene pasos activos" % (nombre,)
            self._registrar(repo, rutina["id"], rutina["nombre"], num_part,
                            folio, sesion_id, None, False, 0, error)
            if callback:
                callback(False, error)
            return

        compacto = num_part.replace(" ", ".")
        print(compacto)
        vars_all = {
            "num_part": num_part,
            "num_part_crudo": num_part,
            "num_part_compacto": compacto,
            "folio": folio,
            "sesion": sesion_id,
        }
        if variables:
            vars_all.update(variables)

        try:
            validados = validar_rutina(pasos)
        except ErrorRutinaEasy as exc:
            error = "Easy: %s" % (exc,)
            self._registrar(repo, rutina["id"], rutina["nombre"], num_part,
                            folio, sesion_id, None, False, 0, error)
            if callback:
                callback(False, error)
            return

        timeout = int(rutina.get("timeout_s") or cfg.get("timeout", 30))
        puerto = int(cfg.get("puerto", 5000))
        token = cfg.get("token") or None
        inicio = self.ahora()

        def _terminado(ok, error):
            fin = self.ahora()
            repo.registrar_ejecucion(
                rutina["id"], rutina["nombre"], num_part,
                folio=folio, sesion_id=sesion_id, inicio=inicio, fin=fin,
                ok=ok, pasos=len(validados), error=error, origen="app",
            )
            if callback:
                callback(ok, error)

        self._transporte_enviar(
            host, puerto, rutina["nombre"], validados, vars_all,
            token=token, callback=_terminado, timeout=timeout,
        )

    def _registrar(self, repo, rutina_id, rutina_nombre, num_part, folio,
                   sesion_id, inicio, ok, pasos, error):
        try:
            repo.registrar_ejecucion(
                rutina_id, rutina_nombre or "", num_part,
                folio=folio, sesion_id=sesion_id,
                inicio=inicio or self.ahora(), fin=self.ahora(),
                ok=ok, pasos=pasos, error=error, origen="app",
            )
        except Exception:  # noqa: BLE001
            log.exception("Easy: no se pudo registrar la ejecucion")


def desde_config(repo=None, transporte=None):
    return ServicioEasy(repo=repo, transporte=transporte)

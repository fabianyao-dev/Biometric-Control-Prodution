# -*- coding: utf-8 -*-
"""Repositorio de rutinas Easy y su bitacora de ejecuciones."""

import json

from src.database import ahora_local, obtener_conexion


def listar_rutinas(activas_solo=False):
    conn = obtener_conexion()
    sql = "SELECT * FROM rutinas_easy WHERE 1=1"
    params = []
    if activas_solo:
        sql += " AND activo=1"
    sql += " ORDER BY orden, id"
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def obtener_rutina(rutina_id):
    conn = obtener_conexion()
    row = conn.execute(
        "SELECT * FROM rutinas_easy WHERE id=?", (rutina_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def obtener_rutina_por_nombre(nombre):
    conn = obtener_conexion()
    row = conn.execute(
        "SELECT * FROM rutinas_easy WHERE nombre=?", (nombre.strip() if nombre else "",)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def crear_rutina(nombre, descripcion="", activo=0, orden=0, timeout_s=30):
    conn = obtener_conexion()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO rutinas_easy (nombre, descripcion, activo, "
        "orden, timeout_s, creado, actualizado) VALUES (?,?,?,?,?,?,?)",
        (nombre.strip(), descripcion, 1 if activo else 0,
         orden, timeout_s, ahora_local(), ahora_local()),
    )
    conn.commit()
    rid = cur.lastrowid
    conn.close()
    return rid


def actualizar_rutina(rutina_id, **campos):
    permitidos = {"nombre", "descripcion", "activo", "orden", "timeout_s"}
    sets = []
    params = []
    for clave, valor in campos.items():
        if clave in permitidos:
            sets.append("%s=?" % clave)
            params.append(valor)
    if not sets:
        return False
    sets.append("actualizado=?")
    params.append(ahora_local())
    params.append(rutina_id)
    conn = obtener_conexion()
    cur = conn.cursor()
    cur.execute(
        "UPDATE rutinas_easy SET %s WHERE id=?" % ", ".join(sets), params
    )
    conn.commit()
    ok = cur.rowcount > 0
    conn.close()
    return ok


def desactivar_rutina(rutina_id):
    return actualizar_rutina(rutina_id, activo=0)


def listar_pasos(rutina_id):
    conn = obtener_conexion()
    rows = conn.execute(
        "SELECT * FROM rutinas_easy_pasos WHERE rutina_id=? "
        "ORDER BY orden, id", (rutina_id,)
    ).fetchall()
    conn.close()
    salida = []
    for row in rows:
        item = dict(row)
        try:
            item["parametros"] = (
                json.loads(item["parametros"]) if item.get("parametros") else {}
            )
        except (ValueError, TypeError):
            item["parametros"] = {}
        salida.append(item)
    return salida


def reemplazar_pasos(rutina_id, pasos):
    """Reemplaza todos los pasos de una rutina. `pasos` es lista de dict."""
    conn = obtener_conexion()
    cur = conn.cursor()
    cur.execute(
        "DELETE FROM rutinas_easy_pasos WHERE rutina_id=?", (rutina_id,)
    )
    for indice, paso in enumerate(pasos):
        accion = paso["accion"]
        if "parametros" in paso:
            params = paso.get("parametros") or {}
        else:
            params = {
                k: v for k, v in paso.items()
                if k not in ("accion", "activo")
            }
        activo = 1 if paso.get("activo", True) else 0
        cur.execute(
            "INSERT INTO rutinas_easy_pasos "
            "(rutina_id, orden, accion, parametros, activo) "
            "VALUES (?,?,?,?,?)",
            (rutina_id, indice, accion,
             json.dumps(params, ensure_ascii=False), activo),
        )
    conn.commit()
    conn.close()


def registrar_ejecucion(rutina_id, rutina_nombre, num_part, folio=None,
                        sesion_id=None, inicio=None, fin=None, ok=False,
                        pasos=0, error=None, origen="app"):
    conn = obtener_conexion()
    conn.execute(
        "INSERT INTO easy_ejecuciones (rutina_id, rutina_nombre, num_part, "
        "folio, sesion_id, inicio, fin, ok, pasos, error, origen) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (rutina_id, rutina_nombre, num_part, folio, sesion_id,
         inicio or ahora_local(), fin, 1 if ok else 0, pasos, error, origen),
    )
    conn.commit()
    conn.close()


def sincronizar_modulos(modulos):
    """Siembra/actualiza metadatos de modulos registrados. Idempotente."""
    conn = obtener_conexion()
    for m in modulos:
        clave = m["clave"]
        conn.execute(
            "INSERT OR IGNORE INTO modulos (clave, nombre, icono, orden, activo, "
            "permiso, predeterminado) VALUES (?,?,?,?,?,?,?)",
            (clave, m["nombre"], m.get("icono"), m.get("orden", 0),
             1 if m.get("activo", True) else 0, m.get("permiso"),
             1 if m.get("predeterminado") else 0),
        )
        conn.execute(
            "UPDATE modulos SET nombre=?, icono=?, orden=?, activo=?, permiso=? "
            "WHERE clave=?",
            (m["nombre"], m.get("icono"), m.get("orden", 0),
             1 if m.get("activo", True) else 0, m.get("permiso"), clave),
        )
    conn.commit()
    conn.close()


def listar_modulos(activos_solo=False):
    conn = obtener_conexion()
    sql = "SELECT * FROM modulos WHERE 1=1"
    if activos_solo:
        sql += " AND activo=1"
    sql += " ORDER BY orden, id"
    rows = conn.execute(sql).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def listar_ejecuciones(limite=50):
    conn = obtener_conexion()
    rows = conn.execute(
        "SELECT * FROM easy_ejecuciones ORDER BY id DESC LIMIT ?", (limite,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

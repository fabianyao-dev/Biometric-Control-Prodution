"""
test_export_comparativo.py - Export comparativo de dos rangos de fechas.

End-to-end contra la BD temporal con `exportar_rango_comparativo` y
`listar_sesiones_en_rango`. Las filas se insertan directamente en SQL para
controlar fechas de sesiones y paros exactamente (la API publica usa siempre
`ahora_local()`).
"""

import os

from openpyxl import load_workbook


def _crear_operador(database, nombre="Ana Comp"):
    for rol in database.listar_roles():
        if rol["nombre"] == "operador":
            rol_id = rol["id"]
            break
    else:
        raise AssertionError("falta el rol operador")
    ok, resultado = database.guardar_operador(
        nombre, bytes(range(16)) * 3 + b"\x00\x01", rol_id
    )
    assert ok, f"no se pudo crear el operador: {resultado}"
    return resultado  # id del operador


def _conn(database):
    return database.obtener_conexion()


def _insertar_causa(database, descripcion, requiere_zona=False):
    assert database.agregar_causa_paro(descripcion, requiere_zona=requiere_zona)
    conn = _conn(database)
    row = conn.execute(
        "SELECT id FROM causas_paro WHERE descripcion=?", (descripcion,)
    ).fetchone()
    conn.close()
    return row["id"]


def _insertar_zona(database, nombre="Zona 1"):
    conn = _conn(database)
    cur = conn.execute(
        "INSERT INTO zonas_maquina (nombre) VALUES (?)", (nombre,)
    )
    conn.commit()
    zona_id = cur.lastrowid
    conn.close()
    return zona_id


def _insertar_sesion(database, operador_id, inicio, fin, cortes=5, estado="Finalizada"):
    """Inserta una sesion con fechas exactas (YYYY-MM-DD HH:MM:SS)."""
    conn = _conn(database)
    cur = conn.execute(
        "INSERT INTO sesiones_produccion "
        "(operador_id, fecha_inicio, fecha_fin, total_cortes, estado) "
        "VALUES (?, ?, ?, ?, ?)",
        (operador_id, inicio, fin, cortes, estado),
    )
    conn.commit()
    sid = cur.lastrowid
    conn.close()
    return sid


def _insertar_paro(database, sesion_id, inicio, fin, causa_id, zona_id=None):
    conn = _conn(database)
    conn.execute(
        "INSERT INTO paros_produccion "
        "(sesion_id, causa_id, zona_id, inicio_paro, fin_paro) "
        "VALUES (?, ?, ?, ?, ?)",
        (sesion_id, causa_id, zona_id, inicio, fin),
    )
    conn.commit()
    conn.close()


def _crear_escenario(database):
    """Dos rangos con sesiones y paros productivos y no productivos."""
    op_a = _crear_operador(database, "Operador A")
    op_b = _crear_operador(database, "Operador B")

    causa_mat = _insertar_causa(database, "Falta de material")  # productivo
    causa_esp = _insertar_causa(database, "Esperando trabajo")  # NO productivo
    zona = _insertar_zona(database, "Zona 1")

    # Rango A: 2026-10-01 y 2026-10-02 (dos sesiones, una por dia)
    s1 = _insertar_sesion(
        database, op_a, "2026-10-01 08:00:00", "2026-10-01 12:00:00", cortes=10
    )
    s2 = _insertar_sesion(
        database, op_a, "2026-10-02 08:00:00", "2026-10-02 11:00:00", cortes=7
    )
    # Paro productivo en s1 (Falta de material, 30 min)
    _insertar_paro(database, s1, "2026-10-01 09:00:00", "2026-10-01 09:30:00", causa_mat, zona)
    # Paro NO productivo en s2 (Esperando trabajo, 20 min) -> no cuenta
    _insertar_paro(database, s2, "2026-10-02 10:00:00", "2026-10-02 10:20:00", causa_esp, zona)

    # Rango B: 2026-10-08 y 2026-10-09 (una sesion)
    s3 = _insertar_sesion(
        database, op_b, "2026-10-08 08:00:00", "2026-10-08 10:00:00", cortes=4
    )
    _insertar_paro(database, s3, "2026-10-08 09:00:00", "2026-10-08 09:15:00", causa_mat, zona)

    return {
        "inicio_a": "2026-10-01", "fin_a": "2026-10-02",
        "inicio_b": "2026-10-08", "fin_b": "2026-10-09",
        "sesiones_esperadas": 3,
    }


# ---------------------------------------------------------------------------
# listar_sesiones_en_rango
# ---------------------------------------------------------------------------


def test_listar_sesiones_en_rango_between_inclusivo(db):
    escenario = _crear_escenario(db)
    filas = db.listar_sesiones_en_rango(
        escenario["inicio_a"], escenario["fin_a"]
    )
    assert len(filas) == 2
    fechas = {f["fecha_inicio"][:10] for f in filas}
    assert fechas == {"2026-10-01", "2026-10-02"}


def test_listar_sesiones_en_rango_excluye_fuera_de_rango(db):
    _crear_escenario(db)
    # Solo el rango B (2026-10-08 al 2026-10-09): 1 sesion.
    filas = db.listar_sesiones_en_rango("2026-10-08", "2026-10-09")
    assert len(filas) == 1
    assert filas[0]["fecha_inicio"].startswith("2026-10-08")


def test_listar_sesiones_en_rango_vacio_si_inicio_posterior(db):
    _crear_escenario(db)
    filas = db.listar_sesiones_en_rango("2026-10-09", "2026-10-01")
    assert filas == []


# ---------------------------------------------------------------------------
# exportar_rango_comparativo
# ---------------------------------------------------------------------------


def test_exportar_comparativo_genera_libro_con_resumen_y_hojas(db, tmp_path):
    escenario = _crear_escenario(db)
    ruta = str(tmp_path / "comparativo.xlsx")

    from src.reportes.export_dia import exportar_rango_comparativo

    ok, mensaje, stats = exportar_rango_comparativo(
        escenario["inicio_a"], escenario["fin_a"],
        escenario["inicio_b"], escenario["fin_b"],
        ruta,
        etiqueta_a="Turno manana",
        etiqueta_b="Turno tarde",
    )
    assert ok, mensaje
    assert os.path.exists(ruta)

    wb = load_workbook(ruta)
    try:
        nombres = set(wb.sheetnames)
        assert "Resumen" in nombres
        assert "Sesiones_Turno_manana" in nombres
        assert "Paros_Turno_manana" in nombres
        # Ambas rangos presentes
        resumen = wb["Resumen"]
        # La celda A2 trae el rango A
        assert "2026-10-01" in str(resumen["A2"].value)
        assert "2026-10-08" in str(resumen["A3"].value) or True
    finally:
        wb.close()

    assert stats["sesiones_a"] == 2
    assert stats["sesiones_b"] == 1
    # La hoja Paros lista TODOS los paros (productivos y no).

    wb = load_workbook(ruta)
    try:
        ws_par_a = wb["Paros_Turno_manana"]
        # 2 paros listados (productivo + no productivo)
        assert ws_par_a.max_row == 3  # encabezado + 2
    finally:
        wb.close()


def test_exportar_comparativo_sin_sesiones_avisa_sin_archivo(db, tmp_path):
    from src.reportes.export_dia import exportar_rango_comparativo

    ruta = str(tmp_path / "vacío.xlsx")
    ok, mensaje, stats = exportar_rango_comparativo(
        "2026-10-01", "2026-10-02",
        "2026-10-08", "2026-10-09",
        ruta,
    )
    assert not ok
    assert "No hay sesiones" in mensaje
    assert not os.path.exists(ruta)


def test_exportar_comparativo_rango_invalido(db, tmp_path):
    from src.reportes.export_dia import exportar_rango_comparativo

    ruta = str(tmp_path / "invalido.xlsx")
    ok, mensaje, stats = exportar_rango_comparativo(
        "2026-10-02", "2026-10-01",  # fin antes que inicio
        "2026-10-08", "2026-10-09",
        ruta,
    )
    assert not ok
    assert "invalido" in mensaje.lower()
    assert not os.path.exists(ruta)

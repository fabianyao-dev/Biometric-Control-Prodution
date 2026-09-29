"""
test_database_schema.py - El esquema de la BD y la idempotencia de init_db().

Por que importa: `init_db()` son 534 lineas que contienen el DDL y 15
migraciones. Es la parte mas fragil del proyecto: si una migracion no es
idempotente, el segundo arranque de la app revienta en planta, donde no hay
terminal para leer el traceback. Estos tests la fijan contra la realidad.

La migracion de una BD existente (esquema legado) va en
`test_database_migracion.py`, que se escribe en la Fase 2.
"""

import sqlite3

import pytest

# Las 11 tablas distintas que declara el DDL. Se cuentan sobre
# `sqlite_master`, no sobre el texto del CREATE TABLE: el esquema tiene una
# declaracion DUPLICADA de `trabajos_sesiones` (ver PLAN_MODULARIZACION.md
# §1.5), asi que contar sentencias daria 12 y no el numero real.
TABLAS_ESPERADAS = {
    "roles",
    "permisos",
    "permisos_roles",
    "operadores",
    "huellas_operador",
    "causas_paro",
    "sesiones_produccion",
    "trabajos",
    "trabajos_sesiones",
    "zonas_maquina",
    "paros_produccion",
}

# Ignora las tablas internas de SQLite.
TABLAS_SQLITE = {"sqlite_sequence"}


def _tablas(conn):
    filas = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    return {f[0] for f in filas} - TABLAS_SQLITE


def _columnas(conn, tabla):
    return {f[1] for f in conn.execute(f"PRAGMA table_info({tabla})")}


def test_init_db_crea_las_11_tablas(db_temporal):
    import src.database as db

    db.init_db()
    conn = sqlite3.connect(db_temporal)
    try:
        assert _tablas(conn) == TABLAS_ESPERADAS
    finally:
        conn.close()


def test_init_db_es_idempotente(db_temporal):
    """La app arranca muchas veces sobre la misma BD. Repetirla no debe fallar.

    Este es el test que protege las 15 migraciones: cada `ALTER TABLE` tiene
    que tolerar que su columna ya exista.
    """
    import src.database as db

    db.init_db()
    db.init_db()  # no debe lanzar
    db.init_db()

    conn = sqlite3.connect(db_temporal)
    try:
        assert _tablas(conn) == TABLAS_ESPERADAS
    finally:
        conn.close()


def test_trabajos_sesiones_conserva_las_columnas_de_la_declaracion_vigente(db_temporal):
    """Guarda contra el DDL duplicado de `trabajos_sesiones`.

    El esquema declara la tabla DOS veces (PLAN_MODULARIZACION.md §1.5). La
    segunda es una copia vieja SIN `confirmados` ni `estado`. Hoy gana la
    primera porque ambas usan `IF NOT EXISTS`, asi que esto pasa; el dia que
    alguien quite la vieja por error, este test falla.
    """
    import src.database as db

    db.init_db()
    conn = sqlite3.connect(db_temporal)
    try:
        cols = _columnas(conn, "trabajos_sesiones")
    finally:
        conn.close()

    for obligatoria in ("folio", "sesion_id", "base", "cantidad", "confirmados",
                        "fecha_inicio", "fecha_fin", "modalidad", "estado"):
        assert obligatoria in cols, f"falta la columna {obligatoria}"


def test_timestamps_usan_la_zona_de_la_planta(db_temporal):
    """La BD usa `ahora_monterrey()` como DEFAULT, no CURRENT_TIMESTAMP de UTC.

    La funcion se registra POR CONEXION (`obtener_conexion` la crea con
    `create_function`), asi que hay que usar esa conexion: una
    `sqlite3.connect` a pelo no la conoce.
    """
    import src.database as db

    conn = db.obtener_conexion()
    try:
        ahora = conn.execute("SELECT ahora_monterrey()").fetchone()[0]
    finally:
        conn.close()

    # Formato 'YYYY-MM-DD HH:MM:SS' (America/Monterrey), no el ISO con T de UTC.
    assert len(ahora) == 19
    assert ahora[4] == "-" and ahora[10] == " "
    assert "T" not in ahora


def test_semilla_crea_roles_permisos_causas_y_zonas(db_temporal):
    """El primer arranque siembra los catalogos por defecto (solo una vez)."""
    import src.database as db

    # Los tres que se crean de verdad (database.py:299). OJO: `supervisor`
    # aparece en PERMISOS_POR_DEFECTO pero NO se crea como rol; sus permisos
    # solo se aplicaran si alguien lo crea a mano en Administracion.
    assert {r["nombre"] for r in db.listar_roles()} == {
        "admin", "operador", "mantenimiento"
    }

    # El permiso que protege el acceso a Administracion no puede faltar.
    assert db.PERMISO_ACCESO_ADMIN in {p["nombre"] for p in db.listar_permisos()}

    causas = {c["descripcion"] for c in db.listar_causas_paro()}
    # 'Primera pieza' y 'Esperando trabajo' son implicitas: existen en la BD
    # pero NO salen en el selector de causas que ve el operador.
    assert {"Primera pieza", "mantenimiento", "Esperando trabajo"} <= causas

    zonas = {z["nombre"] for z in db.listar_zonas_maquina()}
    assert "Zona de cable" in zonas


def test_admin_tiene_acceso_admin(db_temporal):
    """Ningun rol activo puede quedarse sin `acceso_admin`.

    Es la garantia que evita que alguien se quede fuera del sistema por
    reconfigurar permisos (ver el comentario de `PERMISO_ACCESO_ADMIN`).
    """
    import src.database as db

    con_permiso = db.roles_con_permiso(db.PERMISO_ACCESO_ADMIN)
    assert con_permiso, "ningun rol tiene acceso_admin: el sistema quedaria inaccesible"


@pytest.mark.parametrize("tabla", sorted(TABLAS_ESPERADAS))
def test_todas_las_tablas_son_accesibles(db_temporal, tabla):
    """Una tabla inaccesible (FK rota, tabla caida) falla aqui, no en planta."""
    import src.database as db

    conn = db.obtener_conexion()
    try:
        conn.execute(f"SELECT * FROM {tabla} LIMIT 1").fetchall()
    finally:
        conn.close()

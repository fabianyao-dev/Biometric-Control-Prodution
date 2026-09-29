"""
test_database_ops.py - El comportamiento de negocio de la capa de datos.

`test_database_schema.py` comprueba que las tablas EXISTEN. Este comprueba que
las FUNCIONES hacen lo que el operador espera: que dar de baja un operador no
lo borre, que desactivar un rol le revoke los permisos a todos sus operadores,
que un trabajo QR se pueda retomar sin perder el conteo y que uno cerrado no
se pueda reabrir.

Estos son los casos donde un error NO se ve en pantalla (no revienta con
excepcion: devuelve silenciosamente la lista equivocada) y se descubre dias
despues, cuando nadie encuentra al operador o las piezas no cuadran.

Convenciones de la API (ver `src/database.py`):
- Las funciones que pueden fallar devuelven `(ok, mensaje)` o `(ok, id)`;
  NO lanzan excepcion. Los tests lo comprueban explicitamente.
- `folio` es la clave primaria de `trabajos`.
- Cerrar un trabajo es EXPLICITO (`completar_trabajo`): alcanzar la meta no
  cierra solo, porque el corte lo topa la vista antes de confirmar.
"""

import sqlite3

import pytest

HUELLA = b"plantilla-falsa-para-tests"


def _rol_id(database, nombre):
    conn = database.obtener_conexion()
    try:
        row = conn.execute(
            "SELECT id FROM roles WHERE nombre=? AND activo=1", (nombre,)
        ).fetchone()
    finally:
        conn.close()
    assert row is not None, f"el rol '{nombre}' deberia existir tras init_db()"
    return row["id"]


def _crear_operador(database, nombre, rol="operador"):
    ok, resultado = database.guardar_operador(nombre, HUELLA, _rol_id(database, rol))
    assert ok, f"no se pudo crear el operador {nombre}: {resultado}"
    return resultado


# ---------------------------------------------------------------------------
# Operadores: soft-delete y reactivacion
# ---------------------------------------------------------------------------


def test_crear_operador_exige_una_huella(db):
    """Sin huella no hay operador: la huella ES la credencial."""
    import src.database as database

    ok, mensaje = database.guardar_operador("Sin huella", [])
    assert ok is False
    assert "huella" in mensaje.lower()


def test_crear_operador_rechaza_nombre_vacio(db):
    import src.database as database

    ok, mensaje = database.guardar_operador("   ", HUELLA)
    assert ok is False
    assert "nombre" in mensaje.lower()


def test_no_se_duplican_operadores_activos(db):
    """Dos alta con el mismo nombre: la segunda se rechaza, no se duplica."""
    import src.database as database

    _crear_operador(database, "Juan Perez")
    ok, mensaje = database.guardar_operador("Juan Perez", HUELLA)

    assert ok is False
    assert "Juan Perez" in mensaje

    conn = database.obtener_conexion()
    try:
        n = conn.execute(
            "SELECT COUNT(*) c FROM operadores WHERE nombre='Juan Perez'"
        ).fetchone()["c"]
    finally:
        conn.close()
    assert n == 1


def test_operador_dado_de_baja_se_marca_inactivo_pero_no_se_borra(db):
    """Soft-delete: se marca `activo=0`; la fila y su huella siguen.

    Si se borrara de verdad, las sesiones de produccion historicas quedarian
    huerfanas y el reporte del dia no podria atribuir las piezas a nadie.

    OJO: `listar_operadores_admin()` DEVUELVE tambien los inactivos a proposito
    (la pantalla de Administracion los necesita para reactivarlos); el filtro
    por `activo` lo hace la vista, no esta funcion.
    """
    import src.database as database

    operador_id = _crear_operador(database, "Ana Lopez")
    database.eliminar_operador(operador_id)

    conn = database.obtener_conexion()
    try:
        fila = conn.execute(
            "SELECT activo FROM operadores WHERE id=?", (operador_id,)
        ).fetchone()
        huellas = conn.execute(
            "SELECT COUNT(*) c FROM huellas_operador WHERE operador_id=?",
            (operador_id,),
        ).fetchone()["c"]
    finally:
        conn.close()

    assert fila["activo"] == 0, "debe quedar marcado como inactivo, no borrado"
    assert huellas == 1, "sus huellas deben conservarse para el historial"

    # La vista recibe el `activo` para pintar tachado y ofrecer "reactivar".
    listado = {o["nombre"]: o["activo"] for o in database.listar_operadores_admin()}
    assert listado["Ana Lopez"] == 0


def test_reactivar_operador_conserva_sus_huellas(db):
    """Reinscribir un operador dado de baja lo reactiva SIN duplicar huellas."""
    import src.database as database

    operador_id = _crear_operador(database, "Pedro Ruiz")
    database.eliminar_operador(operador_id)
    ok, _ = database.guardar_operador("Pedro Ruiz", HUELLA, _rol_id(database, "operador"))
    assert ok is True

    conn = database.obtener_conexion()
    try:
        n = conn.execute(
            "SELECT COUNT(*) c FROM huellas_operador WHERE operador_id=?",
            (operador_id,),
        ).fetchone()["c"]
    finally:
        conn.close()
    assert n == 2, "reactivar debe AGREGAR la huella nueva, conservando la vieja"


def test_operador_admite_varias_huellas(db):
    """Un operador puede tener mas de una huella (dos dedos, dos manos)."""
    import src.database as database

    operador_id = _crear_operador(database, "Maria Lopez")
    database.agregar_huella(operador_id, b"segunda-plantilla")

    assert len(database.listar_huellas_operador(operador_id)) == 2


# ---------------------------------------------------------------------------
# Permisos
# ---------------------------------------------------------------------------


def test_operador_normal_no_tiene_acceso_admin(db):
    import src.database as database

    operador_id = _crear_operador(database, "Carlos Ruiz", rol="operador")
    assert database.rol_tiene_permiso_operador(operador_id, database.PERMISO_ACCESO_ADMIN) is False


def test_admin_si_tiene_acceso_admin(db):
    import src.database as database

    operador_id = _crear_operador(database, "Jefa de Planta", rol="admin")
    assert database.rol_tiene_permiso_operador(operador_id, database.PERMISO_ACCESO_ADMIN) is True


def test_mantenimiento_puede_autorizar_paro(db):
    """`mantenimiento` puede autorizar paros: es su unico proposito.

    Sin este permiso, un tecnico no puede autorizar su propio paro y el
    rol se queda inutil.
    """
    import src.database as database

    operador_id = _crear_operador(database, "Tecnico Alberto", rol="mantenimiento")
    assert database.rol_tiene_permiso_operador(operador_id, "autorizar_paro") is True


def test_desactivar_un_rol_revoca_sus_permisos_a_todos(db):
    """El JOIN de `rol_tiene_permiso_operador` exige r.activo=1 a proposito.

    Sin ese filtro, desactivar un rol dejaba a sus operadores con
    `autorizar_paro` y `acceso_admin` retenidos (Diagnostico 7.2.3).
    """
    import src.database as database

    operador_id = _crear_operador(database, "Jefa de Planta", rol="admin")
    assert database.rol_tiene_permiso_operador(operador_id, database.PERMISO_ACCESO_ADMIN)

    rol_id = _rol_id(database, "admin")
    conn = database.obtener_conexion()
    try:
        conn.execute("UPDATE roles SET activo=0 WHERE id=?", (rol_id,))
        conn.commit()
    finally:
        conn.close()

    assert database.rol_tiene_permiso_operador(operador_id, database.PERMISO_ACCESO_ADMIN) is False


def test_agregar_rol_reactiva_un_rol_desactivado(db):
    import src.database as database

    assert database.agregar_rol("ayudante") is True
    rol_id = _rol_id(database, "ayudante")

    conn = database.obtener_conexion()
    try:
        conn.execute("UPDATE roles SET activo=0 WHERE id=?", (rol_id,))
        conn.commit()
    finally:
        conn.close()

    assert database.agregar_rol("ayudante") is True
    _rol_id(database, "ayudante")  # debe volver a estar activo


# ---------------------------------------------------------------------------
# Causas de paro
# ---------------------------------------------------------------------------


def test_causa_paro_dada_de_baja_no_aparece(db):
    """`eliminar_causa_paro` recibe el ID y hace soft-delete."""
    import src.database as database

    assert database.agregar_causa_paro("Falla de husillo") is True
    activas = {c["descripcion"] for c in database.listar_causas_paro()}
    assert "Falla de husillo" in activas

    conn = database.obtener_conexion()
    try:
        causa_id = conn.execute(
            "SELECT id FROM causas_paro WHERE descripcion='Falla de husillo'"
        ).fetchone()["id"]
    finally:
        conn.close()

    database.eliminar_causa_paro(causa_id)

    assert "Falla de husillo" not in {c["descripcion"] for c in database.listar_causas_paro()}
    # Y con `activas_solo=False` sigue estando: es soft-delete.
    inactivas = {c["descripcion"] for c in database.listar_causas_paro(activas_solo=False)}
    assert "Falla de husillo" in inactivas


def test_las_causas_por_defecto_existen(db):
    """Las tres causas que siembra `init_db()` deben existir siempre.

    'Primera pieza' y 'Esperando trabajo' las abre y cierra el sistema solas
    (por eso la vista las oculta del selector, en `selector_causas.py:196`),
    pero si faltan, el modo Primera pieza avisa y se apaga.
    """
    import src.database as database

    descripciones = {c["descripcion"] for c in database.listar_causas_paro()}
    for esperada in database.CAUSAS_PARO_POR_DEFECTO:
        assert esperada in descripciones, f"falta la causa por defecto '{esperada}'"


def test_requiere_zona_se_persiste(db):
    """`requiere_zona` distingue las causas que exigen zona de maquina.

    Es lo que permite que el selector de paros pida la zona cuando la causa la
    necesita (un paro electrico pertenece a una zona, uno de espera no).
    """
    import src.database as database

    database.agregar_causa_paro("Corto en zona electrica", requiere_zona=True)
    database.agregar_causa_paro("Falta de material", requiere_zona=False)

    por_id = {c["descripcion"]: c["requiere_zona"] for c in database.listar_causas_paro()}
    assert por_id["Corto en zona electrica"] == 1
    assert por_id["Falta de material"] == 0


# ---------------------------------------------------------------------------
# Ciclo de vida del trabajo por QR
# ---------------------------------------------------------------------------


def test_abrir_trabajo_crea_en_estado_abierto(db):
    import src.database as database

    operador_id = _crear_operador(database, "Luis Torres")
    sesion_id = database.abrir_sesion(operador_id)

    ok, fila = database.abrir_trabajo(1001, sesion_id, "MH-2045", 50)
    assert ok is True
    assert fila["folio"] == 1001
    assert fila["num_part"] == "MH-2045"
    assert fila["cantidad_total"] == 50
    assert fila["estado"] == database.ESTADO_ABIERTO
    assert fila["fecha_fin"] is None


@pytest.mark.parametrize(
    "folio, num_part, cantidad, esperado",
    [
        (1001, "", 50, "numero de parte"),
        (1001, "   ", 50, "numero de parte"),
        (1001, "PZA", 0, "mayor que cero"),
        (1001, "PZA", -3, "mayor que cero"),
    ],
)
def test_abrir_trabajo_rechaza_entradas_invalidas(db, folio, num_part, cantidad, esperado):
    """La validacion vive en la capa de datos, no solo en el parser del QR.

    El QR y `abrir_trabajo` validan por separado a proposito: el QR se puede
    escanear con otros pretextos, y esta funcion tambien se llama al recuperar
    trabajo tras un apagon.
    """
    import src.database as database

    operador_id = _crear_operador(database, "Luis Torres")
    sesion_id = database.abrir_sesion(operador_id)

    ok, mensaje = database.abrir_trabajo(folio, sesion_id, num_part, cantidad)
    assert ok is False
    assert esperado in mensaje


def test_abrir_trabajo_normaliza_num_part_numerico_a_texto(db):
    """El parser del QR entrega `num_part` como entero; se normaliza a texto.

    Sin `str(num_part)`, un numero de parte numerico reventaba al hacer
    `.strip()` (bug latente ya corregido; este test lo blinda).
    """
    import src.database as database

    operador_id = _crear_operador(database, "Luis Torres")
    sesion_id = database.abrir_sesion(operador_id)

    ok, fila = database.abrir_trabajo(1002, sesion_id, 2045, 50)
    assert ok is True
    assert fila["num_part"] == "2045"


def test_retomar_un_trabajo_no_pierde_el_conteo(db):
    """Re-escanear un folio 'Abierto' lo retoma sin perder los cortes."""
    import src.database as database

    operador_id = _crear_operador(database, "Luis Torres")
    sesion_id = database.abrir_sesion(operador_id)

    database.abrir_trabajo(1003, sesion_id, "PZA-A", 10)
    database.actualizar_detectados(1003, 4)

    ok, fila = database.abrir_trabajo(1003, sesion_id, "PZA-A", 10)
    assert ok is True
    assert fila["cortes_detectados"] == 4, "retomar debe conservar el conteo real"
    assert fila["estado"] == database.ESTADO_ABIERTO


def test_re_escanear_no_duplica_la_fila(db):
    import src.database as database

    operador_id = _crear_operador(database, "Luis Torres")
    sesion_id = database.abrir_sesion(operador_id)

    database.abrir_trabajo(1004, sesion_id, "PZA-B", 10)
    database.abrir_trabajo(1004, sesion_id, "PZA-B", 10)

    conn = database.obtener_conexion()
    try:
        n = conn.execute("SELECT COUNT(*) c FROM trabajos WHERE folio=1004").fetchone()["c"]
    finally:
        conn.close()
    assert n == 1, "re-escanear el mismo folio no debe duplicar el trabajo"


def test_un_trabajo_cerrado_no_se_puede_reabrir(db):
    """Un folio que ya alcanzo su cantidad queda cerrado para siempre."""
    import src.database as database

    operador_id = _crear_operador(database, "Luis Torres")
    sesion_id = database.abrir_sesion(operador_id)

    database.abrir_trabajo(1005, sesion_id, "PZA-C", 3)
    database.completar_trabajo(1005, 3)

    ok, mensaje = database.abrir_trabajo(1005, sesion_id, "PZA-C", 3)
    assert ok is False
    assert "CERRADO" in mensaje


def test_completar_trabajo_cierra_el_trabajo_y_el_segmento(db):
    """`completar_trabajo` cierra el trabajo Y su segmento de la sesion."""
    import src.database as database

    operador_id = _crear_operador(database, "Luis Torres")
    sesion_id = database.abrir_sesion(operador_id)
    database.abrir_trabajo(1006, sesion_id, "PZA-D", 3)
    database.completar_trabajo(1006, 3)

    conn = database.obtener_conexion()
    try:
        trabajo = conn.execute("SELECT * FROM trabajos WHERE folio=1006").fetchone()
        segmentos = conn.execute(
            "SELECT * FROM trabajos_sesiones WHERE folio=1006"
        ).fetchall()
    finally:
        conn.close()

    assert trabajo["estado"] == database.ESTADO_CERRADO
    assert trabajo["fecha_fin"] is not None
    assert trabajo["cortes_confirmados"] == 3
    assert len(segmentos) == 1
    assert segmentos[0]["fecha_fin"] is not None, "el segmento tambien debe cerrarse"
    assert segmentos[0]["estado"] == database.ESTADO_CERRADO


def test_pausar_un_trabajo_no_lo_cierra_y_lo_saca_de_los_vigentes(db):
    """Pausar guarda el parcial: fecha_fin se pone, el estado sigue 'Abierto'.

    Los pausados NO se ofrecen como trabajo vigente (`obtener_trabajo_abierto`
    filtra por `fecha_fin IS NULL`): solo se retoman re-escaneando el folio.
    """
    import src.database as database

    operador_id = _crear_operador(database, "Luis Torres")
    sesion_id = database.abrir_sesion(operador_id)
    database.abrir_trabajo(1007, sesion_id, "PZA-E", 10)
    database.actualizar_detectados(1007, 6)

    database.pausar_trabajo(1007, 6)

    conn = database.obtener_conexion()
    try:
        trabajo = conn.execute("SELECT * FROM trabajos WHERE folio=1007").fetchone()
    finally:
        conn.close()

    assert trabajo["estado"] == database.ESTADO_ABIERTO, "pausar NO cierra el trabajo"
    assert trabajo["fecha_fin"] is not None
    assert trabajo["cortes_detectados"] == 6, "el parcial detectado debe quedar guardado"
    assert database.obtener_trabajo_abierto(sesion_id) is None


def test_reanudar_un_trabajo_pausado_lo_reabre(db):
    """Re-escanear el folio de un pausado lo reactiva."""
    import src.database as database

    operador_id = _crear_operador(database, "Luis Torres")
    sesion_id = database.abrir_sesion(operador_id)
    database.abrir_trabajo(1008, sesion_id, "PZA-F", 10)
    database.actualizar_detectados(1008, 6)
    database.pausar_trabajo(1008, 6)

    ok, fila = database.abrir_trabajo(1008, sesion_id, "PZA-F", 10)
    assert ok is True
    assert fila["fecha_fin"] is None, "retomar debe limpiar fecha_fin"
    assert database.obtener_trabajo_abierto(sesion_id)["folio"] == 1008


def test_folio_es_clave_primaria(db):
    """`trabajos.folio` es PK: dos filas del mismo folio deben chocar."""
    import src.database as database

    operador_id = _crear_operador(database, "Luis Torres")
    sesion_id = database.abrir_sesion(operador_id)
    database.abrir_trabajo(2001, sesion_id, "X", 5)

    conn = database.obtener_conexion()
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO trabajos (folio, num_part, cantidad_total) "
                "VALUES (2001, 'Y', 6)"
            )
    finally:
        conn.close()


def test_trabajos_de_sesion_solo_los_de_esa_sesion(db):
    """Cada sesion ve SUS trabajos: el conteo no se mezcla entre turnos."""
    import src.database as database

    op1 = _crear_operador(database, "Turno Dia")
    op2 = _crear_operador(database, "Turno Noche")
    sesion1 = database.abrir_sesion(op1)
    sesion2 = database.abrir_sesion(op2)

    database.abrir_trabajo(3001, sesion1, "DIA-1", 10)
    database.abrir_trabajo(3002, sesion2, "NOCHE-1", 10)

    folios1 = {t["folio"] for t in database.listar_trabajos_de_sesion(sesion1)}
    folios2 = {t["folio"] for t in database.listar_trabajos_de_sesion(sesion2)}

    assert folios1 == {3001}
    assert folios2 == {3002}


# ---------------------------------------------------------------------------
# Sesiones
# ---------------------------------------------------------------------------


def test_sesion_abierta_y_cerrada(db):
    """Entrada y salida del operador por turno.

    Los timestamps de `sesiones_produccion` son `fecha_inicio` / `fecha_fin`
    (no `fecha_entrada` / `fecha_salida` como en otros sitios).
    """
    import src.database as database

    operador_id = _crear_operador(database, "Luis Torres")
    sesion_id = database.abrir_sesion(operador_id)

    conn = database.obtener_conexion()
    try:
        abierta = conn.execute(
            "SELECT * FROM sesiones_produccion WHERE id=?", (sesion_id,)
        ).fetchone()
    finally:
        conn.close()
    assert abierta["fecha_inicio"] is not None
    assert abierta["fecha_fin"] is None

    database.cerrar_sesion(sesion_id, 12)

    conn = database.obtener_conexion()
    try:
        cerrada = conn.execute(
            "SELECT * FROM sesiones_produccion WHERE id=?", (sesion_id,)
        ).fetchone()
    finally:
        conn.close()
    assert cerrada["fecha_fin"] is not None
    assert cerrada["total_cortes"] == 12

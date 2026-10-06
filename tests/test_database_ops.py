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
# Cierre por APAGON (reinicio tras un corte de luz)
# ---------------------------------------------------------------------------


def test_apagon_confirma_los_detectados_del_trabajo(db):
    """Tras un apagon los detectados se CONFIRMAN, no solo se pausan.

    Es la diferencia con `pausar_trabajo`: las piezas ya se cortaron y no
    habra quien las vuelva a contar, asi que dejarlas solo como detectadas
    hacia que el folio quedara con mas detectados que confirmados.
    """
    import src.database as database

    operador_id = _crear_operador(database, "Raul Hernandez")
    sesion_id = database.abrir_sesion(operador_id)
    database.abrir_trabajo(1009, sesion_id, "PZA-G", 200)
    database.actualizar_detectados(1009, 145)

    ok, estado, confirmados = database.confirmar_trabajo_por_apagon(1009, 145)

    assert ok is True
    assert confirmados == 145
    assert estado == database.ESTADO_ABIERTO, "145 de 200 NO cierra el folio"

    conn = database.obtener_conexion()
    try:
        trabajo = conn.execute(
            "SELECT * FROM trabajos WHERE folio=1009"
        ).fetchone()
        segmento = conn.execute(
            "SELECT * FROM trabajos_sesiones WHERE folio=1009"
        ).fetchone()
    finally:
        conn.close()

    assert trabajo["cortes_confirmados"] == 145
    assert trabajo["cortes_detectados"] == 145
    assert trabajo["fecha_fin"] is not None
    assert trabajo["estado"] == database.ESTADO_ABIERTO
    # El segmento de la sesion tambnien se cierra, y ya no queda descuadrado.
    assert segmento["fecha_fin"] is not None
    assert segmento["cantidad"] == 145
    assert segmento["confirmados"] == 145


def test_apagon_cierra_el_trabajo_si_ya_alcanzo_la_meta(db):
    """Si los detectados llegan a la meta, el folio queda 'Cerrado'."""
    import src.database as database

    operador_id = _crear_operador(database, "Raul Hernandez")
    sesion_id = database.abrir_sesion(operador_id)
    database.abrir_trabajo(1010, sesion_id, "PZA-H", 150)
    database.actualizar_detectados(1010, 150)

    ok, estado, confirmados = database.confirmar_trabajo_por_apagon(1010, 150)

    assert (ok, estado, confirmados) == (True, database.ESTADO_CERRADO, 150)

    conn = database.obtener_conexion()
    try:
        trabajo = conn.execute(
            "SELECT * FROM trabajos WHERE folio=1010"
        ).fetchone()
        segmento = conn.execute(
            "SELECT * FROM trabajos_sesiones WHERE folio=1010"
        ).fetchone()
    finally:
        conn.close()

    assert trabajo["estado"] == database.ESTADO_CERRADO
    assert trabajo["cortes_confirmados"] == 150
    assert segmento["estado"] == database.ESTADO_CERRADO
    # Un folio Cerrado ya NO se puede reabrir escaneando su QR.
    ok_reabrir, _ = database.abrir_trabajo(1010, sesion_id, "PZA-H", 150)
    assert ok_reabrir is False


def test_apagon_no_rebaja_los_confirmados_previos(db):
    """`confirmar_trabajo_por_apagon` nunca deja confirmados < detectados.

    Si el checkpoint llegara atras (contador reiniciado, BD restaurada), la
    funcion se queda con el maximo: perder un confirmado ya validado seria
    peor que dejar detectados > confirmados.
    """
    import src.database as database

    operador_id = _crear_operador(database, "Raul Hernandez")
    sesion_id = database.abrir_sesion(operador_id)
    database.abrir_trabajo(1011, sesion_id, "PZA-I", 200)
    database.actualizar_detectados(1011, 180)
    database.cerrar_trabajo_modalidad(1011, 180, 200, modalidad="parcial",
                                     detectados=180)
    database.abrir_trabajo(1011, sesion_id, "PZA-I", 200)
    # El checkpoint de esta sesion quedo atras (no deberia pasar, pero el
    # guardado nunca debe perder lo ya confirmado).
    database.actualizar_detectados(1011, 150)

    ok, _estado, confirmados = database.confirmar_trabajo_por_apagon(1011, 150)

    assert ok is True
    assert confirmados == 180, "los confirmados previos no se deben rebajar"


def test_apagon_repara_los_segmentos_pausados_sin_confirmar(db):
    """Los segmentos previos del folio que pausaron sin confirmar se igualan.

    Si no, el folio queda con `cortes_confirmados` = 145 pero los segmentos
    (que es lo que suma el reporte) seguirian reportando 0.
    """
    import src.database as database

    operador_id = _crear_operador(database, "Raul Hernandez")
    sesion1 = database.abrir_sesion(operador_id)
    database.abrir_trabajo(1012, sesion1, "PZA-J", 300)
    database.actualizar_detectados(1012, 100)
    database.pausar_trabajo(1012, 100)

    sesion2 = database.abrir_sesion(operador_id)
    database.abrir_trabajo(1012, sesion2, "PZA-J", 300)
    database.actualizar_detectados(1012, 145)
    database.confirmar_trabajo_por_apagon(1012, 145)

    segmentos = database.listar_trabajos_de_sesion(sesion1) + \
        database.listar_trabajos_de_sesion(sesion2)
    suma_confirmados = sum(s["confirmados"] or 0 for s in segmentos)
    conn = database.obtener_conexion()
    try:
        trabajo = conn.execute(
            "SELECT cortes_confirmados FROM trabajos WHERE folio=1012"
        ).fetchone()
    finally:
        conn.close()

    assert suma_confirmados == trabajo["cortes_confirmados"] == 145


def test_apagon_con_paro_en_curso_lo_cierra_con_causa(db):
    """El reinicio debe poder cerrar el paro abierto con la causa implicita.

    `causa_id` es nullable, asi que el fallo (causa None) NO revienta: el
    reporte sale con "(sin causa registrada)". Por eso el test mira el id.
    """
    import src.database as database

    operador_id = _crear_operador(database, "Raul Hernandez")
    sesion_id = database.abrir_sesion(operador_id)
    paro_id = database.iniciar_paro(sesion_id, None)

    causa_id = None
    for causa in database.listar_causas_paro(activas_solo=True):
        if str(causa["descripcion"]).strip().lower() == "computadora apagada":
            causa_id = causa["id"]
    assert causa_id is not None, "la causa implicita del corte de luz debe existir"

    database.finalizar_paro(paro_id, causa_id, operador_id)

    conn = database.obtener_conexion()
    try:
        paro = conn.execute(
            "SELECT * FROM paros_produccion WHERE id=?", (paro_id,)
        ).fetchone()
    finally:
        conn.close()

    assert paro["causa_id"] == causa_id, "el paro no debe quedar sin causa"
    assert paro["fin_paro"] is not None


def test_apagon_con_trabajo_lega_el_folio_al_paro_reconstruido(db):
    """Regresion: el paro del corte de luz debe conservar el folio.

    Reproduce el ORDEN real de `_cerrar_sesion_interrumpida`: primero
    `confirmar_trabajo_por_apagon` (que le pone `fecha_fin` al trabajo) y
    DESPUES se reconstruye el paro. Si el folio se vuelve a pedir con
    `obtener_trabajo_abierto` en ese segundo paso, la consulta exige
    `fecha_fin IS NULL`, no encuentra el trabajo ya cerrado y el paro sale
    'sin trabajo' aunque la maquina cortara con el folio cargado.
    """
    import src.database as database

    operador_id = _crear_operador(database, "Raul Hernandez")
    sesion_id = database.abrir_sesion(operador_id)
    database.abrir_trabajo(1040, sesion_id, "PZA-APLIE", 50)
    database.registrar_ultimo_corte(sesion_id, "2026-09-29 10:47:52")

    # Paso 1 de la recuperacion: el trabajo se confirma y queda CERRADO.
    trabajo = database.obtener_trabajo_abierto(sesion_id)
    assert trabajo is not None
    folio_en_curso = trabajo["folio"]
    database.confirmar_trabajo_por_apagon(
        folio_en_curso, trabajo["cortes_detectados"] or 0
    )
    assert database.obtener_trabajo_abierto(sesion_id) is None, (
        "tras confirmar, el trabajo ya no debe verse como abierto"
    )

    # Paso 2: el paro se reconstruye con el folio capturado ANTES del cierre.
    database.crear_paro_por_apagon(
        sesion_id, folio_en_curso, "2026-09-29 10:47:52", operador_id,
        _causa_id_de(database, "computadora apagada"),
        fin="2026-09-29 10:49:11",
    )

    paros = database.obtener_paros_de_sesion(sesion_id)
    assert len(paros) == 1
    assert paros[0]["folio"] == 1040, (
        "el paro del corte de luz perdio el folio del trabajo en curso"
    )


# ---------------------------------------------------------------------------
# El corte de luz NO es un paro de produccion (reportes)
# ---------------------------------------------------------------------------


def _causa_id_de(database, descripcion):
    for causa in database.listar_causas_paro(activas_solo=True):
        if str(causa["descripcion"]).strip().lower() == descripcion:
            return causa["id"]
    raise AssertionError(f"falta la causa '{descripcion}'")


def test_corte_de_luz_no_cuenta_como_paro_de_produccion(db):
    """`listar_sesiones_por_fecha` no debe sumar el corte de luz a `num_paros`.

    Es una omision del operador al apagar sin cerrar sesion, no una falla de
    la maquina: contarla penaliza la disponibilidad del turno. El paro de luz
    SI se registra (esta en la hoja Paros), solo queda fuera del agregado.
    """
    import src.database as database

    operador_id = _crear_operador(database, "Raul Hernandez")
    sesion_id = database.abrir_sesion(operador_id)

    # Un paro real de maquina y el corte de luz de la sesion.
    database.finalizar_paro(database.iniciar_paro(sesion_id, None),
                            _causa_id_de(database, "mantenimiento"), operador_id)
    database.finalizar_paro(database.iniciar_paro(sesion_id, None),
                            _causa_id_de(database, "computadora apagada"),
                            operador_id)
    database.cerrar_sesion(sesion_id, 10)

    # La sesion arranca hoy (ZONA de la planta), asi que se consulta el dia
    # local de `ahora_local()`.
    sesiones = database.listar_sesiones_por_fecha(database.ahora_local()[:10])
    assert len(sesiones) == 1
    assert sesiones[0]["num_paros"] == 1, (
        "solo el paro de maquina debe contar; el corte de luz se excluye"
    )


def test_espera_tampoco_cuenta_y_el_sin_causa_si(db):
    """Los tres casos del filtro `CAUSAS_NO_PRODUCTIVAS` en una sola sesion.

    - espera y corte de luz: NO cuentan (no son paros de la maquina);
    - paro sin causa: SI cuenta. No sabemos que fue y esconderlo seria peor
      que medirlo de mas.
    """
    import src.database as database

    operador_id = _crear_operador(database, "Raul Hernandez")
    sesion_id = database.abrir_sesion(operador_id)

    database.finalizar_paro(database.iniciar_paro(sesion_id, None),
                            _causa_id_de(database, "esperando trabajo"),
                            operador_id)
    database.finalizar_paro(database.iniciar_paro(sesion_id, None),
                            _causa_id_de(database, "computadora apagada"),
                            operador_id)
    # Sin causa: `iniciar_paro` la deja NULL y `finalizar_paro` la respeta.
    database.finalizar_paro(database.iniciar_paro(sesion_id, None), None,
                            operador_id)
    database.cerrar_sesion(sesion_id, 10)

    sesiones = database.listar_sesiones_por_fecha(database.ahora_local()[:10])
    assert sesiones[0]["num_paros"] == 1, (
        "solo el paro sin causa cuenta: los otros dos no son paros utiles"
    )


def test_el_corte_de_luz_aparece_en_el_detalle_del_reporte(db):
    """Excluido del agregado, NO del detalle: el corte queda en la hoja Paros.

    Es lo que pedio el operador: 'que si aparezca pero que no se sume'. El
    reporte lista el paro con su duracion; solo lo saca de Nº/Min y
    disponibilidad.
    """
    import src.database as database

    operador_id = _crear_operador(database, "Raul Hernandez")
    sesion_id = database.abrir_sesion(operador_id)
    database.finalizar_paro(database.iniciar_paro(sesion_id, None),
                            _causa_id_de(database, "computadora apagada"),
                            operador_id)
    database.cerrar_sesion(sesion_id, 10)

    paros = database.obtener_paros_de_sesion(sesion_id)
    assert len(paros) == 1
    assert paros[0]["descripcion"] == "Computadora apagada", (
        "el corte de luz debe seguir visible en el detalle de la sesion"
    )


def test_el_paro_posterior_al_cierre_no_hereda_el_folio(db):
    """Cerrar el trabajo y despues abrir un paro: el paro va SIN folio.

    Regresion de la incidencia reportada: al cerrar el trabajo y apagar la
    maquina, el paro de "Computadora apagada" aparecia con el folio del
    trabajo recien cerrado. Los dos eventos caen en el MISMO segundo, asi que
    el backfill por solape los confundia.

    El caso real: el segmento del folio 28 termino 10:12:40 y el paro empezo
    10:12:40. Con `>=` el backfill loNhilo ahi y le colgo el folio.
    """
    import src.database as database

    operador_id = _crear_operador(database, "Raul Hernandez")
    sesion_id = database.abrir_sesion(operador_id)
    database.abrir_trabajo(1020, sesion_id, "PZA-Z", 100)

    # Se cierra el trabajo y, en el mismo segundo, arranca el paro.
    database.cerrar_trabajo_modalidad(1020, 5, 100, modalidad="parcial",
                                      detectados=5)
    paro_id = database.iniciar_paro(sesion_id, None)
    database.finalizar_paro(paro_id,
                            _causa_id_de(database, "computadora apagada"),
                            operador_id)

    paros = database.obtener_paros_de_sesion(sesion_id)
    assert len(paros) == 1
    assert paros[0]["folio"] is None, (
        "el paro abrio DESPUES de cerrar el trabajo: no debe heredar su folio"
    )
    assert paros[0]["descripcion"] == "Computadora apagada"


def test_el_paro_que_parte_dentro_del_trabajo_si_lleva_folio(db):
    """Contraste del anterior: el solape REAL si debe vincular el folio.

    Si el paro arranca con el trabajo aun abierto, el backfill tiene que
    colgarlo. Sin este test, un arreglo que apague el backfill entero
    pasaria el de arriba y dejaria paros huerfanos.
    """
    import src.database as database

    operador_id = _crear_operador(database, "Raul Hernandez")
    sesion_id = database.abrir_sesion(operador_id)
    database.abrir_trabajo(1021, sesion_id, "PZA-Y", 100)

    # El paro arranca con el folio 1021 aun cargado, pero se registra sin
    # folio (como cuando el folio se carga a mitad de un paro ya abierto).
    paro_id = database.iniciar_paro(sesion_id, None)
    database.finalizar_paro(paro_id, _causa_id_de(database, "mantenimiento"),
                            operador_id)

    paros = database.obtener_paros_de_sesion(sesion_id)
    assert paros[0]["folio"] == 1021, (
        "el paro solapa el segmento abierto: debe quedar vinculado"
    )


# ---------------------------------------------------------------------------
# Apagon con la maquina EN MARCHA: el paro se reconstruye (backfill)
# ---------------------------------------------------------------------------


def test_registrar_ultimo_corte_persiste_el_ancla(db):
    """El HAL lo lleva en memoria; sin persistirlo se pierde con la luz."""
    import src.database as database

    operador_id = _crear_operador(database, "Raul Hernandez")
    sesion_id = database.abrir_sesion(operador_id)
    database.registrar_ultimo_corte(sesion_id, "2026-09-29 10:05:00")

    sesion = database.obtener_sesion_interrumpida()
    assert sesion is not None
    assert sesion["id"] == sesion_id
    assert sesion["ultimo_corte"] == "2026-09-29 10:05:00"


def test_crear_paro_por_apagon_cubre_el_intervalo_del_hueco(db):
    """El paro reconstruido va del ultimo corte al reinicio, no desde el
    reinicio (que daria cero y dejaria el hueco sin medir)."""
    import src.database as database

    operador_id = _crear_operador(database, "Raul Hernandez")
    sesion_id = database.abrir_sesion(operador_id)
    database.abrir_trabajo(1030, sesion_id, "PZA-AP", 50)

    paro_id = database.crear_paro_por_apagon(
        sesion_id, 1030, "2026-09-29 10:05:00", operador_id,
        _causa_id_de(database, "computadora apagada"),
        fin="2026-09-29 10:12:40",
    )

    paro = database.obtener_paros_de_sesion(sesion_id)[0]
    assert paro["id"] == paro_id
    assert paro["inicio_paro"] == "2026-09-29 10:05:00"
    assert paro["fin_paro"] == "2026-09-29 10:12:40"
    assert paro["descripcion"] == "Computadora apagada"
    assert paro["folio"] == 1030, "debe quedar ligado al trabajo en curso"


def test_crear_paro_por_apagon_no_inventa_un_intervalo_negativo(db):
    """Un ancla posterior al reinicio (reloj desfasado) no genera negativo.

    Se degrada a un paro de un instante. Un `inicio > fin` sucioaria el
    reporte con duraciones negativas.
    """
    import src.database as database

    operador_id = _crear_operador(database, "Raul Hernandez")
    sesion_id = database.abrir_sesion(operador_id)

    database.crear_paro_por_apagon(
        sesion_id, None, "2026-09-29 23:59:00", operador_id,
        _causa_id_de(database, "computadora apagada"),
        fin="2026-09-29 10:12:40",
    )

    paro = database.obtener_paros_de_sesion(sesion_id)[0]
    assert paro["inicio_paro"] == paro["fin_paro"] == "2026-09-29 10:12:40"


def test_crear_paro_por_apagon_sin_ancla_no_usa_el_inicio_de_sesion(db):
    """Sin `ultimo_corte` el paro dura cero; no se mide desde el login.

    Medir desde el inicio de la sesion inventaria horas de paro que el
    operador no hizo y contaminaria la disponibilidad del turno.
    """
    import src.database as database

    operador_id = _crear_operador(database, "Raul Hernandez")
    sesion_id = database.abrir_sesion(operador_id)

    database.crear_paro_por_apagon(
        sesion_id, None, None, operador_id,
        _causa_id_de(database, "computadora apagada"),
        fin="2026-09-29 10:12:40",
    )

    paro = database.obtener_paros_de_sesion(sesion_id)[0]
    assert paro["inicio_paro"] == "2026-09-29 10:12:40"


def test_el_paro_apagon_no_cuenta_como_paro_de_produccion(db):
    """Reconstruir el paro no lo reintroduce en los agregados de maquina.

    El corte de luz es una omision del operador, no una falla: aparece en la
    hoja Paros pero fuera de Nº paros, Min paro y disponibilidad.
    """
    import src.database as database

    operador_id = _crear_operador(database, "Raul Hernandez")
    sesion_id = database.abrir_sesion(operador_id)
    database.crear_paro_por_apagon(
        sesion_id, None, "2026-09-29 10:05:00", operador_id,
        _causa_id_de(database, "computadora apagada"),
        fin="2026-09-29 10:12:40",
    )
    database.cerrar_sesion(sesion_id, 10)

    sesiones = database.listar_sesiones_por_fecha(database.ahora_local()[:10])
    assert sesiones[0]["num_paros"] == 0, (
        "el corte de luz no es un paro de produccion"
    )
    # Pero sigue visible en el detalle.
    paros = database.obtener_paros_de_sesion(sesion_id)
    assert len(paros) == 1
    assert paros[0]["descripcion"] == "Computadora apagada"


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

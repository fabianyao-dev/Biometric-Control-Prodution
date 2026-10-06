"""
test_reporte_dia.py - El corte de luz NO es un paro de produccion.

Contexto: el reinicio tras un apagón cierra el paro abierto con la causa
implicita "Computadora apagada". Como ese corte ocurre con la sesion abierta,
automaticamente cae en el reporte. El operador no lo.proto: es una omision
suya al apagar, no una falla de la maquina, asi que no debe restarle
disponibilidad al turno.

El requisito fue explicitamente "que si aparezca pero que no se sume con los
paros de produccion", y son dos cosas distintas que hay que probar por
separado:

  - APARECE: la fila del corte esta en la hoja Paros, con su duracion.
  - NO SUMA: no entra en Nº paros, Min paro, Disponibilidad, la columna Paros
    de Sesiones, los cruces ni las columnas de paros por segmento.
"""

import pytest

from src.reportes.export_dia import (
    CAUSAS_NO_PRODUCTIVAS,
    _cuenta_como_paro,
    exportar_dia,
)

# ---------------------------------------------------------------------------
# El criterio, aislado
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("causa", ["Computadora apagada", "computadora apagada",
                                   "  COMPUTADORA APAGADA "])
def test_el_corte_de_luz_no_cuenta(causa):
    """El criterio es insensible a mayusculas y espacios.

    La causa la escribe el usuario en el selector y la guarda el modulo; si el
    filtro fuera case-sensitive dejaria pasar el corte de luz.
    """
    assert not _cuenta_como_paro(causa)


def test_la_espera_no_cuenta():
    """La espera de trabajo tampoco: tiempo ocioso, no paro de maquina."""
    assert not _cuenta_como_paro("Esperando trabajo")


@pytest.mark.parametrize("causa", ["Mantenimiento", "Falta de material",
                                   "Molde atorado", ""])
def test_un_paro_normal_si_cuenta(causa):
    """Un paro real de maquina SI cuenta, incluso sin causa.

    Sin causa no sabemos que fue y esconderlo seria peor que medirlo de mas.
    """
    assert _cuenta_como_paro(causa)


def test_ambas_causas_no_productivas_estan_cubiertas():
    """Guardia: las dos excepciones del modulo son las que se documentan."""
    assert set(CAUSAS_NO_PRODUCTIVAS) == {
        "esperando trabajo", "computadora apagada"}


# ---------------------------------------------------------------------------
# El workbook, end-to-end
# ---------------------------------------------------------------------------


def _causa_id_de(database, descripcion):
    for causa in database.listar_causas_paro(activas_solo=True):
        if str(causa["descripcion"]).strip().lower() == descripcion:
            return causa["id"]
    raise AssertionError(f"falta la causa '{descripcion}'")


def _crear_operador(database, nombre="Raul Hernandez"):
    from tests.test_database_ops import HUELLA, _rol_id

    ok, resultado = database.guardar_operador(
        nombre, HUELLA, _rol_id(database, "operador"))
    assert ok, f"no se pudo crear el operador {nombre}: {resultado}"
    return resultado


def _filas(ws, encabezados):
    """Devuelve las filas de datos de `ws` como dicts {encabezado: valor}."""
    filas = list(ws.iter_rows(values_only=True))
    cabeceras = list(filas[0])
    return [dict(zip(cabeceras, f)) for f in filas[1:] if any(
        v is not None for v in f)]


def test_el_corte_de_luz_aparece_pero_no_suma(db, tmp_path):
    """El contrato completo del reporte ante un corte de luz.

    Sesion con tres paros: uno de maquina (debe sumar), la espera y el corte
    de luz (deben listarse pero no sumar). Se comprueba hoja por hoja.
    """
    import src.database as database

    operador_id = _crear_operador(database)
    sesion_id = database.abrir_sesion(operador_id)

    database.finalizar_paro(
        database.iniciar_paro(sesion_id, None),
        _causa_id_de(database, "mantenimiento"), operador_id)
    database.finalizar_paro(
        database.iniciar_paro(sesion_id, None),
        _causa_id_de(database, "esperando trabajo"), operador_id)
    database.finalizar_paro(
        database.iniciar_paro(sesion_id, None),
        _causa_id_de(database, "computadora apagada"), operador_id)
    database.cerrar_sesion(sesion_id, 10)

    ruta = str(tmp_path / "dia.xlsx")
    ok, msg, stats = exportar_dia(database.ahora_local()[:10], ruta)
    assert ok, f"el export fallo: {msg}"

    from openpyxl import load_workbook

    wb = load_workbook(ruta)
    try:
        # --- APARECE: la hoja Paros lista los tres, con su duracion.
        paros = _filas(wb["Paros"], None)
        causas = [f["Causa"] for f in paros]
        assert "Computadora apagada" in causas, (
            "el corte de luz debe quedar en el detalle de Paros")
        assert "Esperando trabajo" in causas
        assert len(paros) == 3, "los tres paros deben listarse"

        # --- NO SUMA: solo el paro de maquina cuenta.
        assert stats["paros"] == 3, (
            "las stats informan el detalle, no el agregado")

        # Sesiones: la columna Paros es el conteo de paros PRODUCTIVOS.
        sesiones = _filas(wb["Sesiones"], None)
        assert len(sesiones) == 1
        assert sesiones[0]["Paros"] == 1, (
            "la columna Paros de Sesiones no debe contar el corte de luz")

        # Cruces: ninguna causa no productiva puede aparecer.
        ws_cru = wb["Cruces"]
        celdas = [c.value for fila_ in ws_cru.iter_rows() for c in fila_]
        assert "Computadora apagada" not in celdas, (
            "el corte de luz no debe aparecer en los cruces")
        assert "Esperando trabajo" not in celdas, (
            "la espera tampoco debe aparecer en los cruces")
        # Y el paro de maquina si, con su operador y su zona en el cruce.
        assert "mantenimiento" in celdas
        assert "Raul Hernandez" in celdas

        # Resumen: las formulas deben excluir AMBAS causas.
        ws_res = wb["Resumen"]
        formulas = {
            ws_res.cell(row=r, column=1).value: ws_res.cell(row=r, column=2).value
            for r in range(2, 20)
        }
        for etiqueta in ("Min paro", "Nº paros"):
            f = formulas[etiqueta]
            assert "Esperando trabajo" in f and "Computadora apagada" in f, (
                f"la formula de '{etiqueta}' debe excluir las dos causas: {f}")
    finally:
        wb.close()


def test_el_corte_de_luz_se_informa_aparte_en_el_resumen(db, tmp_path):
    """Lo que se excluye del agregado se reporta en KPIs propios.

    Si solo se sacara del total, el corte de luz desapareceria del reporte y
    el operador perderia la visibilidad que pidio.
    """
    import src.database as database

    operador_id = _crear_operador(database)
    sesion_id = database.abrir_sesion(operador_id)
    database.finalizar_paro(
        database.iniciar_paro(sesion_id, None),
        _causa_id_de(database, "computadora apagada"), operador_id)
    database.cerrar_sesion(sesion_id, 10)

    ruta = str(tmp_path / "dia.xlsx")
    ok, msg, _ = exportar_dia(database.ahora_local()[:10], ruta)
    assert ok, f"el export fallo: {msg}"

    from openpyxl import load_workbook

    wb = load_workbook(ruta)
    try:
        ws_res = wb["Resumen"]
        celdas = {
            ws_res.cell(row=r, column=1).value: ws_res.cell(row=r, column=2).value
            for r in range(2, 20)
        }
        assert "Nº cortes de luz" in celdas, (
            "debe existir un KPI propio para el corte de luz")
        assert "Computadora apagada" in celdas["Nº cortes de luz"]
    finally:
        wb.close()


def test_el_corte_de_luz_no_cuenta_en_los_paros_del_segmento(db, tmp_path):
    """Con trabajo cargado: el corte tampoco infla los paros del segmento.

    Este es el caso real de la incidencia: el apagón ocurrió con el folio
    abierto, asi que el paro lleva folio y cae dentro de la ventana del
    segmento. Si no se filtra aqui, el renglón del trabajo muestra un paro que
    no fue de la maquina.
    """
    import src.database as database

    operador_id = _crear_operador(database)
    sesion_id = database.abrir_sesion(operador_id)
    database.abrir_trabajo(1011, sesion_id, "FOLIO-9", 100)

    database.iniciar_paro(sesion_id, 1011)
    database.finalizar_paro(
        database.obtener_paros_de_sesion(sesion_id)[0]["id"],
        _causa_id_de(database, "computadora apagada"), operador_id)
    database.cerrar_trabajo_modalidad(1011, 0, 100, modalidad="parcial",
                                     detectados=0)
    database.cerrar_sesion(sesion_id, 10)

    ruta = str(tmp_path / "dia.xlsx")
    ok, msg, _ = exportar_dia(database.ahora_local()[:10], ruta)
    assert ok, f"el export fallo: {msg}"

    from openpyxl import load_workbook

    wb = load_workbook(ruta)
    try:
        trabajos = _filas(wb["Trabajos"], None)
        assert len(trabajos) == 1
        assert trabajos[0]["Nº paros"] == 0, (
            "el corte de luz no debe contar como paro del segmento")
        assert trabajos[0]["Min paro"] == 0.0

        # Sigue visible en el detalle.
        paros = _filas(wb["Paros"], None)
        assert any(f["Causa"] == "Computadora apagada" for f in paros)
        assert paros[0]["Folio"] == 1011, (
            "el corte conserva el folio con el que ocurrio")
        assert paros[0]["Parte"] == "FOLIO-9"
    finally:
        wb.close()


def test_un_paro_de_maquina_en_el_mismo_lugar_si_cuenta(db, tmp_path):
    """El filtro no se comio los paros reales del mismo segmento.

    Contraste directo del test anterior: mismo segmento, misma causa de
    maquina, y el conteo sube. Si este falla, el filtro esta demasiado
    agresivo.
    """
    import src.database as database

    operador_id = _crear_operador(database)
    sesion_id = database.abrir_sesion(operador_id)
    database.abrir_trabajo(1012, sesion_id, "FOLIO-9", 100)

    database.iniciar_paro(sesion_id, 1012)
    database.finalizar_paro(
        database.obtener_paros_de_sesion(sesion_id)[0]["id"],
        _causa_id_de(database, "mantenimiento"), operador_id)
    database.cerrar_trabajo_modalidad(1012, 0, 100, modalidad="parcial",
                                     detectados=0)
    database.cerrar_sesion(sesion_id, 10)

    ruta = str(tmp_path / "dia.xlsx")
    ok, msg, _ = exportar_dia(database.ahora_local()[:10], ruta)
    assert ok, f"el export fallo: {msg}"

    from openpyxl import load_workbook

    wb = load_workbook(ruta)
    try:
        trabajos = _filas(wb["Trabajos"], None)
        assert trabajos[0]["Nº paros"] == 1, (
            "un paro de maquina dentro del segmento debe contar")
    finally:
        wb.close()

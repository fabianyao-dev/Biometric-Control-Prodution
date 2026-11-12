"""
export_dia.py - Export del dia a Excel (openpyxl).

Genera un workbook con 6 hojas a partir de las sesiones de una fecha
('YYYY-MM-DD', segun `date(fecha_inicio)`):

    Resumen    KPIs del dia con formulas + top 5 causas (estatico).
    Sesiones   Tabla `TblSesiones` (1 fila por sesion).
    Paros      Tabla `TblParos` (1 fila por paro, con folio/parte; los paros
               sin trabajo van como "sin trabajo").
    Trabajos   Tabla `TblTrabajos` (1 fila por segmento folio x sesion,
               enriquecida con los paros de su sesion).
    Cruces     Tablas pre-calculadas (por operador/causa/zona/folio y matriz
               operador x causa) + grafico de barras.
    LEEME      Guia de 2 clics para armar tablas dinamicas desde las tablas.

Las hojas de datos son Tablas oficiales de Excel (autofilter + estilo), listas
para Insertar -> Tabla dinamica. Las formulas del Resumen usan rangos de
columna completos (`Sesiones!E2:E1048576`) para que sigan funcionando aunque
el usuario agregue filas o alguna tabla quede vacia.
"""

import logging
from collections import defaultdict
from datetime import datetime

log = logging.getLogger(__name__)

FORMATO_TS = "%Y-%m-%d %H:%M:%S"
SIN_TRABAJO = "—sin trabajo—"

# Causas que NO son paros de produccion: se listan en la hoja Paros pero NO
# suman a Nº paros, Min paro, Disponibilidad ni a los cruces.
#   - "Esperando trabajo": tiempo ocioso entre trabajos (no lleva folio).
#   - "Computadora apagada": corte de luz que el reinicio cierra. Es una
#     omision del operador al apagar sin cerrar sesion, no una falla de la
#     maquina, asi que no debe restarle disponibilidad al turno.
# En minusculas sin espacios: es como las compara la BD.
CAUSAS_NO_PRODUCTIVAS = ("esperando trabajo", "computadora apagada")


def _cuenta_como_paro(causa) -> bool:
    """True si el paro debe sumarse a los agregados de produccion.

    Inverso de `CAUSAS_NO_PRODUCTIVAS`: la espera de trabajo y el corte de luz
    se muestran en la hoja Paros (quedan registrados) pero quedan fuera de
    Nº/min derivados (segmento, Resumen, Cruces). Un paro sin causa SI cuenta:
    no sabemos que fue y esconderlo seria peor que medirlo de mas.
    """
    return str(causa or "").strip().lower() not in CAUSAS_NO_PRODUCTIVAS


MODALIDAD_NOMBRE = {
    "normal": "Normal",
    "parcial": "Parcial",
    "folio": "Folio modificado",
}

AZUL_CABECERA = "1F4E78"


def _parse_ts(valor):
    if not valor:
        return None
    try:
        return datetime.strptime(str(valor), FORMATO_TS)
    except (ValueError, TypeError):
        return None


def _min_entre(inicio, fin):
    """Minutos entre dos timestamps (1 decimal) o None si falta alguno."""
    dt_ini = _parse_ts(inicio)
    dt_fin = _parse_ts(fin)
    if dt_ini is None or dt_fin is None:
        return None
    return round((dt_fin - dt_ini).total_seconds() / 60.0, 1)


def _tabla(ws, ref, nombre, filas):
    """Convierte un rango con encabezado en Tabla oficial de Excel.

    `filas` es el numero de filas de datos del rango. Una tabla de Excel con
    SOLO el encabezado (sin filas de datos) es invalida: Excel se niega a abrir
    el archivo (lo reporta como "contenido problematico" y lo repara quitando
    la tabla). Por eso, si `filas` es 0 no se crea la tabla; la hoja queda con
    su encabezado y sin autofiltro, que es lo unico valido.
    """
    if filas == 0:
        return
    from openpyxl.worksheet.table import Table, TableStyleInfo

    tab = Table(displayName=nombre, ref=ref)
    tab.tableStyleInfo = TableStyleInfo(
        name="TableStyleMedium9", showRowStripes=True, showColumnStripes=False
    )
    ws.add_table(tab)


def _formato_base(wb, ws, encabezados, anchos):
    """Estilo de cabecera, freeze, anchos y formatos numericos basicos."""
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

    fill = PatternFill("solid", fgColor=AZUL_CABECERA)
    font = Font(bold=True, color="FFFFFF", size=11)
    thin = Side(style="thin", color="B0B0B0")
    borde = Border(left=thin, right=thin, top=thin, bottom=thin)
    for col, texto in enumerate(encabezados, start=1):
        celda = ws.cell(row=1, column=col, value=texto)
        celda.fill = fill
        celda.font = font
        celda.alignment = Alignment(horizontal="center", vertical="center")
        celda.border = borde
    ws.freeze_panes = "A2"
    for col, ancho in enumerate(anchos, start=1):
        ws.column_dimensions[ws.cell(row=1, column=col).column_letter].width = ancho
    ws.sheet_properties.pageSetUpPr.fitToPage = True


def exportar_dia(fecha: str, ruta_destino: str):
    """Exporta todas las sesiones de `fecha` a un .xlsx en `ruta_destino`.

    Devuelve (ok, mensaje, stats). Si el dia no tiene sesiones devuelve
    (False, aviso, {}) para que la UI muestre advertencia sin generar archivo.
    """
    from openpyxl import Workbook
    from openpyxl.chart import BarChart, Reference
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    try:
        datetime.strptime(fecha, "%Y-%m-%d")
    except (ValueError, TypeError):
        return False, f"Fecha invalida: {fecha!r} (usa YYYY-MM-DD).", {}

    from src.database import (
        listar_sesiones_por_fecha,
        listar_trabajos_de_sesion,
        obtener_paros_de_sesion,
        paros_de_segmento,
    )

    sesiones = listar_sesiones_por_fecha(fecha)
    if not sesiones:
        return False, f"No hay sesiones el {fecha}.", {}

    if not str(ruta_destino).lower().endswith(".xlsx"):
        ruta_destino = str(ruta_destino) + ".xlsx"

    # ---- Recolectar filas cruzadas ----
    filas_sesion, filas_paro, filas_trabajo = [], [], []
    por_operador = defaultdict(lambda: {"cortes": 0, "min_paro": 0.0, "paros": 0})
    por_causa = defaultdict(lambda: {"paros": 0, "min": 0.0})
    por_zona = defaultdict(lambda: {"paros": 0, "min": 0.0})
    por_folio = {}
    paros_por_folio = {}
    matriz_op_causa = defaultdict(lambda: defaultdict(float))

    for s in sesiones:
        sid = s["id"]
        operador = s["nombre"]
        paros = obtener_paros_de_sesion(sid)
        trabajos = listar_trabajos_de_sesion(sid)
        for p in paros:
            dur = _min_entre(p["inicio_paro"], p["fin_paro"])
            causa = p["descripcion"] or "(sin causa registrada)"
            zona = p["zona"] or "(sin zona)"
            folio = p["folio"]
            # El corte de luz SI lleva folio (ocurrio con el trabajo cargado),
            # asi que el filtro va ANTES de cualquier acumulacion para que no
            # cuelte en el bloque "Por folio" del cruce.
            productivo = _cuenta_como_paro(p["descripcion"])
            if folio is not None and productivo:
                keyf = (folio, p["num_part"] or "")
                agf = paros_por_folio.setdefault(
                    keyf, {"paros": 0, "min": 0.0})
                agf["paros"] += 1
                if dur is not None:
                    agf["min"] += dur
            filas_paro.append([
                sid, operador,
                folio if folio is not None else SIN_TRABAJO,
                p["num_part"] or "",
                causa, zona,
                p["inicio_paro"] or "",
                p["fin_paro"] or "En curso",
                dur if dur is not None else 0.0,
                p["autorizador"] or (
                    "Sin autorizar" if not p["fin_paro"] else "(sin registro)"
                ),
            ])
            if not productivo:
                continue
            if dur is not None:
                por_causa[causa]["paros"] += 1
                por_causa[causa]["min"] += dur
                por_zona[zona]["paros"] += 1
                por_zona[zona]["min"] += dur
                por_operador[operador]["min_paro"] += dur
                por_operador[operador]["paros"] += 1
                matriz_op_causa[operador][causa] += dur
            else:
                por_operador[operador]["paros"] += 1
                por_causa[causa]["paros"] += 1
                por_zona[zona]["paros"] += 1
        por_operador[operador]["cortes"] += s["total_cortes"] or 0
        filas_sesion.append([
            sid, operador,
            s["fecha_inicio"] or "",
            s["fecha_fin"] or "En curso",
            s["total_cortes"] or 0,
            s["estado"] or "",
            s["minutos"] or 0.0,
            # `num_paros` (no `len(paros)`): paros PRODUCTIVOS, los mismos que
            # suman el Resumen. Aqui no hay tabla de detalle debajo que
            # justifique el total bruto.
            s["num_paros"] or 0,
        ])
        for t in trabajos:
            meta = t["cantidad_total"] or 0
            # Por SEGMENTO (igual que el desglose): detectados de ESTA sesion
            # y lo validado al cerrar ESE segmento (0 si solo se pauso).
            det_seg = t["cantidad_sesion"] or 0
            conf_seg = t["confirmados"] or 0
            avance = round(conf_seg / meta, 4) if meta else 0.0
            modalidad = t["modalidad"]
            seg_ini = t["fecha_inicio"] or ""
            seg_fin = t["fecha_fin"]  # None = segmento abierto
            # Estado guardado al cerrar el segmento (no el folio actual).
            estado_seg = t["estado_segmento"] or (
                "En curso" if seg_fin is None else t["estado"]
            )
            if not seg_fin:
                modalidad_txt = "En curso"
            else:
                modalidad_txt = MODALIDAD_NOMBRE.get(modalidad, modalidad)
            filas_trabajo.append([
                sid, operador, t["folio"], t["num_part"] or "",
                meta, det_seg, conf_seg, det_seg - conf_seg,
                avance, seg_ini, seg_fin or "En curso",
                modalidad_txt, estado_seg,
                0, 0.0,
            ])
            key = (t["folio"], t["num_part"] or "")
            agg = por_folio.setdefault(
                key, {"cortado": 0, "conf": 0})
            agg["cortado"] += t["cantidad_sesion"] or 0
            agg["conf"] += conf_seg
        # Paros del segmento desde BD (uno solo por paro, solo los
        # productivos): el primero que lo solapa en orden cronologico se lo
        # queda.
        vistos = set()
        base_filas = len(filas_trabajo) - len(trabajos)
        for i in range(base_filas, len(filas_trabajo)):
            f = filas_trabajo[i]
            ini_seg = f[9]
            fin_seg = None if f[10] == "En curso" else f[10]
            for p in paros_de_segmento(sid, ini_seg, fin_seg):
                if p["id"] in vistos or not _cuenta_como_paro(p["descripcion"]):
                    continue
                vistos.add(p["id"])
                f[13] += 1
                if p["duracion_min"] is not None:
                    f[14] += p["duracion_min"]
            f[14] = round(f[14], 1)

    wb = Workbook()

    # ---- Sesiones ----
    ws_ses = wb.active
    ws_ses.title = "Sesiones"
    enc_ses = ["ID", "Operador", "Inicio", "Fin", "Cortes", "Estado", "Min", "Paros"]
    _formato_base(wb, ws_ses, enc_ses, [8, 28, 19, 19, 10, 12, 10, 8])
    for f in filas_sesion:
        ws_ses.append(f)
    ws_ses.sheet_properties.tabColor = "1F4E78"
    for r in range(2, 2 + len(filas_sesion)):
        ws_ses.cell(row=r, column=7).number_format = "0.0"
    _tabla(ws_ses, f"A1:H{1 + len(filas_sesion)}", "TblSesiones", len(filas_sesion))

    # ---- Paros ----
    ws_par = wb.create_sheet("Paros")
    enc_par = ["Sesión", "Operador", "Folio", "Parte", "Causa", "Zona",
               "Inicio", "Fin", "Duración min", "Autorizó"]
    _formato_base(wb, ws_par, enc_par, [9, 24, 14, 14, 30, 16, 19, 19, 13, 22])
    for f in filas_paro:
        ws_par.append(f)
    ws_par.sheet_properties.tabColor = "C00000"
    for r in range(2, 2 + len(filas_paro)):
        ws_par.cell(row=r, column=9).number_format = "0.0"
    _tabla(ws_par, f"A1:J{1 + len(filas_paro)}", "TblParos", len(filas_paro))

    # ---- Trabajos (todo por segmento, nada acumulado) ----
    ws_tra = wb.create_sheet("Trabajos")
    enc_tra = ["Sesión", "Operador", "Folio", "Parte", "Meta",
               "Detectados", "Confirmados", "Diferencia",
               "Avance %", "Inicio", "Fin", "Modalidad", "Estado",
               "Nº paros", "Min paro"]
    _formato_base(wb, ws_tra, enc_tra,
                  [9, 24, 12, 14, 10, 12, 12, 12, 10, 19, 19, 16, 10, 10, 10])
    for f in filas_trabajo:
        ws_tra.append(f)
    ws_tra.sheet_properties.tabColor = "548235"
    for r in range(2, 2 + len(filas_trabajo)):
        ws_tra.cell(row=r, column=9).number_format = "0%"
        ws_tra.cell(row=r, column=15).number_format = "0.0"
    _tabla(ws_tra, f"A1:O{1 + len(filas_trabajo)}", "TblTrabajos", len(filas_trabajo))

    # ---- Resumen (KPIs con formulas + top causas estatico) ----
    ws_res = wb.create_sheet("Resumen", 0)
    ws_res.sheet_properties.tabColor = "FFC000"
    ws_res.column_dimensions["A"].width = 26
    ws_res.column_dimensions["B"].width = 20
    ws_res["A1"] = "Reporte del día"
    ws_res["B1"] = fecha
    ws_res["A1"].font = Font(bold=True, size=14)
    kpis = [
        ("Sesiones", "=COUNTA(Sesiones!A2:A1048576)"),
        ("Cortes totales", "=SUM(Sesiones!E2:E1048576)"),
        ("Min producción", "=SUM(Sesiones!G2:G1048576)"),
        # Paro = todo MENOS las causas no productivas (`CAUSAS_NO_PRODUCTIVAS`):
        # la espera de trabajo (ociosa, sin folio) y el corte de luz. El corte
        # de luz es una omision del operador al apagar sin cerrar sesion, no
        # una falla de la maquina: restarle disponibilidad al turno seri
        # penalizar al operador por algo que no controla. Se excluye con un
        # criterio por causa sobre la misma columna.
        ("Min paro",
         "=SUMIFS(Paros!I2:I1048576,Paros!E2:E1048576,"
         "\"<>Esperando trabajo\",Paros!E2:E1048576,"
         "\"<>Computadora apagada\")"),
        ("Disponibilidad", "=IF(B4=0,0,1-B5/B4)"),
        ("Nº paros",
         "=COUNTIFS(Paros!A2:A1048576,\"<>\",Paros!E2:E1048576,"
         "\"<>Esperando trabajo\",Paros!E2:E1048576,"
         "\"<>Computadora apagada\")"),
        ("Segmentos folio×sesión", "=COUNTA(Trabajos!A2:A1048576)"),
        # Informativas (NO entran en disponibilidad ni en el cruce): lo que se
        # salio de los agregados se reporta aparte, no se esconde.
        ("Nº esperas",
         "=COUNTIF(Paros!E2:E1048576,\"Esperando trabajo\")"),
        ("Min espera",
         "=SUMIF(Paros!E2:E1048576,\"Esperando trabajo\",Paros!I2:I1048576)"),
        ("Nº cortes de luz",
         "=COUNTIF(Paros!E2:E1048576,\"Computadora apagada\")"),
        ("Min computadora apagada",
         "=SUMIF(Paros!E2:E1048576,\"Computadora apagada\","
         "Paros!I2:I1048576)"),
    ]
    for i, (etiqueta, formula) in enumerate(kpis, start=2):
        ws_res.cell(row=i, column=1, value=etiqueta)
        ws_res.cell(row=i, column=2, value=formula)
    ws_res["B6"].number_format = "0.0%"
    for r in range(2, 2 + len(kpis)):
        ws_res.cell(row=r, column=1).font = Font(bold=True)
    top = sorted(por_causa.items(), key=lambda kv: kv[1]["min"], reverse=True)[:5]
    base_top = 2 + len(kpis) + 1
    ws_res.cell(row=base_top, column=1, value="Top causas del día").font = Font(bold=True, size=12)
    for j, h in enumerate(["Causa", "Paros", "Min"], start=1):
        c = ws_res.cell(row=base_top + 1, column=j, value=h)
        c.fill = PatternFill("solid", fgColor=AZUL_CABECERA)
        c.font = Font(bold=True, color="FFFFFF")
    for i, (causa, d) in enumerate(top, start=base_top + 2):
        ws_res.cell(row=i, column=1, value=causa)
        ws_res.cell(row=i, column=2, value=d["paros"])
        ws_res.cell(row=i, column=3, value=round(d["min"], 1))
    ws_res.column_dimensions["C"].width = 14
    ws_res.freeze_panes = "A2"

    # ---- Cruces (pre-calculados) ----
    ws_cru = wb.create_sheet("Cruces")
    ws_cru.sheet_properties.tabColor = "7030A0"
    fila = 1

    def bloque(titulo, encabezados, datos, anchos):
        nonlocal fila
        ws_cru.cell(row=fila, column=1, value=titulo).font = Font(bold=True, size=12)
        fila += 1
        for j, h in enumerate(encabezados, start=1):
            c = ws_cru.cell(row=fila, column=j, value=h)
            c.fill = PatternFill("solid", fgColor=AZUL_CABECERA)
            c.font = Font(bold=True, color="FFFFFF")
            c.alignment = Alignment(horizontal="center")
        for j, a in enumerate(anchos, start=1):
            ws_cru.column_dimensions[get_column_letter(j)].width = max(
                ws_cru.column_dimensions[get_column_letter(j)].width or 0, a
            )
        fila += 1
        inicio = fila
        for reg in datos:
            for j, v in enumerate(reg, start=1):
                ws_cru.cell(row=fila, column=j, value=v)
            fila += 1
        fila += 1
        return inicio

    b1 = bloque("Por operador", ["Operador", "Cortes", "Paros", "Min paro"],
                [[op, v["cortes"], v["paros"], round(v["min_paro"], 1)]
                 for op, v in sorted(por_operador.items())],
                [26, 12, 10, 12])
    b2 = bloque("Por causa", ["Causa", "Paros", "Min"],
                [[c, v["paros"], round(v["min"], 1)]
                 for c, v in sorted(por_causa.items(), key=lambda kv: -kv[1]["min"])],
                [32, 10, 12])
    bloque("Por zona", ["Zona", "Paros", "Min"],
           [[z, v["paros"], round(v["min"], 1)]
            for z, v in sorted(por_zona.items(), key=lambda kv: -kv[1]["min"])],
           [24, 10, 12])
    # Por folio: cortado/confirmados de sus segmentos + paros vinculados
    # directo al folio (sin duplicar por renglon).
    claves_folio = sorted(set(por_folio) | set(paros_por_folio))
    bloque("Por folio", ["Folio", "Parte", "Cortado día", "Confirmados",
                         "Paros", "Min paro"],
           [[folio, parte,
             por_folio.get((folio, parte), {}).get("cortado", 0),
             por_folio.get((folio, parte), {}).get("conf", 0),
             paros_por_folio.get((folio, parte), {}).get("paros", 0),
             round(paros_por_folio.get((folio, parte), {}).get("min", 0.0), 1)]
            for (folio, parte) in claves_folio],
           [12, 16, 13, 13, 10, 12])
    causas_top = sorted(por_causa, key=lambda c: -por_causa[c]["min"])[:8]
    ops = sorted(por_operador)
    bloque("Matriz operador × causa (min)", ["Operador"] + causas_top,
           [[op] + [round(matriz_op_causa[op][c], 1) for c in causas_top]
            for op in ops],
           [26] + [14] * max(len(causas_top), 1))

    if por_causa and len(por_causa) >= 1:
        try:
            chart = BarChart()
            chart.title = "Min paro por causa"
            chart.y_axis.title = "Min"
            n = len(por_causa)
            # Bloque "Por causa": `b2` es la PRIMERA fila de datos, asi que el
            # encabezado (titulo de la serie) esta en `b2-1` y los datos van de
            # `b2` a `b2+n-1`. Con `min_row=b2` el titulo salia del primer
            # valor (la leyenda mostraba un numero), se perdia la causa con
            # mas minutos y se colaba la fila en blanco como barra fantasma.
            chart.add_data(
                Reference(ws_cru, min_col=3, min_row=b2 - 1, max_row=b2 + n - 1),
                titles_from_data=True,
            )
            chart.set_categories(
                Reference(ws_cru, min_col=1, min_row=b2, max_row=b2 + n - 1)
            )
            chart.height = 7.5
            ws_cru.add_chart(chart, f"A{fila}")
        except Exception:
            log.warning("No se pudo agregar grafico de cruces", exc_info=True)
    ws_cru.freeze_panes = "A2"
    _ = b1

    # ---- LEEME ----
    ws_lee = wb.create_sheet("LEEME")
    ws_lee.column_dimensions["A"].width = 110
    guia = [
        "Cómo cruzar la información (tablas dinámicas en 2 clics):",
        "",
        "1. Ve a Paros, Trabajos o Sesiones (ya son Tablas: TblParos, TblTrabajos, TblSesiones).",
        "2. Insertar > Tabla dinámica > Aceptar (usa la tabla actual).",
        "3. Arrastra: Filas=Causa/Zona/Folio, Valores=Suma de Duración min o Cuenta.",
        "",
        "Notas:",
        "- Folio '—sin trabajo—' = paro sin trabajo (Primera pieza con permiso, espera de QR o corte de luz sin QR).",
        "- Trabajos: un renglon por segmento (folio x sesion) con Inicio/Fin propios. 'Detectados' es lo cortado en ESE segmento, 'Confirmados' lo validado al cerrarlo (0 si solo se pauso), 'Avance %' su aporte, 'Estado' si YA alcanzaba la meta en ese punto, y 'Nº paros'/'Min paro' solo los caidos en su ventana.",
        "- Paro = todo MENOS 'Esperando trabajo' y 'Computadora apagada': ambas "
        "se listan en Paros pero quedan fuera de Nº paros, Min paro y "
        "Disponibilidad (la espera es tiempo ocioso; el corte de luz es una "
        "omisión del operador al apagar sin cerrar sesión, no una falla de la "
        "máquina).",
        "- Lo excluido no se esconde: se informa aparte como 'Nº esperas'/"
        "'Min espera' y 'Nº cortes de luz'/'Min computadora apagada'.",
        "- Un paro '(sin causa registrada)' sí cuenta como paro: si no se "
        "registró causa, no sabemos qué fue y medirlo es más honesto que "
        "esconderlo.",
        "- Resumen usa fórmulas sobre las hojas (se recalculan al abrir en Excel).",
        "- Cruces viene pre-calculado para lo más pedido: por operador, causa, zona y folio.",
    ]
    for i, linea in enumerate(guia, start=1):
        ws_lee.cell(row=i, column=1, value=linea)
    ws_lee["A1"].font = Font(bold=True, size=12)

    try:
        wb.save(ruta_destino)
    except PermissionError:
        log.warning("Excel bloqueado por otro proceso: %s", ruta_destino)
        return False, (
            "No se pudo guardar: el archivo está abierto en Excel u otro "
            "programa. Ciérralo o elige otro nombre."
        ), {}
    except OSError as e:
        log.error("No se pudo guardar Excel en %s: %s", ruta_destino, e)
        return False, f"No se pudo guardar: {e}", {}

    stats = {
        "fecha": fecha,
        "sesiones": len(filas_sesion),
        "paros": len(filas_paro),
        "trabajos": len(filas_trabajo),
    }
    log.info("Export día %s -> %s (%s)", fecha, ruta_destino, stats)
    return True, f"Día {fecha}: {len(filas_sesion)} sesiones, {len(filas_paro)} paros, {len(filas_trabajo)} trabajos.", stats


# ---------------------------------------------------------------------------
# Export comparativo de DOS rangos de fechas (mismo boton de Exportar de
# Sesiones). Cada rango se exporta con las mismas hojas y el mismo criterio
# de paros productivos que exportar_dia, pero en un solo libro con sufijos
# "A" y "B" para comparar turno contra turno, semana contra semana, etc.
# ---------------------------------------------------------------------------

def _rango_valido(fecha_inicio: str, fecha_fin: str) -> bool:
    try:
        di = datetime.strptime(fecha_inicio, "%Y-%m-%d").date()
        df = datetime.strptime(fecha_fin, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return False
    return di <= df


def _recolectar_rango(fecha_inicio: str, fecha_fin: str):
    """Recolecta filas de sesiones/paros/trabajos y cruces de un rango.

    Devuelve un dict con las mismas claves que `exportar_dia` acumula en sus
    listas locales, para poder reusar el armado de hojas.
    """
    from src.database import (
        listar_sesiones_en_rango,
        listar_trabajos_de_sesion,
        obtener_paros_de_sesion,
        paros_de_segmento,
    )

    filas_sesion, filas_paro, filas_trabajo = [], [], []
    por_operador = defaultdict(lambda: {"cortes": 0, "min_paro": 0.0, "paros": 0})
    por_causa = defaultdict(lambda: {"paros": 0, "min": 0.0})
    por_zona = defaultdict(lambda: {"paros": 0, "min": 0.0})
    por_folio = {}
    paros_por_folio = {}
    matriz_op_causa = defaultdict(lambda: defaultdict(float))

    sesiones = listar_sesiones_en_rango(fecha_inicio, fecha_fin)
    for s in sesiones:
        sid = s["id"]
        operador = s["nombre"]
        paros = obtener_paros_de_sesion(sid)
        trabajos = listar_trabajos_de_sesion(sid)
        for p in paros:
            dur = _min_entre(p["inicio_paro"], p["fin_paro"])
            causa = p["descripcion"] or "(sin causa registrada)"
            zona = p["zona"] or "(sin zona)"
            folio = p["folio"]
            productivo = _cuenta_como_paro(p["descripcion"])
            if folio is not None and productivo:
                keyf = (folio, p["num_part"] or "")
                agf = paros_por_folio.setdefault(keyf, {"paros": 0, "min": 0.0})
                agf["paros"] += 1
                if dur is not None:
                    agf["min"] += dur
            filas_paro.append([
                sid, operador,
                folio if folio is not None else SIN_TRABAJO,
                p["num_part"] or "",
                causa, zona,
                p["inicio_paro"] or "",
                p["fin_paro"] or "En curso",
                dur if dur is not None else 0.0,
                p["autorizador"] or (
                    "Sin autorizar" if not p["fin_paro"] else "(sin registro)"
                ),
            ])
            if not productivo:
                continue
            if dur is not None:
                por_causa[causa]["paros"] += 1
                por_causa[causa]["min"] += dur
                por_zona[zona]["paros"] += 1
                por_zona[zona]["min"] += dur
                por_operador[operador]["min_paro"] += dur
                por_operador[operador]["paros"] += 1
                matriz_op_causa[operador][causa] += dur
            else:
                por_operador[operador]["paros"] += 1
                por_causa[causa]["paros"] += 1
                por_zona[zona]["paros"] += 1
        por_operador[operador]["cortes"] += s["total_cortes"] or 0
        filas_sesion.append([
            sid, operador,
            s["fecha_inicio"] or "",
            s["fecha_fin"] or "En curso",
            s["total_cortes"] or 0,
            s["estado"] or "",
            s["minutos"] or 0.0,
            s["num_paros"] or 0,
        ])
        for t in trabajos:
            meta = t["cantidad_total"] or 0
            det_seg = t["cantidad_sesion"] or 0
            conf_seg = t["confirmados"] or 0
            avance = round(conf_seg / meta, 4) if meta else 0.0
            seg_ini = t["fecha_inicio"] or ""
            seg_fin = t["fecha_fin"]
            estado_seg = t["estado_segmento"] or (
                "En curso" if seg_fin is None else t["estado"]
            )
            filas_trabajo.append([
                sid, operador, t["folio"], t["num_part"] or "",
                meta, det_seg, conf_seg, det_seg - conf_seg,
                avance, seg_ini, seg_fin or "En curso",
                MODALIDAD_NOMBRE.get(t["modalidad"], t["modalidad"]),
                estado_seg, 0, 0.0,
            ])
            key = (t["folio"], t["num_part"] or "")
            agg = por_folio.setdefault(key, {"cortado": 0, "conf": 0})
            agg["cortado"] += t["cantidad_sesion"] or 0
            agg["conf"] += conf_seg
        vistos = set()
        base_filas = len(filas_trabajo) - len(trabajos)
        for i in range(base_filas, len(filas_trabajo)):
            f = filas_trabajo[i]
            ini_seg = f[9]
            fin_seg = None if f[10] == "En curso" else f[10]
            for p in paros_de_segmento(sid, ini_seg, fin_seg):
                if p["id"] in vistos or not _cuenta_como_paro(p["descripcion"]):
                    continue
                vistos.add(p["id"])
                f[13] += 1
                if p["duracion_min"] is not None:
                    f[14] += p["duracion_min"]
            f[14] = round(f[14], 1)

    return {
        "sesiones": filas_sesion,
        "paros": filas_paro,
        "trabajos": filas_trabajo,
        "por_operador": por_operador,
        "por_causa": por_causa,
        "por_zona": por_zona,
        "por_folio": por_folio,
        "paros_por_folio": paros_por_folio,
        "matriz_op_causa": matriz_op_causa,
    }


def _hoja_sesiones(wb, filas, tabcolor="1F4E78", nombre="Sesiones", tabla_nombre="TblSesiones"):
    ws = wb.create_sheet(nombre)
    ws.sheet_properties.tabColor = tabcolor
    enc = ["ID", "Operador", "Inicio", "Fin", "Cortes", "Estado", "Min", "Paros"]
    _formato_base(wb, ws, enc, [8, 28, 19, 19, 10, 12, 10, 8])
    for f in filas:
        ws.append(f)
    for r in range(2, 2 + len(filas)):
        ws.cell(row=r, column=7).number_format = "0.0"
    _tabla(ws, f"A1:H{1 + len(filas)}", tabla_nombre, len(filas))
    return ws


def _hoja_paros(wb, filas, tabcolor="C00000", nombre="Paros", tabla_nombre="TblParos"):
    ws = wb.create_sheet(nombre)
    ws.sheet_properties.tabColor = tabcolor
    enc = ["Sesión", "Operador", "Folio", "Parte", "Causa", "Zona",
           "Inicio", "Fin", "Duración min", "Autorizó"]
    _formato_base(wb, ws, enc, [9, 24, 14, 14, 30, 16, 19, 19, 13, 22])
    for f in filas:
        ws.append(f)
    for r in range(2, 2 + len(filas)):
        ws.cell(row=r, column=9).number_format = "0.0"
    _tabla(ws, f"A1:J{1 + len(filas)}", tabla_nombre, len(filas))
    return ws


def _hoja_trabajos(wb, filas, tabcolor="548235", nombre="Trabajos", tabla_nombre="TblTrabajos"):
    ws = wb.create_sheet(nombre)
    ws.sheet_properties.tabColor = tabcolor
    enc = ["Sesión", "Operador", "Folio", "Parte", "Meta",
           "Detectados", "Confirmados", "Diferencia",
           "Avance %", "Inicio", "Fin", "Modalidad", "Estado",
           "Nº paros", "Min paro"]
    _formato_base(wb, ws, enc,
                  [9, 24, 12, 14, 10, 12, 12, 12, 10, 19, 19, 16, 10, 10, 10])
    for f in filas:
        ws.append(f)
    for r in range(2, 2 + len(filas)):
        ws.cell(row=r, column=9).number_format = "0%"
        ws.cell(row=r, column=15).number_format = "0.0"
    _tabla(ws, f"A1:O{1 + len(filas)}", tabla_nombre, len(filas))
    return ws


def _hoja_cruces(wb, datos, tabcolor="7030A0", nombre="Cruces"):
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    ws = wb.create_sheet(nombre)
    ws.sheet_properties.tabColor = tabcolor
    fila = 1

    def bloque(titulo, encabezados, filas_datos, anchos):
        nonlocal fila
        ws.cell(row=fila, column=1, value=titulo).font = Font(bold=True, size=12)
        fila += 1
        for j, h in enumerate(encabezados, start=1):
            c = ws.cell(row=fila, column=j, value=h)
            c.fill = PatternFill("solid", fgColor=AZUL_CABECERA)
            c.font = Font(bold=True, color="FFFFFF")
            c.alignment = Alignment(horizontal="center")
        for j, a in enumerate(anchos, start=1):
            letra = get_column_letter(j)
            ws.column_dimensions[letra].width = max(
                ws.column_dimensions[letra].width or 0, a
            )
        fila += 1
        inicio = fila
        for reg in filas_datos:
            for j, v in enumerate(reg, start=1):
                ws.cell(row=fila, column=j, value=v)
            fila += 1
        fila += 1
        return inicio

    bloque("Por operador", ["Operador", "Cortes", "Paros", "Min paro"],
           [[op, v["cortes"], v["paros"], round(v["min_paro"], 1)]
            for op, v in sorted(datos["por_operador"].items())],
           [26, 12, 10, 12])
    bloque("Por causa", ["Causa", "Paros", "Min"],
           [[c, v["paros"], round(v["min"], 1)]
            for c, v in sorted(datos["por_causa"].items(),
                               key=lambda kv: -kv[1]["min"])],
           [32, 10, 12])
    bloque("Por zona", ["Zona", "Paros", "Min"],
           [[z, v["paros"], round(v["min"], 1)]
            for z, v in sorted(datos["por_zona"].items(),
                               key=lambda kv: -kv[1]["min"])],
           [24, 10, 12])
    claves_folio = sorted(set(datos["por_folio"]) | set(datos["paros_por_folio"]))
    bloque("Por folio", ["Folio", "Parte", "Cortado", "Confirmados",
                         "Paros", "Min paro"],
           [[folio, parte,
             datos["por_folio"].get((folio, parte), {}).get("cortado", 0),
             datos["por_folio"].get((folio, parte), {}).get("conf", 0),
             datos["paros_por_folio"].get((folio, parte), {}).get("paros", 0),
             round(datos["paros_por_folio"].get((folio, parte), {}).get("min", 0.0), 1)]
            for (folio, parte) in claves_folio],
           [12, 16, 13, 13, 10, 12])
    ws.freeze_panes = "A2"
    return ws


def _hoja_resumen_comparativo(wb, res_a, res_b, etiqueta_a, etiqueta_b,
                              fecha_inicio_a, fecha_fin_a,
                              fecha_inicio_b, fecha_fin_b):
    """Hoja Resumen con KPIs de ambos rangos lado a lado y la diferencia."""
    from openpyxl.styles import Font, PatternFill

    ws = wb.create_sheet("Resumen", 0)
    ws.sheet_properties.tabColor = "FFC000"
    ws.column_dimensions["A"].width = 30
    ws.column_dimensions["B"].width = 16
    ws.column_dimensions["C"].width = 16
    ws.column_dimensions["D"].width = 12

    ws["A1"] = "Reporte comparativo"
    ws["A1"].font = Font(bold=True, size=14)
    ws["A2"] = f"{etiqueta_a}: {fecha_inicio_a} al {fecha_fin_a}"
    ws["B2"] = etiqueta_a
    ws["C2"] = etiqueta_b
    ws["D2"] = "Diferencia (B - A)"
    for col in ("B", "C", "D"):
        ws[f"{col}2"].font = Font(bold=True)

    def kpis(datos):
        """Lista de (etiqueta, valor numerico) de un rango."""
        sesiones = len(datos["sesiones"])
        cortes = sum(f[4] for f in datos["sesiones"])
        min_prod = sum(f[6] for f in datos["sesiones"])
        min_paro = sum(v["min_paro"] for v in datos["por_operador"].values())
        n_paros = sum(v["paros"] for v in datos["por_operador"].values())
        disp = (1 - min_paro / min_prod) if min_prod else 0
        return [
            ("Sesiones", sesiones),
            ("Cortes totales", cortes),
            ("Min producción", round(min_prod, 1)),
            ("Min paro", round(min_paro, 1)),
            ("Disponibilidad", round(disp, 4)),
            ("Nº paros", n_paros),
            ("Segmentos folio×sesión", len(datos["trabajos"])),
        ]

    ka, kb = kpis(res_a), kpis(res_b)
    fila = 3
    for i, ((etq_a, v_a), (etq_b, v_b)) in enumerate(zip(ka, kb)):
        assert etq_a == etq_b
        ws.cell(row=fila, column=1, value=etq_a).font = Font(bold=True)
        ws.cell(row=fila, column=2, value=v_a)
        ws.cell(row=fila, column=3, value=v_b)
        ws.cell(row=fila, column=4, value=round(v_b - v_a, 4))
        fila += 1

    # Top causas de cada rango (informativo, debajo de los KPIs).
    fila += 1
    ws.cell(row=fila, column=1, value="Top 5 causas (A)").font = Font(bold=True, size=12)
    ws.cell(row=fila, column=3, value="Top 5 causas (B)").font = Font(bold=True, size=12)
    fila += 1
    for j, h in enumerate(["Causa", "Min", "Causa", "Min"], start=1):
        c = ws.cell(row=fila, column=j, value=h)
        c.fill = PatternFill("solid", fgColor=AZUL_CABECERA)
        c.font = Font(bold=True, color="FFFFFF")
    fila += 1
    top_a = sorted(res_a["por_causa"].items(), key=lambda kv: -kv[1]["min"])[:5]
    top_b = sorted(res_b["por_causa"].items(), key=lambda kv: -kv[1]["min"])[:5]
    for i in range(5):
        ca = top_a[i] if i < len(top_a) else ("", {"min": 0.0, "paros": 0})
        cb = top_b[i] if i < len(top_b) else ("", {"min": 0.0, "paros": 0})
        ws.cell(row=fila, column=1, value=ca[0])
        ws.cell(row=fila, column=2, value=round(ca[1]["min"], 1))
        ws.cell(row=fila, column=3, value=cb[0])
        ws.cell(row=fila, column=4, value=round(cb[1]["min"], 1))
        fila += 1

    ws.freeze_panes = "A2"
    return ws


def exportar_rango_comparativo(fecha_inicio_a: str, fecha_fin_a: str,
                               fecha_inicio_b: str, fecha_fin_b: str,
                               ruta_destino: str,
                               etiqueta_a: str = "Rango A",
                               etiqueta_b: str = "Rango B"):
    """Exporta DOS rangos de fechas en un solo .xlsx para compararlos.

    Cada rango se recolecta con el mismo criterio que `exportar_dia` (paros
    productivos excluyendo espera de trabajo y corte de luz) y se vuelca en
    hojas con sufijo A / B, mas una hoja Resumen con KPIs lado a lado y su
    diferencia.

    Devuelve (ok, mensaje, stats). Si algun rango esta vacio, avisa sin
    generar archivo (Excel no abre un libro sin datos utiles).
    """
    from openpyxl import Workbook

    for finicio, ffin, nom in (
        (fecha_inicio_a, fecha_fin_a, "A"),
        (fecha_inicio_b, fecha_fin_b, "B"),
    ):
        if not _rango_valido(finicio, ffin):
            msg = (
                f"Rango {nom} invalido: '{finicio}' al '{ffin}'. "
                "Usa YYYY-MM-DD y fin >= inicio."
            )
            return False, msg, {}

    if not str(ruta_destino).lower().endswith(".xlsx"):
        ruta_destino = str(ruta_destino) + ".xlsx"

    res_a = _recolectar_rango(fecha_inicio_a, fecha_fin_a)
    res_b = _recolectar_rango(fecha_inicio_b, fecha_fin_b)

    if not res_a["sesiones"] and not res_b["sesiones"]:
        return False, (
            "No hay sesiones en ninguno de los dos rangos."
        ), {}

    wb = Workbook()
    _hoja_resumen_comparativo(
        wb, res_a, res_b, etiqueta_a, etiqueta_b,
        fecha_inicio_a, fecha_fin_a, fecha_inicio_b, fecha_fin_b,
    )

    suf_a = f" {etiqueta_a}".replace(" ", "_") if etiqueta_a != "Rango A" else " A"
    suf_b = f" {etiqueta_b}".replace(" ", "_") if etiqueta_b != "Rango B" else " B"

    _hoja_sesiones(
        wb, res_a["sesiones"], nombre=f"Sesiones{suf_a}",
        tabla_nombre=f"TblSesiones{suf_a}",
    )
    _hoja_sesiones(
        wb, res_b["sesiones"], nombre=f"Sesiones{suf_b}",
        tabla_nombre=f"TblSesiones{suf_b}",
    )
    _hoja_paros(
        wb, res_a["paros"], nombre=f"Paros{suf_a}",
        tabla_nombre=f"TblParos{suf_a}",
    )
    _hoja_paros(
        wb, res_b["paros"], nombre=f"Paros{suf_b}",
        tabla_nombre=f"TblParos{suf_b}",
    )
    _hoja_trabajos(
        wb, res_a["trabajos"], nombre=f"Trabajos{suf_a}",
        tabla_nombre=f"TblTrabajos{suf_a}",
    )
    _hoja_trabajos(
        wb, res_b["trabajos"], nombre=f"Trabajos{suf_b}",
        tabla_nombre=f"TblTrabajos{suf_b}",
    )
    _hoja_cruces(wb, res_a, nombre=f"Cruces{suf_a}")
    _hoja_cruces(wb, res_b, nombre=f"Cruces{suf_b}")

    try:
        wb.save(ruta_destino)
    except PermissionError:
        log.warning("Excel bloqueado por otro proceso: %s", ruta_destino)
        return False, (
            "No se pudo guardar: el archivo está abierto en Excel u otro "
            "programa. Ciérralo o elige otro nombre."
        ), {}
    except OSError as e:
        log.error("No se pudo guardar Excel en %s: %s", ruta_destino, e)
        return False, f"No se pudo guardar: {e}", {}

    stats = {
        "rango_a": f"{fecha_inicio_a} al {fecha_fin_a}",
        "rango_b": f"{fecha_inicio_b} al {fecha_fin_b}",
        "sesiones_a": len(res_a["sesiones"]),
        "paros_a": len(res_a["paros"]),
        "trabajos_a": len(res_a["trabajos"]),
        "sesiones_b": len(res_b["sesiones"]),
        "paros_b": len(res_b["paros"]),
        "trabajos_b": len(res_b["trabajos"]),
    }
    log.info(
        "Export comparativo %s vs %s -> %s", fecha_inicio_a, fecha_inicio_b,
        ruta_destino, stats,
    )
    return True, (
        f"Comparativo: {etiqueta_a} ({len(res_a['sesiones'])} sesiones) vs "
        f"{etiqueta_b} ({len(res_b['sesiones'])} sesiones)."
    ), stats

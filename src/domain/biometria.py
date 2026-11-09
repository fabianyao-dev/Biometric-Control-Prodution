"""Reglas puras de decision biometrica (sin hardware, Qt ni SQLite).

El score de comparacion de DigitalPersona es una DISIMILITUD: 0 es una
coincidencia perfecta y `0x7FFFFFFF` ninguna coincidencia. La tasa de falsos
positivos (FAR) es aproximadamente `score / 0x7FFFFFFF`.

Este modulo solo decide, dado un conjunto de candidatos de una busqueda 1:N,
cual es el operador ganador. La captura, el umbral y la persistencia viven en
las capas de hardware/servicio y base de datos.
"""

PROBABILIDAD_UNO = 0x7FFFFFFF


def elegir_candidato(candidatos, ids_por_indice, umbral, margen=0):
    """Elige el mejor candidato de una identificacion 1:N.

    `candidatos` son pares ``(indice, score)`` devueltos por el lector (no
    hace falta que vengan ordenados) e `ids_por_indice` mapea cada indice de
    plantilla a un id de operador.

    Devuelve ``(indice, score)`` del mejor candidato dentro del umbral o
    ``None`` si no hay coincidencia valida. Tambien devuelve ``None`` cuando
    el segundo mejor candidato pertenece a OTRO operador y queda dentro del
    margen de ambiguedad: es preferible pedir la huella de nuevo antes que
    confundir a dos personas.

    Los indices fuera de rango se descartan; nunca se indexa a ciegas una
    respuesta del SDK.
    """
    validos = []
    for idx, score in candidatos or []:
        if not (0 <= idx < len(ids_por_indice)):
            continue
        if score is None or score > umbral:
            continue
        validos.append((idx, score))
    if not validos:
        return None

    validos.sort(key=lambda par: par[1])
    mejor_idx, mejor_score = validos[0]
    mejor_operador = ids_por_indice[mejor_idx]

    for idx, score in validos[1:]:
        if ids_por_indice[idx] == mejor_operador:
            continue
        if score - mejor_score <= margen:
            return None
        break

    return mejor_idx, mejor_score

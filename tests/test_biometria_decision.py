"""
test_biometria_decision.py - Decision pura de una identificacion 1:N.

El SDK devuelve un score de DISIMILITUD (0 = match perfecto). Antes se
aceptaba cualquier mejor candidato por debajo del umbral, sin revisar al
segundo: con dos operadores parecidos se podia iniciar sesion como el
equivocado. `elegir_candidato()` concentra esa decision (sin hardware) para
poder probarla aqui.

Casos que fija este archivo:

- Solo cuenta un candidato dentro del umbral.
- Un indice fuera de rango jamas se indexa (respuesta corrupta del SDK).
- El segundo candidato del MISMO operador no es ambiguo (varias huellas).
- El segundo candidato de OTRO operador dentro del margen SI es ambiguo.
- El margen 0 solo rechaza empates exactos entre operadores distintos.
"""

from src.domain.biometria import elegir_candidato


class TestElegirCandidato:
    def test_sin_candidatos(self):
        assert elegir_candidato([], [1, 2], umbral=100) is None

    def test_mejor_dentro_del_umbral(self):
        candidatos = [(4, 80), (2, 20)]
        assert elegir_candidato(candidatos, [10, 11, 12, 13, 14], 100) == (2, 20)

    def test_descarta_candidatos_fuera_del_umbral(self):
        assert elegir_candidato([(0, 101)], [10], 100) is None

    def test_descarta_indice_fuera_de_rango(self):
        assert elegir_candidato([(9, 1)], [10], 100) is None

    def test_ignora_indice_invalido_y_usa_el_valido(self):
        candidatos = [(9, 1), (0, 50)]
        assert elegir_candidato(candidatos, [10], 100) == (0, 50)

    def test_segundo_candidato_del_mismo_operador_no_es_ambiguo(self):
        candidatos = [(0, 10), (1, 30)]
        ids = [7, 7]
        assert elegir_candidato(candidatos, ids, 100, margen=100) == (0, 10)

    def test_segundo_candidato_de_otro_operador_es_ambiguo(self):
        candidatos = [(0, 10), (1, 30)]
        ids = [7, 8]
        assert elegir_candidato(candidatos, ids, 100, margen=100) is None

    def test_otro_operador_suficientemente_lejos_no_es_ambiguo(self):
        candidatos = [(0, 10), (1, 90)]
        ids = [7, 8]
        assert elegir_candidato(candidatos, ids, 100, margen=50) == (0, 10)

    def test_margen_cero_rechaza_empate_exacto(self):
        candidatos = [(0, 10), (1, 10)]
        ids = [7, 8]
        assert elegir_candidato(candidatos, ids, 100, margen=0) is None

    def test_margen_cero_acepta_diferencia_minima(self):
        candidatos = [(0, 10), (1, 11)]
        ids = [7, 8]
        assert elegir_candidato(candidatos, ids, 100, margen=0) == (0, 10)

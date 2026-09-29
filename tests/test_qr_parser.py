"""
test_qr_parser.py - El contrato del QR de trabajo: `folio|num_part|cantidad`.

El QR es la puerta de entrada de cada trabajo. Un cambio tonto en el parser
corta la produccion de la planta entera, y hasta ahora no habia ni un test.

Decisiones de negocio que este archivo fija (no son accidentales):

- El separador es ESTRICTO: solo `|`. SeGmO aceptaba `]`, `}` y `\\` porque
  los escaneres USB tipo teclado mandan codigos de tecla de una distribucion
  US y Windows los traduce segun la disposicion activa, asi que con la PC en
  ES/Latinoamericano el `|` puede llegar como `]`. Aceptarlos hacia: el
  operador no se enteraba del error y el trabajo se cargaba a medias.
- `num_part` NO se convierte a entero: es texto libre (p. ej. "MH-2045-B").

La validacion vive en `parsear_qr()`, funcion pura extraida de
`HuellaModal._leer_qr`. Devuelve la tupla, o el string con el motivo del
rechazo.
"""

import pytest

from src.gui.huella_modal import parsear_qr


class TestQrsValidos:
    def test_qr_basico(self):
        assert parsear_qr("1001|MH-2045|50") == (1001, "MH-2045", 50)

    def test_tolera_espacios_around_del_separador(self):
        assert parsear_qr(" 1001 | MH-2045 | 50 ") == (1001, "MH-2045", 50)

    def test_num_part_es_texto_libre(self):
        """`num_part` no es un entero: admite guiones, puntos, letras."""
        folio, num_part, cantidad = parsear_qr("77|PZA-2024-A.3|10")
        assert folio == 77
        assert num_part == "PZA-2024-A.3"
        assert cantidad == 10

    def test_cantidad_de_un_solo_pie(self):
        assert parsear_qr("5|PIEZA|1") == (5, "PIEZA", 1)

    def test_folio_y_cantidad_grandes(self):
        assert parsear_qr("999999|PARTE-XYZ|999999") == (999999, "PARTE-XYZ", 999999)

    def test_folio_con_ceros_a_la_izquierda(self):
        assert parsear_qr("0042|ABC|7") == (42, "ABC", 7)


class TestFormatoInvalido:
    def test_solo_dos_campos(self):
        resultado = parsear_qr("1001|MH-2045")
        assert isinstance(resultado, str)
        assert "Formato invalido" in resultado

    def test_cuatro_campos(self):
        assert isinstance(parsear_qr("1001|MH-2045|50|EXTRA"), str)

    def test_texto_vacio(self):
        assert isinstance(parsear_qr(""), str)

    def test_solo_separadores(self):
        assert isinstance(parsear_qr("||"), str)

    def test_campo_extra_al_final(self):
        """`1001|A|50|` son 4 campos (el ultimo vacio): no debe aceptarse."""
        assert isinstance(parsear_qr("1001|A|50|"), str)


class TestSeparadorEstricto:
    """El separador es SOLO `|`. Cualquier otro simbolo es un QR invalido.

    Estos tests son la razon de ser del parser estricto: si alguien vuelve a
    "ser permisivo" por el problema de distribucion de teclado, fallan.
    """

    @pytest.mark.parametrize(
        "separador",
        ["]", "}", "\\", ",", ";", ":", "|", " ", "-", ">", "\t"],
    )
    def test_separadores_aceptados_unicamente_si_son_pipe(self, separador):
        texto = f"1001{separador}MH-2045{separador}50"
        resultado = parsear_qr(texto)
        if separador == "|":
            assert resultado == (1001, "MH-2045", 50)
        else:
            assert isinstance(resultado, str), f"'{separador}' no deberia separar"

    def test_corchete_bracket_se_rechaza(self):
        """El caso real de la PC en ES: `|` llega como `]`."""
        resultado = parsear_qr("1001]MH-2045]50")
        assert isinstance(resultado, str)
        assert "Formato invalido" in resultado

    def test_llave_se_rechaza(self):
        assert isinstance(parsear_qr("1001}MH-2045}50"), str)


class TestValidacionDeCampos:
    def test_folio_no_numerico(self):
        resultado = parsear_qr("ABC|MH-2045|50")
        assert "Folio no numerico" in resultado

    def test_cantidad_no_numerica(self):
        resultado = parsear_qr("1001|MH-2045|NOCHE")
        assert "Cantidad no numerica" in resultado

    def test_folio_cero(self):
        assert "mayor que cero" in parsear_qr("0|MH-2045|50")

    def test_folio_negativo(self):
        assert "mayor que cero" in parsear_qr("-5|MH-2045|50")

    def test_cantidad_cero(self):
        assert "mayor que cero" in parsear_qr("1001|MH-2045|0")

    def test_cantidad_negativa(self):
        assert "mayor que cero" in parsear_qr("1001|MH-2045|-3")

    def test_num_part_vacio(self):
        resultado = parsear_qr("1001||50")
        assert "numero de parte" in resultado

    def test_num_part_solo_espacios(self):
        """`num_part` se hace strip antes de validarse: " " es vacio."""
        resultado = parsear_qr("1001|   |50")
        assert "numero de parte" in resultado

    def test_flotante_rechazado(self):
        """`1001|A|50.5` no vale: la cantidad es un entero de piezas."""
        assert "Cantidad no numerica" in parsear_qr("1001|A|50.5")


class TestOrdenDeValidacion:
    """El mensaje de error debe ser el del campo que se reporta primero.

    Importa en planta: el operador ve UN motivo y actua sobre el. Si el parser
    reportara "Cantidad no numerica" para un folio que tambien es basura, el
    operador corregiria el campo equivocado y el QR volveria a fallar.
    """

    def test_folio_malo_gana_sobre_cantidad_mala(self):
        assert "Folio no numerico" in parsear_qr("ABC|PARTE|NOCHE")

    def test_campos_vacios_ganan_sobre_valores_no_numericos(self):
        assert "Formato invalido" in parsear_qr("")

    def test_folio_se_valida_antes_que_cantidad_no_numerica(self):
        assert "Folio no numerico" in parsear_qr("ABC|A|NOCHE")

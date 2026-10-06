"""
test_modalidades_cierre.py - El stepper de cantidad del cierre de trabajo (#5).

Los tests no crean QApplication (convencion de la suite), asi que solo se
prueba la logica PURA `ajustar_cantidad`: es la que ejecutan los botones
+/- y las flechas del input de "FINALIZAR TRABAJO".

Cubren lo que un error aqui dejaria VER en pantalla sin romper nada: una
cantidad que baja de cero (el trabajo se guardaria con piezas negativas) o
que se pasa del tope del QIntValidator.
"""

from src.gui.modalidades_cierre import MAX_CANTIDAD, ajustar_cantidad


def test_ajustar_cantidad_suma_y_resta_de_uno():
    """El paso de los botones +/- es exactamente 1."""
    assert ajustar_cantidad("120", 1) == "121"
    assert ajustar_cantidad("120", -1) == "119"
    assert ajustar_cantidad("0", 1) == "1"


def test_ajustar_cantidad_con_un_tope_de_1_si_puede_atrasar():
    """Con 1 ya mostrado, el '-' lo regresa a 0 (no lo salta)."""
    assert ajustar_cantidad("1", -1) == "0"


def test_ajustar_cantidad_nunca_baja_de_cero():
    """El input no admite negativos: a partir de 0, '-' se queda en 0."""
    assert ajustar_cantidad("0", -1) == "0"
    assert ajustar_cantidad("-5", -1) == "0"


def test_ajustar_cantidad_no_pasa_del_tope():
    """Igual que el QIntValidator(0, MAX_CANTIDAD): tope por encima."""
    assert ajustar_cantidad(str(MAX_CANTIDAD), 1) == str(MAX_CANTIDAD)
    assert ajustar_cantidad(str(MAX_CANTIDAD - 1), 5) == str(MAX_CANTIDAD)


def test_ajustar_cantidad_con_texto_vacio_o_invalido_empieza_en_cero():
    """Vacio o basura tecleada cuentan como 0 y avanzan desde ahi."""
    assert ajustar_cantidad("", 1) == "1"
    assert ajustar_cantidad("   ", -1) == "0"
    assert ajustar_cantidad("12a", 1) == "1"
    assert ajustar_cantidad("abc", -1) == "0"


def test_ajustar_cantidad_acepta_espacios_alrededor():
    """El input puede traer espacios tecleados: se toleran."""
    assert ajustar_cantidad("  120  ", 1) == "121"

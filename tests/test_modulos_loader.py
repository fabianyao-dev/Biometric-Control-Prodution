"""Descubrimiento de modulos: `crear_vista` no debe impedir el registro."""

from src.gui.modulos import registro
from src.gui.modulos.loader import descubrir


def test_descubrir_registra_corte_y_omite_plantilla():
    registro.limpiar()
    descubrir()
    claves = [m.clave for m in registro.modulos_registrados()]
    assert "corte" in claves
    assert "plantilla" not in claves
    corte = registro.obtener("corte")
    assert corte is not None
    assert corte.predeterminado is True
    assert callable(corte.crear_vista)

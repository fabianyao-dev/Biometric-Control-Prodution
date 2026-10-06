"""
test_inicio_view.py - Regresiones de la vista de Inicio sin abrir ventanas.

Los tests no crean QApplication, asi que se invocan metodos como funciones
no enlazadas (`InicioView._segundos_desde(None, getter)`) o sobre un objeto
falso: ambos caminos solo tocan logica pura, no widgets.

Cubren el OverflowError reportado en produccion al apagar la maquina con la
sesion abierta, y su consecuencia peor: la cadena de checkpoints
(`_checkpoint_cortes` se re-programa a si mismo) moria en silencio y los
respaldos ante apagones dejaban de guardarse hasta reiniciar la app.
"""

from datetime import datetime, timedelta


def _ts(texto):
    return datetime.strptime(texto, "%Y-%m-%d %H:%M:%S")


def test_segundos_desde_con_infinito_devuelve_none():
    """Maquina detenida -> `segundos_desde_arranque` devuelve inf.

    `timedelta(seconds=inf)` lanza OverflowError; el valor no es medible y
    se descarta con None (el checkpoint sigue vivo).
    """
    from src.gui.inicio_view import InicioView

    assert InicioView._segundos_desde(None, lambda: float("inf")) is None


def test_segundos_desde_con_dato_invalido_devuelve_none():
    """Negativo, None o un HAL que revienta: nunca un timestamp."""
    from src.gui.inicio_view import InicioView

    assert InicioView._segundos_desde(None, lambda: -1.0) is None
    assert InicioView._segundos_desde(None, lambda: None) is None

    def _revienta():
        raise AttributeError("segundos_desde_arranque")

    assert InicioView._segundos_desde(None, _revienta) is None


def test_segundos_desde_con_valor_finito_resta_los_segundos():
    from src.database import ahora_local
    from src.gui.inicio_view import InicioView

    antes = ahora_local()
    ts = InicioView._segundos_desde(None, lambda: 90.0)
    despues = ahora_local()

    assert ts is not None
    assert _ts(ts) >= _ts(antes) - timedelta(seconds=90)
    assert _ts(ts) <= _ts(despues) - timedelta(seconds=90)


def test_checkpoint_se_reprograma_aunque_el_cuerpo_reviente(monkeypatch):
    """El `QTimer.singleShot` final vive en un finally: la cadena no se rompe.

    Antes estaba DESPUES del cuerpo, asi que la primera excepcion (p. ej. el
    OverflowError del infinito) mataba todos los checkpoints siguientes.
    """
    from src.gui import inicio_view as vista

    programadas = []

    class _QTimerFalso:
        @staticmethod
        def singleShot(ms, callback):
            programadas.append((ms, callback))

    monkeypatch.setattr(vista, "QTimer", _QTimerFalso)

    class _ControladorFalso:
        @staticmethod
        def cortes_totales():
            raise RuntimeError("boom")

    class _VistaFalsa:
        sesion_id = 1
        _trabajo = None
        controlador = _ControladorFalso()
        _checkpoint_cortes = vista.InicioView._checkpoint_cortes

    _VistaFalsa()._checkpoint_cortes()

    assert len(programadas) == 1, (
        "un fallo en el cuerpo no debe impedir programar el proximo checkpoint"
    )

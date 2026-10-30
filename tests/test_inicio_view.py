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

import time
from datetime import datetime, timedelta

import pytest


def _ts(texto):
    return datetime.strptime(texto, "%Y-%m-%d %H:%M:%S")


def test_segundos_desde_con_infinito_devuelve_none():
    """Maquina detenida -> `segundos_desde_arranque` devuelve inf.

    `timedelta(seconds=inf)` lanza OverflowError; el valor no es medible y
    se descarta con None (el checkpoint sigue vivo).
    """
    from src.gui.modulos.corte.inicio_view import InicioView

    assert InicioView._segundos_desde(None, lambda: float("inf")) is None


def test_segundos_desde_con_dato_invalido_devuelve_none():
    """Negativo, None o un HAL que revienta: nunca un timestamp."""
    from src.gui.modulos.corte.inicio_view import InicioView

    assert InicioView._segundos_desde(None, lambda: -1.0) is None
    assert InicioView._segundos_desde(None, lambda: None) is None

    def _revienta():
        raise AttributeError("segundos_desde_arranque")

    assert InicioView._segundos_desde(None, _revienta) is None


def test_segundos_desde_con_valor_finito_resta_los_segundos():
    from src.database import ahora_local
    from src.gui.modulos.corte.inicio_view import InicioView

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
    from src.gui.modulos.corte import inicio_view as vista

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


# ----------------------------------------------------------------------
# Torre de luces: decision de color (logica pura, sin widgets)
# ----------------------------------------------------------------------

class _ControladorTorre:
    """Controlador minimo: solo responde si la maquina esta detenida."""

    def __init__(self, detenida):
        self.detenida = detenida
        self.torre = []

    def maquina_detenida(self):
        return self.detenida

    def establecer_torre(self, verde=False, ambar=False, roja=False):
        self.torre.append((verde, ambar, roja))

    def pulso_alarma(self):
        self.torre.append("ALARMA")


def _vista_torre(detenida=False, **attrs):
    """InicioView sin Qt: `_estado_torre` solo lee atributos."""
    from src.gui.modulos.corte.inicio_view import InicioView

    vista = InicioView.__new__(InicioView)
    vista.controlador = _ControladorTorre(detenida)
    vista.sesion_id = 7
    vista._modo_mantenimiento = False
    vista._modo_paro = False
    vista._primera_pieza = False
    vista._en_paro = False
    vista._paro_inicio_momento = None
    vista._ultimo_color_rojo = None
    for clave, valor in attrs.items():
        setattr(vista, clave, valor)
    return vista


@pytest.fixture
def tol_60(monkeypatch):
    """Tolerancia de torre corta para los tests.

    La tolerancia real es `PRIMERA_PIEZA_TIMEOUT_S` (900 s por defecto):
    demasiado larga para fabricar un paro vencido en un test.
    """
    from src import config

    monkeypatch.setattr(config, "PRIMERA_PIEZA_TIMEOUT_S", 60, raising=False)


def test_torre_sin_sesion_queda_apagada():
    vista = _vista_torre(sesion_id=None)
    assert vista._estado_torre() == (False, False, False)


def test_torre_verde_con_la_maquina_en_marcha():
    vista = _vista_torre(detenida=False)
    assert vista._estado_torre() == (True, False, False)


def test_torre_ambar_con_la_maquina_detenida():
    vista = _vista_torre(detenida=True)
    assert vista._estado_torre() == (False, True, False)


def test_torre_ambar_en_primera_pieza_con_maquina_encendida():
    vista = _vista_torre(detenida=False, _primera_pieza=True)
    assert vista._estado_torre() == (False, True, False)


def test_torre_ambar_en_mantenimiento():
    vista = _vista_torre(detenida=False, _modo_mantenimiento=True)
    assert vista._estado_torre() == (False, True, False)


def test_torre_ambar_dentro_de_la_tolerancia_de_paro():
    vista = _vista_torre(
        detenida=True, _en_paro=True,
        _paro_inicio_momento=time.time() - 5,
    )
    assert vista._estado_torre() == (False, True, False)


def test_torre_roja_pasada_la_tolerancia_de_paro(tol_60):
    vista = _vista_torre(
        detenida=True, _en_paro=True,
        _paro_inicio_momento=time.time() - 120,
    )
    assert vista._estado_torre() == (False, False, True)


def test_torre_sin_momento_de_paro_no_se_pone_roja():
    vista = _vista_torre(detenida=True, _en_paro=True)
    assert vista._estado_torre() == (False, True, False)


# --- Regresiones del reporte de planta: la roja nunca encendia -------------
# El modo PARO cortaba la decision en ambar, asi que un paro autorizado
# jamas llegaba al rojo (ni al buzzer de Q6). La tolerancia debe aplicar a
# TODOS los paros reales, no solo al instante previo a la autorizacion.


def test_torre_roja_en_modo_paro_pasada_la_tolerancia(tol_60):
    vista = _vista_torre(
        detenida=True, _en_paro=True, _modo_paro=True,
        _paro_inicio_momento=time.time() - 120,
    )
    assert vista._estado_torre() == (False, False, True)


def test_torre_ambar_en_modo_paro_dentro_de_la_tolerancia():
    vista = _vista_torre(
        detenida=True, _en_paro=True, _modo_paro=True,
        _paro_inicio_momento=time.time() - 5,
    )
    assert vista._estado_torre() == (False, True, False)


def test_torre_roja_en_mantenimiento_con_la_maquina_detenida(tol_60):
    vista = _vista_torre(
        detenida=True, _modo_mantenimiento=True,
        _paro_inicio_momento=time.time() - 120,
    )
    assert vista._estado_torre() == (False, False, True)


def test_torre_ambar_en_paro_de_zona_con_la_maquina_en_marcha():
    """Zona 'maquina encendida': sigue cortando, asi que no hay roja."""
    vista = _vista_torre(
        detenida=False, _en_paro=True, _modo_paro=True,
        _paro_inicio_momento=time.time() - 120,
    )
    assert vista._estado_torre() == (False, True, False)


def test_torre_no_se_pone_roja_en_espera_de_trabajo():
    """Sin paro abierto (maquina apagada esperando folio) solo hay ambar."""
    vista = _vista_torre(detenida=True,
                         _paro_inicio_momento=time.time() - 120)
    assert vista._estado_torre() == (False, True, False)


def test_tolerancia_de_paro_usa_primera_pieza_timeout_s(monkeypatch):
    """La tolerancia de la torre es `PRIMERA_PIEZA_TIMEOUT_S`."""
    from src import config

    monkeypatch.setattr(config, "PRIMERA_PIEZA_TIMEOUT_S", 5, raising=False)
    vista = _vista_torre(
        detenida=True, _en_paro=True,
        _paro_inicio_momento=time.time() - 6,
    )
    assert vista._estado_torre() == (False, False, True)


def test_tolerancia_de_paro_no_usa_paro_idle_timeout_s(monkeypatch):
    """El minuto del auto-paro por inactividad NO es la tolerancia."""
    from src import config

    monkeypatch.setattr(config, "PARO_IDLE_TIMEOUT_S", 1, raising=False)
    monkeypatch.setattr(config, "PRIMERA_PIEZA_TIMEOUT_S", 900, raising=False)
    vista = _vista_torre(
        detenida=True, _en_paro=True,
        _paro_inicio_momento=time.time() - 120,
    )
    assert vista._estado_torre() == (False, True, False)


def test_tolerancia_de_paro_en_cero_desactiva_la_roja(monkeypatch):
    from src import config

    monkeypatch.setattr(config, "PRIMERA_PIEZA_TIMEOUT_S", 0, raising=False)
    vista = _vista_torre(
        detenida=True, _en_paro=True,
        _paro_inicio_momento=time.time() - 999,
    )
    assert vista._estado_torre() == (False, True, False)


def test_tolerancia_ancla_el_paro_al_detener_la_maquina():
    vista = _vista_torre(detenida=True, _en_paro=True)
    vista._actualizar_tolerancia_paro()
    assert vista._paro_inicio_momento is not None


def test_tolerancia_no_ancla_sin_paro_real():
    vista = _vista_torre(detenida=True)
    vista._actualizar_tolerancia_paro()
    assert vista._paro_inicio_momento is None


def test_tolerancia_se_rearma_al_volver_a_la_marcha():
    vista = _vista_torre(detenida=True, _en_paro=True,
                         _paro_inicio_momento=time.time() - 120)
    vista.controlador.detenida = False
    vista._actualizar_tolerancia_paro()
    assert vista._paro_inicio_momento is None


def test_tolerancia_no_ancla_sin_sesion():
    vista = _vista_torre(detenida=True, _en_paro=True, sesion_id=None)
    vista._actualizar_tolerancia_paro()
    assert vista._paro_inicio_momento is None


def test_alarma_suena_al_entrar_en_rojo_desde_el_modo_paro(tol_60):
    vista = _vista_torre(
        detenida=True, _en_paro=True, _modo_paro=True,
        _paro_inicio_momento=time.time() - 120,
    )
    vista._actualizar_torre()
    assert vista.controlador.torre[-1] == "ALARMA"


def test_actualizar_torre_dispara_la_alarma_solo_al_entrar_en_rojo(tol_60):
    vista = _vista_torre(
        detenida=True, _en_paro=True,
        _paro_inicio_momento=time.time() - 120,
    )

    vista._actualizar_torre()
    vista._actualizar_torre()

    assert vista.controlador.torre.count("ALARMA") == 1

    # Al salir del rojo se rearma: la siguiente entrada vuelve a sonar.
    vista._en_paro = False
    vista.controlador.detenida = False
    vista._actualizar_torre()
    assert vista._ultimo_color_rojo is None

    vista._en_paro = True
    vista.controlador.detenida = True
    vista._actualizar_torre()
    assert vista.controlador.torre.count("ALARMA") == 2


def test_actualizar_torre_aplica_el_color_decidido():
    """La vista delega en el HAL, que es quien dedupe (sin trafico extra)."""
    vista = _vista_torre(detenida=False)

    vista._actualizar_torre()

    assert vista.controlador.torre == [(True, False, False)]
    assert vista._ultimo_color_rojo is None


def test_enviar_easy_num_part_llama_al_servicio():
    from unittest.mock import MagicMock, patch

    from src.gui.modulos.corte.inicio_view import InicioView

    vista = type("VistaFalsa", (), {"_estado": MagicMock()})()
    servicio = MagicMock()
    with patch("src.gui.modulos.corte.inicio_view.config.EASY_CONFIG",
              {"host": "192.168.1.84", "puerto": 5000,
               "rutina": "buscar_easy", "timeout": 30}), \
         patch("src.gui.modulos.corte.easy.service.desde_config", return_value=servicio):
        InicioView._enviar_easy_num_part(vista, "PARTE-999")
        servicio.ejecutar_rutina.assert_called_once()
        args, kwargs = servicio.ejecutar_rutina.call_args
        assert kwargs.get("callback") is not None


def test_enviar_easy_num_part_callback_error_actualiza_estado():
    from unittest.mock import MagicMock, patch

    from src.gui.modulos.corte.inicio_view import InicioView

    vista = type("VistaFalsa", (), {"_estado": MagicMock()})()
    servicio = MagicMock()
    with patch("src.gui.modulos.corte.inicio_view.config.EASY_CONFIG",
              {"host": "192.168.1.84", "puerto": 5000,
               "rutina": "buscar_easy", "timeout": 30}), \
         patch("src.gui.modulos.corte.easy.service.desde_config", return_value=servicio), \
         patch("src.gui.modulos.corte.inicio_view.QTimer.singleShot") as mock_single_shot:
        InicioView._enviar_easy_num_part(vista, "PARTE-999")
        cb = servicio.ejecutar_rutina.call_args[1]["callback"]
        cb(False, "Easy: error de red")
        mock_single_shot.assert_called_once()
        fn = mock_single_shot.call_args[0][1]
        fn()
        vista._estado.assert_called_once_with("Easy: error de red", "error")


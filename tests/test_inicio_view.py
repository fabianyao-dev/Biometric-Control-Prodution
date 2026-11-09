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
from collections import deque
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
    """Controlador minimo para la torre y el seguro anti-corrida."""

    def __init__(self, detenida):
        self.detenida = detenida
        self.torre = []
        self.cortes = 0
        self.excluidos = 0

    def maquina_detenida(self):
        return self.detenida

    def maquina_pausada(self):
        self.detenida = True

    def reprisar_maquina(self):
        self.detenida = False

    def establecer_torre(self, verde=False, ambar=False, roja=False):
        self.torre.append((verde, ambar, roja))

    def pulso_alarma(self):
        self.torre.append("ALARMA")

    def cortes_totales(self):
        return self.cortes

    def cortes_excluidos(self):
        return self.excluidos

    def incorporar_excluidos(self, cantidad=None):
        if cantidad is None:
            n = self.excluidos
        else:
            n = min(max(int(cantidad), 0), self.excluidos)
        self.cortes += n
        self.excluidos = 0

    def suspender_conteo(self):
        self.excluidos = 0

    def retomar_conteo(self):
        self.excluidos = 0

    def reiniciar_gracia_inactividad(self):
        pass


def _vista_torre(detenida=False, **attrs):
    """InicioView sin Qt: `_estado_torre` solo lee atributos."""
    from src.gui.modulos.corte.inicio_view import InicioView

    vista = InicioView.__new__(InicioView)
    vista.controlador = _ControladorTorre(detenida)
    vista.sesion_id = 7
    vista._modo_mantenimiento = False
    vista._modo_paro = False
    vista._modo_paro_maquina_encendida = False
    vista._primera_pieza = False
    vista._en_paro = False
    vista._paro_inicio_momento = None
    vista._ultimo_color_rojo = None
    vista._paro_autorizacion_pendiente = False
    vista._modal_abierto = False
    vista._trabajo = None
    vista._muestras_rafaga = deque()
    vista._ultimo_total_fisico = None
    vista._rafaga_en_curso = False
    vista._excluidos_previos_rafaga = 0
    vista._tiene_permiso_iniciar_primera_pieza = lambda: False
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


def test_torre_roja_en_paro_de_zona_con_la_maquina_en_marcha(tol_60):
    """Zona 'maquina encendida': la maquina sigue cortando, pero el paro sigue
    abierto, asi que al vencer la tolerancia la torre va a ROJA + alarma.

    La roja no significa 'maquina parada': significa 'paro pendiente por mas
    del tiempo permitido'.
    """
    vista = _vista_torre(
        detenida=False, _en_paro=True, _modo_paro=True,
        _paro_inicio_momento=time.time() - 120,
    )
    assert vista._estado_torre() == (False, False, True)


def test_torre_roja_en_primera_pieza_con_la_maquina_encendida(tol_60):
    """Primera pieza con la maquina encendida: al vencer la tolerancia la
    torre va a ROJA + alarma (salir del modo ya exige autorizacion)."""
    vista = _vista_torre(
        detenida=False, _primera_pieza=True,
        _paro_inicio_momento=time.time() - 120,
    )
    assert vista._estado_torre() == (False, False, True)


def test_torre_roja_en_mantenimiento_con_la_maquina_encendida(tol_60):
    """Mantenimiento con la maquina encendida: tambien escala a ROJA."""
    vista = _vista_torre(
        detenida=False, _modo_mantenimiento=True,
        _paro_inicio_momento=time.time() - 120,
    )
    assert vista._estado_torre() == (False, False, True)


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


def test_tolerancia_no_se_borra_si_la_maquina_sigue_en_marcha():
    """El ancla sobrevive a la maquina encendida durante el paro.

    Hay paros en los que la maquina DEBE seguir en marcha (zona con
    'maquina encendida', Mantenimiento, Primera pieza). Si el ancla se
    borrara al volver a la marcha, la tolerancia no venceria nunca y la
    roja + buzzer no se activarian.
    """
    vista = _vista_torre(detenida=True, _en_paro=True,
                         _paro_inicio_momento=time.time() - 120)
    vista.controlador.detenida = False
    vista._actualizar_tolerancia_paro()
    assert vista._paro_inicio_momento is not None


def test_tolerancia_se_rearma_al_resolver_el_paro():
    """Resuelto el paro (ya no hay paro real), el ancla se borra: la alarma
    del siguiente paro vuelve a contar desde cero."""
    vista = _vista_torre(detenida=False, _en_paro=True,
                         _paro_inicio_momento=time.time() - 120)
    vista._en_paro = False
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


# ----------------------------------------------------------------------
# Modal de autorizacion del paro: rojo + buzzer, ambar al autorizar
# ----------------------------------------------------------------------


def test_torre_roja_con_autorizacion_de_paro_pendiente():
    vista = _vista_torre(
        detenida=True, _en_paro=True,
        _paro_autorizacion_pendiente=True,
    )
    assert vista._estado_torre() == (False, False, True)


def test_actualizar_torre_dispara_alarma_al_abrir_modal_de_paro():
    vista = _vista_torre(
        detenida=True, _en_paro=True,
        _paro_autorizacion_pendiente=True,
    )
    vista._actualizar_torre()
    vista._actualizar_torre()
    assert vista.controlador.torre.count("ALARMA") == 1


def test_torre_ambar_al_autorizar_el_paro():
    vista = _vista_torre(
        detenida=True, _en_paro=True, _modo_paro=True,
        _paro_autorizacion_pendiente=False,
    )
    assert vista._estado_torre() == (False, True, False)


def test_torre_roja_al_autorizar_si_ya_vencio_la_tolerancia(tol_60):
    vista = _vista_torre(
        detenida=True, _en_paro=True, _modo_paro=True,
        _paro_autorizacion_pendiente=False,
        _paro_inicio_momento=time.time() - 120,
    )
    assert vista._estado_torre() == (False, False, True)


def test_autorizar_no_reinicia_el_ancla_de_la_tolerancia():
    vista = _vista_torre(
        detenida=True, _en_paro=True, _modo_paro=True,
        _paro_inicio_momento=time.time() - 30,
    )
    ancla = vista._paro_inicio_momento
    vista._actualizar_tolerancia_paro()
    assert vista._paro_inicio_momento == ancla


def test_torre_roja_directa_al_abrir_el_modal_de_paro(tol_60):
    """Con el modal abierto no pasa por ambar: verde -> rojo directo."""
    vista = _vista_torre(
        detenida=True, _en_paro=True,
        _paro_autorizacion_pendiente=True,
        _paro_inicio_momento=time.time(),
    )
    assert vista._estado_torre() == (False, False, True)


def test_autorizar_tarde_rearma_el_buzzer(tol_60):
    """Si la tolerancia vencio con el modal abierto, autorizar vuelve a sonar."""
    vista = _vista_torre(
        detenida=True, _en_paro=True, _modo_paro=True,
        _paro_autorizacion_pendiente=True,
        _paro_inicio_momento=time.time() - 120,
        _ultimo_color_rojo="rojo",
    )
    vista.paro_id = 5
    pulsos = []
    vista._pulso_buzzer_plc = lambda: pulsos.append(1)
    vista._refrescar_estado_maquina = lambda: None
    vista._estado = lambda *args, **kwargs: None
    vista._causa_descripcion = lambda causa_id: None

    vista._autorizado_autenticado(7, "Ana", causa_id=1)

    assert pulsos == [1]
    assert vista._estado_torre() == (False, False, True)


def test_autorizar_a_tiempo_no_rearma_el_buzzer(tol_60):
    vista = _vista_torre(
        detenida=True, _en_paro=True, _modo_paro=True,
        _paro_autorizacion_pendiente=True,
        _paro_inicio_momento=time.time(),
        _ultimo_color_rojo="rojo",
    )
    vista.paro_id = 5
    pulsos = []
    vista._pulso_buzzer_plc = lambda: pulsos.append(1)
    vista._refrescar_estado_maquina = lambda: None
    vista._estado = lambda *args, **kwargs: None
    vista._causa_descripcion = lambda causa_id: None

    vista._autorizado_autenticado(7, "Ana", causa_id=1)

    assert pulsos == []


def test_mantenimiento_iniciado_rearma_el_buzzer_si_vencio(tol_60):
    vista = _vista_torre(detenida=False)
    vista.paro_id = 5
    vista._modo_paro = True
    vista._paro_inicio_momento = time.time() - 120
    vista._ultimo_color_rojo = "rojo"
    pulsos = []
    vista._pulso_buzzer_plc = lambda: pulsos.append(1)
    vista._fijar_switch = lambda *args, **kwargs: None
    vista._refrescar_estado_maquina = lambda: None
    vista._estado = lambda *args, **kwargs: None

    vista._modo_mantenimiento_iniciado(7, "Ana", 8, "Mant", 1, None)

    assert vista._modo_mantenimiento is True
    assert pulsos == [1]


# ----------------------------------------------------------------------
# Ancla de la tolerancia: paro manual vs auto-paro por inactividad
# ----------------------------------------------------------------------


def _vista_pausable():
    """Vista falsa para `_pausar_maquina` sin abrir modales ni widgets."""
    vista = _vista_torre(detenida=False)
    vista.paro_id = None
    vista._folio_activo = lambda: None
    vista._refrescar_estado_maquina = lambda: None
    vista._abrir_paro_autorizacion = lambda: None
    vista._estado = lambda *args, **kwargs: None
    return vista


def test_auto_paro_ancla_la_tolerancia_en_el_ultimo_corte(
        monkeypatch, tol_60):
    monkeypatch.setattr(
        "src.gui.modulos.corte.inicio.paro_mixin.iniciar_paro",
        lambda *args, **kwargs: 99,
    )
    vista = _vista_pausable()
    vista._pausar_maquina(motivo="automatico", inicio_hace_s=120)
    assert vista._paro_inicio_momento <= time.time() - 120
    assert vista._estado_torre() == (False, False, True)


def test_paro_manual_ancla_la_tolerancia_al_pulsar_paro(monkeypatch):
    monkeypatch.setattr(
        "src.gui.modulos.corte.inicio.paro_mixin.iniciar_paro",
        lambda *args, **kwargs: 99,
    )
    vista = _vista_pausable()
    antes = time.time()
    vista._pausar_maquina()
    assert antes <= vista._paro_inicio_momento <= time.time()
    assert vista._en_paro is True


def test_paro_pasa_de_verde_a_rojo_sin_ambar_antes_del_modal(monkeypatch):
    """El primer refresco del paro ya es rojo: el modal se marca antes."""
    monkeypatch.setattr(
        "src.gui.modulos.corte.inicio.paro_mixin.iniciar_paro",
        lambda *args, **kwargs: 99,
    )
    vista = _vista_pausable()
    colores = []
    vista._refrescar_estado_maquina = (
        lambda: colores.append(vista._estado_torre())
    )

    vista._pausar_maquina()

    assert colores == [(False, False, True)]


# ----------------------------------------------------------------------
# Seguro anti-corrida en TODOS los paros reales (buzzer Q6)
# ----------------------------------------------------------------------


def _vista_rafaga(**attrs):
    vista = _vista_torre(detenida=True, **attrs)
    vista._sonar_alarma = lambda: None
    preguntas = []
    vista._preguntar_corrida = lambda n, v: preguntas.append((n, v))
    vista._preguntas = preguntas
    return vista


@pytest.mark.parametrize("attrs", [
    {"_en_paro": True},
    {"_en_paro": True, "_modo_paro": True},
    {"_en_paro": False, "_modo_mantenimiento": True},
    {"_en_paro": False, "_primera_pieza": True},
])
def test_rafaga_dispara_buzzer_y_pregunta_en_cualquier_paro(
        monkeypatch, attrs):
    from src import config

    monkeypatch.setattr(config, "SEGURO_RAFAGA_SEGUNDOS", 7, raising=False)
    monkeypatch.setattr(config, "SEGURO_RAFAGA_CORTES", 5, raising=False)
    vista = _vista_rafaga(**attrs)

    vista._verificar_rafaga_arranque()  # baseline en el contador actual
    vista.controlador.cortes = 6
    vista._verificar_rafaga_arranque()

    assert vista._rafaga_en_curso is True
    assert "ALARMA" in vista.controlador.torre
    assert vista._preguntas == [(6, 7)]


def test_rafaga_no_dispara_sin_paro_real(monkeypatch):
    from src import config

    monkeypatch.setattr(config, "SEGURO_RAFAGA_SEGUNDOS", 7, raising=False)
    monkeypatch.setattr(config, "SEGURO_RAFAGA_CORTES", 5, raising=False)
    vista = _vista_rafaga()  # sesion abierta pero sin paro (espera trabajo)

    vista._verificar_rafaga_arranque()
    vista.controlador.cortes = 10
    vista._verificar_rafaga_arranque()

    assert vista._rafaga_en_curso is False
    assert vista._preguntas == []


def test_total_fisico_suma_totales_y_excluidos():
    vista = _vista_torre(detenida=True, _en_paro=True, _primera_pieza=True)
    vista.controlador.cortes = 10
    vista.controlador.excluidos = 3
    assert vista._total_fisico() == 13


def test_corrida_confirmada_en_modo_paro_incorpora_y_cierra():
    vista = _vista_rafaga(
        _en_paro=True, _modo_paro=True,
        _modo_paro_maquina_encendida=True,
    )
    vista.controlador.cortes = 5
    vista.controlador.excluidos = 6
    vista._excluidos_previos_rafaga = 2
    cerrado = []
    vista._modo_paro_finalizado = lambda id_op, nombre: cerrado.append(
        (id_op, nombre)
    )
    vista._refrescar_labels_cortes = lambda: None
    vista._estado = lambda *args, **kwargs: None

    vista._corrida_confirmada_paro(7, "Ana")

    assert vista.controlador.cortes == 9   # 5 + (6 - 2)
    assert vista.controlador.excluidos == 0
    assert cerrado == [(7, "Ana")]


def test_corrida_confirmada_en_paro_normal_no_incorpora():
    vista = _vista_rafaga(_en_paro=True, _modo_paro=True)
    vista.controlador.cortes = 6
    vista._excluidos_previos_rafaga = 0
    vista._modo_paro_finalizado = lambda id_op, nombre: None
    vista._refrescar_labels_cortes = lambda: None
    vista._estado = lambda *args, **kwargs: None

    vista._corrida_confirmada_paro(7, "Ana")

    assert vista.controlador.cortes == 6


def test_corrida_confirmada_en_paro_no_autorizado_cierra_y_enciende(
        monkeypatch):
    vista = _vista_rafaga(_en_paro=True)
    vista.paro_id = 42
    finalizados = []
    monkeypatch.setattr(
        "src.gui.modulos.corte.inicio.seguridad_mixin.finalizar_paro",
        lambda *args: finalizados.append(args),
    )
    vista._refrescar_estado_maquina = lambda: None
    vista._refrescar_labels_cortes = lambda: None
    vista._estado = lambda *args, **kwargs: None

    vista._corrida_confirmada_paro(7, "Ana")

    assert vista.paro_id is None
    assert vista._en_paro is False
    assert vista.controlador.detenida is False  # reprisar_maquina
    assert finalizados == [(42, None, 7)]


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


# ----------------------------------------------------------------------
# Modo PARO con la maquina APAGADA por la zona
#
# El boton central sale del paro (huella) y deja la maquina ENCENDIDA. Antes
# se deshabilitaba (`btn_on=en_marcha`) justo cuando la zona la dejaba
# apagada, asi que el operador no podia volver a marcha desde ahi.
# ----------------------------------------------------------------------

class _ControladorParo:
    """HAL minimo para `_modo_paro_finalizado` (sin hardware)."""

    def __init__(self, en_marcha=False):
        self.en_marcha = en_marcha
        self.llamadas = []

    def maquina_detenida(self):
        return not self.en_marcha

    def reprisar_maquina(self):
        self.llamadas.append("reprisar")
        self.en_marcha = True

    def retomar_conteo(self):
        self.llamadas.append("retomar")

    def suspender_conteo(self):
        self.llamadas.append("suspender")

    def reiniciar_gracia_inactividad(self):
        self.llamadas.append("gracia")

    def establecer_torre(self, verde=False, ambar=False, roja=False):
        self.llamadas.append("torre")


def _vista_modo_paro(en_marcha):
    """InicioView sin Qt: solo los atributos que leen los metodos probados."""
    from src.gui.modulos.corte.inicio_view import InicioView

    vista = InicioView.__new__(InicioView)
    vista.controlador = _ControladorParo(en_marcha=en_marcha)
    vista.sesion_id = 7
    vista.paro_id = 99
    vista.operador_id = 1
    vista._en_paro = True
    vista._modo_paro = True
    vista._modo_paro_causa_id = 3
    vista._modo_paro_causa_desc = "Cambio de turno"
    vista._modo_paro_zona_id = None
    vista._modo_paro_maquina_encendida = en_marcha
    vista._primera_pieza = False
    vista._paro_idle_triggado = True
    vista._paro_inicio_momento = 123.0
    vista._ultimo_color_rojo = "rojo"
    return vista


def test_estado_modo_paro_con_la_maquina_apagada_habilita_el_boton_central():
    """El central sale del paro (con huella) y enciende: no se deshabilita."""
    estado = _vista_modo_paro(en_marcha=False)._estado_actual()

    assert estado["clave"] == "modo_paro_detenida"
    assert estado["btn_on"] is True
    assert "encender" in estado["tooltip"].lower()


def test_estado_modo_paro_con_la_maquina_en_marcha_habilita_el_boton_central():
    estado = _vista_modo_paro(en_marcha=True)._estado_actual()

    assert estado["clave"] == "modo_paro"
    assert estado["btn_on"] is True


@pytest.mark.parametrize("en_marcha", [False, True])
def test_salir_de_paro_enciende_la_maquina_si_la_zona_la_dejo_apagada(
    monkeypatch, en_marcha
):
    """SALIR DE PARO reanuda el conteo y enciende solo si estaba detenida."""
    from src.gui.modulos.corte.inicio import paro_mixin

    monkeypatch.setattr(paro_mixin, "finalizar_paro", lambda *a, **k: None)
    vista = _vista_modo_paro(en_marcha=en_marcha)
    mensajes = []
    vista._refrescar_estado_maquina = lambda: None
    vista._estado = lambda texto, tipo: mensajes.append((texto, tipo))

    vista._modo_paro_finalizado(1, "Operador")

    assert vista.controlador.en_marcha is True
    assert ("reprisar" in vista.controlador.llamadas) == (not en_marcha)
    assert vista._modo_paro is False
    assert vista._en_paro is False
    assert vista.paro_id is None
    assert "fin de paro" in mensajes[-1][0].lower()


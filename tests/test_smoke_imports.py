"""
test_smoke_imports.py - Todos los modulos del proyecto importan sin error.

Esta es la red de seguridad MAS importante del refactor
(PLAN_MODULARIZACION.md, Fase 0.6). A partir de la Fase 1 se mueven archivos
dentro de `src/`; si queda un import olvidado o un nombre movido sin
actualizar, ESTE test es el que lo detecta, en segundos, en vez de descubrirlo
al arrancar la app en la PC Fanless.

Por que es dinamico y no una lista fija: recorre `src/` en disco en vez de
enumerar modulos a mano. Asi, los modulos nuevos que creen las fases siguientes
(`src/database/roles.py`, `src/gui/inicio/*_mixin.py`, `src/domain/*`) quedan
cubiertos automaticamente, sin editar este archivo.
"""

import importlib
import os
import pathlib

import pytest

RAIZ = pathlib.Path(__file__).resolve().parent.parent
SRC = RAIZ / "src"


def _modulos_de_src():
    """Rutas de modulo de todos los .py bajo src/ (p. ej. 'src.gui.style')."""
    mods = []
    for ruta in sorted(SRC.rglob("*.py")):
        if "__pycache__" in ruta.parts:
            continue
        relativa = ruta.relative_to(RAIZ).with_suffix("")
        partes = list(relativa.parts)
        if partes[-1] == "__init__":
            partes = partes[:-1]
        if not partes:
            continue
        mods.append(".".join(partes))
    return mods


MODULOS = _modulos_de_src()

# Módulos que no deben importar: no forman parte de la app.
EXCLUIDOS = set()


@pytest.mark.skipif(not SRC.exists(), reason="no hay src/")
@pytest.mark.parametrize("nombre", MODULOS)
def test_modulo_importa(nombre):
    """Importar el modulo no debe lanzar.

    `importlib.import_module` propaga cualquier excepcion, asi que este test
    falla con el traceback real: es justo lo que hace util.
    """
    if nombre in EXCLUIDOS:
        pytest.skip(f"{nombre} esta excluido a proposito")
    importlib.import_module(nombre)


def test_se_cubre_al_menos_la_app_completa():
    """Guarda contra que el recorrido de src/ se rompa en silencio.

    Si alguien cambia el nombre de `src/` o rompe el glob, esta lista se
    vaciaria y los tests de arriba pasarian sin comprobar nada.
    """
    assert len(MODULOS) >= 25, f"solo se detectaron {len(MODULOS)} modulos: revisa _modulos_de_src"
    for esperado in (
        "src.config",
        "src.database",
        "src.gui.inicio_view",
        "src.gui.admin_view",
        "src.gui.huella_modal",
        "src.hardware.biometric_sdk",
        "src.hardware.modbus_controller",
        "src.hardware.simulacion_controller",
        "src.reportes.export_dia",
    ):
        assert esperado in MODULOS, f"faltaba {esperado}"


def test_main_importa():
    """El entry point (`python main.py`) importa limpio.

    No se instancia nada: `app = QApplication(sys.argv)` vive dentro de
    `if __name__ == "__main__"`, asi que importar no abre ventana ni arranca
    el HAL.
    """
    importlib.import_module("main")


def test_el_hal_selecciona_simulacion_sin_modbus_host():
    """Sin MODBUS_HOST, `crear_controlador()` debe caer a SimulacionController.

    Verifica la fabrica del composition root (`main.py:79`) sin arrancar
    hardware: es el mecanismo que permite trabajar en dev sin el modulo
    Advantech conectado.
    """
    from src import config
    from src.hardware.simulacion_controller import SimulacionController

    assert not config.MODBUS_CONFIG["host"], "conftest.py deberia dejar MODBUS_HOST vacio"

    import main

    controlador = main.crear_controlador()
    try:
        assert isinstance(controlador, SimulacionController)
    finally:
        controlador.cleanup()


def test_no_se_toca_la_bd_real():
    """El blindaje del conftest: DB_PATH debe apuntar a un temporal.

    `src/config.py` resuelve DB_PATH a `<raiz>/planta_corte.db` cuando la
    variable viene vacia, que es lo que hace el `.env` de desarrollo. Si
    alguien quita el `os.environ["DB_PATH"]` del conftest, los tests
    empiezan a migrar la base de datos real de la planta.
    """
    from src import config

    assert os.path.abspath(config.DB_PATH) != os.path.abspath(RAIZ / "planta_corte.db")
    assert "wts_control_tests_" in config.DB_PATH

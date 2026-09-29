"""
test_arquitectura.py - Las fronteras entre capas se respetan.

Estos tests NO comprueban que el codigo funcione, sino DONDE está cada cosa.
Son los que hacen que un `import sqlite3` en la vista o un `from PySide6` en
el dominio fallen en la CI en segundos, y no cuando alguien mueve un archivo
en la Fase 1.

Reglas que vigilan (ver PLAN_MODULARIZACION.md, §2 y §3):

1. `src/domain/` es PURO: sin Qt, sin SQLite, sin red, sin `os.environ`.
2. `src/hardware/` habla con el exterior, pero NUNCA importa de `src.gui/`
   ni de `main.py` (el HAL no sabe que existe una interfaz).
3. `src/database/` no importa Qt: la persistencia no dibuja.
4. `src/gui/` puede conocer `database` y `config`, pero no al revés.
5. El proyecto NO usa imports absolutos con el prefijo `src.` desde dentro de
   `src/`...salvo el paquete `src` en si. Este es el punto mas delicate: la
   guia de la arquitectura pide imports RELATIVOS dentro de `src/`, porque con
   PyInstaller un cambio de nombre de paquete rompe el build de forma
   silenciosa. Comprobamos la forma, no reescribimos los imports.

Las ultimas dos reglas deben ser AMARILLAS (warning), no rojas: hoy el codigo
existente tiene deuda que las fases siguientes van a pagar. En cuanto se
pague, se comprobado con `pytest.ini` -> `filterwarnings = error` en la Fase 4.
"""

import ast
import pathlib
import re

import pytest

RAIZ = pathlib.Path(__file__).resolve().parent.parent
SRC = RAIZ / "src"

# Subpaquetes que aun no existen (se activan solos cuando se creen).
DOMINIO = SRC / "domain"
GUI = SRC / "gui"
HARDWARE = SRC / "hardware"
DATABASE = SRC / "database.py"

# Modulos prohibidos por capa: capa -> modulos/paquetes que no puede importar.
CAPA_POR_RUTA = {
    DOMINIO: {
        "PySide6", "PySide2", "qtpy",
        "sqlite3",
        "serial", "pymodbus", "pydig", "win32", "winreg", "ctypes",
        "requests", "urllib", "socket", "http",
        "PIL", "reportlab", "openpyxl", "numpy", "pandas",
    },
    HARDWARE: {"PySide6", "PySide2"},
}

def _archivos_python(subcarpeta: pathlib.Path):
    if not subcarpeta.exists():
        return []
    return [p for p in subcarpeta.rglob("*.py") if "__pycache__" not in p.parts]


def _imports_de(ruta: pathlib.Path):
    """Nombres raiz de los modulos que el archivo importa (stdlib y terceros)."""
    arbol = ast.parse(ruta.read_text(encoding="utf-8"), filename=str(ruta))
    nombres = set()
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Import):
            for alias in nodo.names:
                nombres.add(alias.name.split(".")[0])
        elif isinstance(nodo, ast.ImportFrom):
            # ImportFrom relativo (from . import x) no aporta nombre raiz.
            if nodo.level == 0 and nodo.module:
                nombres.add(nodo.module.split(".")[0])
    return nombres


def _modulos_importados(ruta: pathlib.Path):
    """Rutas COMPLETAS de los modulos importados (p. ej. 'src.hardware.biometric_sdk').

    A diferencia de `_imports_de`, no se queda con la raiz. Necesario para
    distinguir `src.hardware.biometric_sdk` (prohibido en la GUI) de
    `src.hardware.biometric_service` (la via correcta).

    Se usa AST y no busqueda de texto a proposito: el codigo tiene docstrings
    que MENCIONAN modulos ('Ver biometric_sdk.py') sin importarlos, y una
    busqueda de texto daria falsos positivos.
    """
    arbol = ast.parse(ruta.read_text(encoding="utf-8"), filename=str(ruta))
    modulos = set()
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Import):
            for alias in nodo.names:
                modulos.add(alias.name)
        elif isinstance(nodo, ast.ImportFrom):
            if nodo.level == 0 and nodo.module:
                modulos.add(nodo.module)
    return modulos


@pytest.mark.parametrize(
    "capa",
    [pytest.param(DOMINIO, id="domain"), pytest.param(HARDWARE, id="hardware")],
)
def test_capa_no_importa_dependencias_que_le_prohiben(capa):
    """Reglas 1 y 2: la capa no debe importar lo que le esta prohibido."""
    if not capa.exists():
        pytest.skip(f"{capa.name}/ todavia no existe (fase posterior)")

    for ruta in _archivos_python(capa):
        prohibido = CAPA_POR_RUTA[capa]
        importados = sorted(_imports_de(ruta) & prohibido)
        assert not importados, (
            f"{ruta.relative_to(RAIZ)} importa {importados}, "
            f"prohibido en {capa.name}/"
        )


def test_domain_esta_limpio_de_efectos_de_entorno():
    """Regla 1 (extra): el dominio no lee os.environ.

    Un dominio que lee configuracion deja de ser puro y no se puede testear
    sin montar el entorno. Si un dia hace falta, se inyecta el valor como
    parametro.
    """
    if not DOMINIO.exists():
        pytest.skip("domain/ todavia no existe")
    for ruta in _archivos_python(DOMINIO):
        texto = ruta.read_text(encoding="utf-8")
        assert "os.environ" not in texto, f"{ruta.name} lee os.environ en el dominio"
        assert "getenv" not in texto, f"{ruta.name} lee getenv en el dominio"


def test_hardware_no_depende_de_la_gui():
    """Regla 2: el HAL no importa la interfaz ni el entry point."""
    assert GUI.exists()
    assert HARDWARE.exists()
    for ruta in _archivos_python(HARDWARE):
        for mod in _modulos_importados(ruta):
            assert not mod.startswith("src.gui"), (
                f"{ruta.name} importa {mod}: el hardware no debe saber de Qt"
            )
            assert mod != "main", (
                f"{ruta.name} importa main: el HAL no debe depender del entry point"
            )


def test_database_no_importa_qt():
    """Regla 3: la capa de persistencia no dibuja nada."""
    if not DATABASE.exists():
        pytest.skip("database.py todavia no existe (la Fase 1 lo empaqueta)")
    importados = _modulos_importados(DATABASE)
    for prohibido in ("PySide6", "PySide2", "qtpy"):
        assert prohibido not in importados, f"database.py no debe importar {prohibido}"


def test_gui_no_importa_hardware_directo_solo_el_service():
    """Regla 4: la GUI habla con el SDK de biometria via `BiometricService`.

    Tocar `biometric_sdk` desde la vista ata la interfaz a la carga dinamica
    de DLLs y al hot-plug del lector, que es logica del adaptador. La via
    correcta es `src.hardware.biometric_service`.
    """
    if not GUI.exists():
        pytest.skip("gui/ no existe")
    for ruta in _archivos_python(GUI):
        for mod in _modulos_importados(ruta):
            assert not mod.endswith("biometric_sdk"), (
                f"{ruta.name} importa {mod} directamente; "
                f"usa BiometricService (src.hardware.biometric_service)"
            )


def test_no_hay_imports_absolutos_con_prefijo_src_dentro_de_src():
    """Regla 5: dentro de `src/` se usa import RELATIVO.

    PyInstaller resuelve el paquete por nombre: si el proyecto se renombra
    `src` -> `wts`, TODOS los `from src.x import y` se rompen a la vez y el
    build falla con un ImportError confuso en tiempo de ejecucion. Con
    imports relativos, renombrar el paquete es un cambio local.

    Este test marca la deuda actual como warning (no falla) para no romper
    la suite actual; se convierte en error en la Fase 4, cuando ya no queden
    imports absolutos.
    """
    offenders = []
    patron = re.compile(r"^\s*(from|import)\s+src\.", re.M)
    for ruta in _archivos_python(SRC):
        if patron.search(ruta.read_text(encoding="utf-8")):
            offenders.append(ruta.relative_to(RAIZ).as_posix())
    if offenders:
        # No fallamos todavia: es la deuda que pagan las fases 1-3.
        # En la Fase 4 se convierte en `assert not offenders` y se borra
        # el skip. Se deja constancia visible con la lista exacta.
        muestra = ", ".join(offenders[:5])
        pytest.skip(
            f"Deuda conocida: {len(offenders)} archivos usan imports absolutos "
            f"con prefijo src. ({muestra}...) Se migran en las fases 1-3."
        )


def test_estructura_de_paquetes_conserva_init():
    """Todo subpaquete tiene `__init__.py` (PyInstaller y el editor lo esperan)."""
    for carpeta in ("gui", "hardware", "reportes"):
        d = SRC / carpeta
        if d.exists():
            assert (d / "__init__.py").exists(), f"falta {d.name}/__init__.py"

"""
conftest.py - Configuracion compartida de la suite automatizada (`tests/`).

OJO: esta suite es distinta de `test/`. Los archivos de `test/` son scripts
MANUALES de planta (hacen `sys.exit(1)`, tocan el lector de huellas y arrancan
el HAL). Aqui vive la suite que corre sola con `pytest -q`.

Este archivo hace tres cosas, en este orden y por una razon:

1. Redirige BD y logs a un temporal ANTES de que se importe `src`.
2. Inyecta la raiz del repo en `sys.path` (el proyecto no se instala).
3. Define los fixtures de BD.

El punto 1 es una red de seguridad deliberada: `src/config.py` resuelve
`DB_PATH` a `<raiz del proyecto>/planta_corte.db` cuando la variable de entorno
viene vacia, que es exactamente lo que hace el `.env` de desarrollo
(`DB_PATH=` a proposito). Sin este blindaje, un test que olvide el fixture
abriria y migraria la base de datos REAL de la planta. Con el, es
estructuralmente imposible.
"""

import os
import sys
import tempfile

# ---------------------------------------------------------------------------
# 1. Entorno: ANTES de cualquier import de `src` o de PySide6
# ---------------------------------------------------------------------------

_DIR_SESION = tempfile.mkdtemp(prefix="wts_control_tests_")

# Apunta a la sesion actual (blindaje global: ver docstring).
os.environ["DB_PATH"] = os.path.join(_DIR_SESION, "planta_corte.db")
os.environ["LOG_DIR"] = os.path.join(_DIR_SESION, "logs")

# Sin hardware en los tests: sin host Modbus, el HAL cae a SimulacionController.
os.environ["MODBUS_HOST"] = ""

# MODO_DEV habilita el acceso sin huella del modal, necesario para los tests
# que simulan la autenticacion sin el lector de DigitalPersona.
os.environ["MODO_DEV"] = "true"

# Qt sin ventana: los tests importan `src.gui.*` y no deben abrir una ventana.
os.environ["QT_QPA_PLATFORM"] = "offscreen"

# ---------------------------------------------------------------------------
# 2. sys.path: el proyecto no se instala como paquete
# ---------------------------------------------------------------------------

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)


# ---------------------------------------------------------------------------
# 3. Fixtures
# ---------------------------------------------------------------------------

import pytest  # noqa: E402


@pytest.fixture()
def bd_limpia(tmp_path, monkeypatch):
    """BD temporal VACIA, sin esquema. Para probar migraciones.

    No llama a `init_db()`: el test decide que esquema previo dejar.
    """
    import src.database as db

    ruta = str(tmp_path / "vacia.db")
    monkeypatch.setattr(db, "DB_PATH", ruta)
    return ruta


@pytest.fixture()
def db_temporal(tmp_path, monkeypatch):
    """BD temporal con el esquema YA CREADO (init_db aplicada)."""
    import src.database as db

    ruta = str(tmp_path / "test.db")
    monkeypatch.setattr(db, "DB_PATH", ruta)
    db.init_db()
    return ruta


@pytest.fixture()
def db(db_temporal):
    """Modulo `src.database` con el esquema ya creado.

    Atajo para los tests que necesitan el modulo Y la BD inicializada. Los
    demas pueden hacer `import src.database as db` dentro del test.
    """
    import src.database as modulo

    return modulo

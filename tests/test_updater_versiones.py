"""
test_updater_versiones.py - El updater puede instalar cualquier version.

El tab Sistema lista versiones nuevas, la instalada y anteriores. El updater
acepta subir o bajar de version, pero un descenso debe ser deliberado: sin
`--permitir-descenso` se rechaza con codigo 7.
"""

import importlib.util
import os

import pytest

RUTA_UPDATER = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "tools",
    "updater.py",
)


@pytest.fixture(scope="module")
def modulo():
    spec = importlib.util.spec_from_file_location(
        "updater_bajo_prueba", RUTA_UPDATER
    )
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def _instalacion(tmp_path, version):
    carpeta = tmp_path / "WTSControl"
    (carpeta / "_internal").mkdir(parents=True)
    (carpeta / "WTSControl.exe").write_text("exe", encoding="utf-8")
    (carpeta / "_internal" / "version.txt").write_text(version, encoding="utf-8")
    return str(carpeta)


class TestComparacion:
    def test_orden_numerico_no_lexicografico(self, modulo):
        assert modulo._cmp_version("1.10.0", "1.9.0") > 0
        assert modulo._cmp_version("1.9.0", "1.10.0") < 0
        assert modulo._cmp_version("1.2.3", "1.2.3") == 0

    def test_es_descenso(self, modulo):
        assert modulo.es_descenso("1.1.19", "1.1.21") is True
        assert modulo.es_descenso("1.1.21", "1.1.21") is False
        assert modulo.es_descenso("1.2.0", "1.1.21") is False

    def test_sin_versiones_no_es_descenso(self, modulo):
        assert modulo.es_descenso("", "1.0.0") is False
        assert modulo.es_descenso("1.0.0", "") is False


def test_leer_version_tolera_bom(tmp_path, modulo):
    carpeta = tmp_path / "app"
    carpeta.mkdir()
    (carpeta / "version.txt").write_bytes(b"\xef\xbb\xbf1.2.3")

    assert modulo.leer_version(str(carpeta)) == "1.2.3"


def test_rechaza_descenso_sin_permiso(tmp_path, modulo):
    instalar = _instalacion(tmp_path, "2.0.0")
    log = tmp_path / "updater.log"

    codigo = modulo.aplicar(
        str(tmp_path / "no-hace-falta.zip"),
        "1.0.0",
        instalar,
        relanzar=False,
        log_path=str(log),
    )

    assert codigo == 7
    assert "permitir-descenso" in log.read_text(encoding="utf-8")


def test_sin_app_en_la_instalacion_falla(tmp_path, modulo):
    log = tmp_path / "updater.log"

    codigo = modulo.aplicar(
        str(tmp_path / "no.zip"),
        "1.0.0",
        str(tmp_path / "vacia"),
        relanzar=False,
        log_path=str(log),
    )

    assert codigo == 1

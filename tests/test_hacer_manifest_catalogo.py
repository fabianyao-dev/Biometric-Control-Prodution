"""
test_hacer_manifest_catalogo.py - El release acumula `releases.json`.

`tools/hacer_manifest.py` ya no publica solo la ultima version: agrega la
entrada al catalogo, reemplaza la de la misma version y lo deja ordenado de
nueva a vieja para que el tab Sistema pueda listar todas.
"""

import importlib.util
import json
import os
import sys

import pytest

RUTA_HACER_MANIFEST = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "tools",
    "hacer_manifest.py",
)


@pytest.fixture(scope="module")
def modulo():
    spec = importlib.util.spec_from_file_location(
        "hacer_manifest_bajo_prueba", RUTA_HACER_MANIFEST
    )
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def _manifest(version, notas="", fecha="2026-01-01 10:00:00"):
    return {
        "version": version,
        "published_at": fecha,
        "notas": notas,
        "zip": {
            "archivo": f"WTSControl-{version}.zip",
            "sha256": f"sha-{version}",
            "size": 123,
        },
    }


def _leer(ruta):
    with open(ruta, "r", encoding="utf-8") as f:
        return json.load(f)


def test_crea_el_catalogo_y_ordena_de_nueva_a_vieja(tmp_path, modulo):
    ruta = tmp_path / "releases.json"

    modulo.actualizar_catalogo(str(ruta), _manifest("1.0.0", "primera"))
    modulo.actualizar_catalogo(str(ruta), _manifest("1.2.0", "tercera"))
    modulo.actualizar_catalogo(str(ruta), _manifest("1.1.0", "segunda"))

    datos = _leer(ruta)
    assert [e["version"] for e in datos["actualizaciones"]] == [
        "1.2.0", "1.1.0", "1.0.0",
    ]
    assert datos["actualizaciones"][0]["notas"] == "tercera"
    assert datos["actualizaciones"][0]["zip"]["archivo"] == "WTSControl-1.2.0.zip"
    assert datos["generado"]


def test_reemplaza_la_entrada_de_la_misma_version(tmp_path, modulo):
    ruta = tmp_path / "releases.json"

    modulo.actualizar_catalogo(str(ruta), _manifest("1.0.0", "notas viejas"))
    modulo.actualizar_catalogo(str(ruta), _manifest("1.0.0", "notas nuevas"))

    datos = _leer(ruta)
    assert len(datos["actualizaciones"]) == 1
    assert datos["actualizaciones"][0]["notas"] == "notas nuevas"


def test_catalogo_corrupto_no_rompe_la_publicacion(tmp_path, modulo):
    ruta = tmp_path / "releases.json"
    ruta.write_text("{ esto no es json", encoding="utf-8")

    modulo.actualizar_catalogo(str(ruta), _manifest("1.0.0", "nueva"))

    datos = _leer(ruta)
    assert [e["version"] for e in datos["actualizaciones"]] == ["1.0.0"]


def test_lee_catalogo_en_formato_lista(tmp_path, modulo):
    ruta = tmp_path / "releases.json"
    ruta.write_text(
        json.dumps([_manifest("1.0.0"), {"sin_version": True}]),
        encoding="utf-8",
    )

    modulo.actualizar_catalogo(str(ruta), _manifest("1.1.0"))

    datos = _leer(ruta)
    assert [e["version"] for e in datos["actualizaciones"]] == ["1.1.0", "1.0.0"]


class TestNotas:
    def test_interpreta_escapes(self, modulo):
        assert modulo.interpretar_escapes("linea1\\nlinea2") == "linea1\nlinea2"
        assert modulo.interpretar_escapes("a\\tb") == "a\tb"
        assert modulo.interpretar_escapes("a\\r\\nb") == "a\nb"

    def test_texto_sin_escapes_no_cambia(self, modulo):
        assert modulo.interpretar_escapes("sin saltos") == "sin saltos"

    def test_main_publica_notas_con_salto_real(self, tmp_path, modulo, monkeypatch):
        build = tmp_path / "build"
        (build / "_internal").mkdir(parents=True)
        (build / "WTSControl.exe").write_text("exe", encoding="utf-8")
        (build / "_internal" / "version.txt").write_text("1.0.0", encoding="utf-8")
        salida = tmp_path / "dist"
        catalogo = tmp_path / "release" / "releases.json"

        monkeypatch.setattr(sys, "argv", [
            "hacer_manifest.py", "1.0.0",
            "--build", str(build),
            "--salida", str(salida),
            "--catalogo", str(catalogo),
            "--notas", "linea1\\nlinea2",
        ])
        modulo.main()

        manifest = _leer(salida / "manifest.json")
        assert manifest["notas"] == "linea1\nlinea2"
        datos = _leer(catalogo)
        assert datos["actualizaciones"][0]["notas"] == "linea1\nlinea2"

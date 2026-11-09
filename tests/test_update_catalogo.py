"""
test_update_catalogo.py - Catalogo de actualizaciones (sin red).

El tab Sistema lista TODAS las versiones publicadas, no solo la ultima. La
logica pura vive en `src/update.py`: normalizar la respuesta del servidor,
ordenar de nueva a vieja y clasificar cada version frente a la instalada.
Tambien se cubre el fallback a `manifest.json` de servidores viejos.
"""

import urllib.error

import pytest

from src import config
from src import update as actualizaciones


def _zip(archivo="WTSControl-1.0.0.zip", sha="abc"):
    return {"archivo": archivo, "sha256": sha, "size": 10}


class TestNormalizar:
    def test_catalogo_con_lista(self):
        datos = {
            "actualizaciones": [
                {
                    "version": "1.2.0",
                    "published_at": "2026-01-01 10:00:00",
                    "notas": "Agrega el listado",
                    "zip": _zip(),
                }
            ]
        }
        lista = actualizaciones.normalizar_actualizaciones(datos)
        assert lista == [{
            "version": "1.2.0",
            "published_at": "2026-01-01 10:00:00",
            "notas": "Agrega el listado",
            "zip": {"archivo": "WTSControl-1.0.0.zip", "sha256": "abc", "size": 10},
        }]

    def test_lista_suelta(self):
        lista = actualizaciones.normalizar_actualizaciones([
            {"version": "1.0.0", "zip": _zip()},
        ])
        assert [e["version"] for e in lista] == ["1.0.0"]

    def test_manifest_suelto_de_servidor_viejo(self):
        lista = actualizaciones.normalizar_actualizaciones({
            "version": "1.0.0",
            "published_at": "ayer",
            "zip": _zip(),
        })
        assert len(lista) == 1
        assert lista[0]["version"] == "1.0.0"

    def test_acepta_comentario_como_alias_de_notas(self):
        lista = actualizaciones.normalizar_actualizaciones([
            {"version": "1.0.0", "comentario": "texto viejo", "zip": _zip()},
        ])
        assert lista[0]["notas"] == "texto viejo"

    def test_descarta_entrada_sin_zip(self):
        lista = actualizaciones.normalizar_actualizaciones([
            {"version": "1.0.0"},
            {"version": "1.1.0", "zip": {"archivo": "x.zip"}},
            {"version": "1.2.0", "zip": _zip()},
        ])
        assert [e["version"] for e in lista] == ["1.2.0"]

    def test_descarta_entrada_sin_version(self):
        assert actualizaciones.normalizar_actualizaciones([
            {"zip": _zip()},
        ]) == []

    def test_respuesta_invalida(self):
        assert actualizaciones.normalizar_actualizaciones(None) == []
        assert actualizaciones.normalizar_actualizaciones("texto") == []


class TestOrden:
    def test_ordena_de_nueva_a_vieja(self):
        lista = actualizaciones.ordenar_actualizaciones([
            {"version": "1.0.9"},
            {"version": "1.10.0"},
            {"version": "1.2.0"},
        ])
        assert [e["version"] for e in lista] == ["1.10.0", "1.2.0", "1.0.9"]

    def test_tolera_partes_no_numericas(self):
        lista = actualizaciones.ordenar_actualizaciones([
            {"version": "1.0.0"},
            {"version": "beta"},
        ])
        assert [e["version"] for e in lista] == ["1.0.0", "beta"]


class TestClasificar:
    def test_nueva(self):
        assert actualizaciones.clasificar_version("1.2.0", "1.1.21") == "nueva"

    def test_instalada(self):
        assert actualizaciones.clasificar_version("1.1.21", "1.1.21") == "instalada"

    def test_anterior(self):
        assert actualizaciones.clasificar_version("1.1.19", "1.1.21") == "anterior"


class TestConsultarCatalogo:
    def test_usa_releases_json(self, monkeypatch):
        monkeypatch.setattr(config, "UPDATE_SOURCE", "http://servidor:8080")
        datos = {"actualizaciones": [
            {"version": "1.0.0", "zip": _zip()},
            {"version": "1.1.0", "zip": _zip()},
        ]}
        monkeypatch.setattr(actualizaciones, "_leer_json", lambda url, timeout=None: datos)

        lista = actualizaciones.consultar_catalogo()

        assert [e["version"] for e in lista] == ["1.1.0", "1.0.0"]

    def test_fallback_a_manifest_si_no_hay_catalogo(self, monkeypatch):
        monkeypatch.setattr(config, "UPDATE_SOURCE", "http://servidor:8080")
        error = urllib.error.HTTPError(
            "http://servidor:8080/releases.json", 404, "Not Found", None, None
        )
        monkeypatch.setattr(
            actualizaciones, "_leer_json",
            lambda url, timeout=None: (_ for _ in ()).throw(error),
        )
        monkeypatch.setattr(
            actualizaciones, "consultar_manifest",
            lambda timeout=None: {"version": "1.0.0", "zip": _zip()},
        )

        lista = actualizaciones.consultar_catalogo()

        assert [e["version"] for e in lista] == ["1.0.0"]

    def test_sin_update_source_falla(self, monkeypatch):
        monkeypatch.setattr(config, "UPDATE_SOURCE", "")
        with pytest.raises(RuntimeError):
            actualizaciones.consultar_catalogo()

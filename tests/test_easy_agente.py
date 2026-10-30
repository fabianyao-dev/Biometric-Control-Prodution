# -*- coding: utf-8 -*-
"""Pruebas unitarias para la integración con el agente Easy."""

import json
from unittest.mock import MagicMock, patch

from src.gui.modulos.corte.easy.agente import _enviar_sincrono


def test_enviar_sincrono_exito():
    fake_conn = MagicMock()
    datos = {"ok": True, "rutina": "buscar_easy", "pasos": 3, "segundos": 1.5}
    respuesta_json = json.dumps(datos).encode("utf-8") + b"\n"
    fake_conn.recv.side_effect = [respuesta_json, b""]

    with patch("socket.create_connection", return_value=fake_conn):
        ok, err = _enviar_sincrono(
            "127.0.0.1", 5000,
            {"rutina": "buscar", "texto": "PARTE-123"}, timeout=5,
        )

    assert ok is True
    assert err is None
    fake_conn.sendall.assert_called_once()
    carga = fake_conn.sendall.call_args[0][0]
    peticion = json.loads(carga.decode("utf-8").strip())
    assert peticion == {"rutina": "buscar", "texto": "PARTE-123"}


def test_enviar_sincrono_error_conexion():
    with patch("socket.create_connection", side_effect=OSError("Host inalcanzable")):
        ok, err = _enviar_sincrono(
            "192.168.1.99", 5000,
            {"rutina": "buscar", "texto": "PARTE-123"}, timeout=5,
        )

    assert ok is False
    assert "no se pudo conectar" in err


def test_enviar_sincrono_respuesta_error():
    fake_conn = MagicMock()
    respuesta_json = json.dumps({"ok": False, "error": "Rutina abortada"}).encode("utf-8") + b"\n"
    fake_conn.recv.side_effect = [respuesta_json, b""]

    with patch("socket.create_connection", return_value=fake_conn):
        ok, err = _enviar_sincrono(
            "127.0.0.1", 5000,
            {"rutina": "buscar", "texto": "PARTE-123"}, timeout=5,
        )

    assert ok is False
    assert err == "Easy: Rutina abortada"


def test_enviar_sincrono_no_json():
    fake_conn = MagicMock()
    fake_conn.recv.side_effect = [b"RESPUESTA_INVALIDA\n", b""]

    with patch("socket.create_connection", return_value=fake_conn):
        ok, err = _enviar_sincrono(
            "127.0.0.1", 5000,
            {"rutina": "buscar", "texto": "PARTE-123"}, timeout=5,
        )

    assert ok is False
    assert "no es JSON" in err


# (sin soporte legacy: enviar_numero_parte eliminado)

import os
import sys

from src import config
from src.hardware.biometric_sdk import obtener_sdk

sys.stdout.reconfigure(encoding="utf-8")

if os.name == "nt":
    import winsound

    def emitir_beep(freq=2000, duration=200):
        winsound.Beep(freq, duration)
else:
    def emitir_beep(freq=2000, duration=200):
        try:
            print("\a", end="", flush=True)
        except Exception:
            pass


class BiometricService:
    """Capa de alto nivel: captura de huella y comparación biométrica."""

    def __init__(self):
        self.sdk = obtener_sdk()

    def abrir(self):
        return self.sdk.abrir_lector()

    def capturar_huella(self, timeout_ms=None):
        """Captura la huella y extrae su FMD.

        Devuelve un dict con 'fmd', 'width', 'height', 'dpi' o None.
        """
        timeout_ms = timeout_ms or config.CAPTURE_TIMEOUT_MS
        try:
            emitir_beep(1200, 200)
        except Exception:
            pass

        captura = self.sdk.capturar_imagen(
            timeout_ms=timeout_ms,
            buffer_size=config.CAPTURE_BUFFER_SIZE,
        )
        if not captura:
            return None

        fmd = self.sdk.extraer_fmd(
            captura["image"],
            captura["width"],
            captura["height"],
            captura["dpi"],
        )
        if not fmd:
            return None

        return {
            "fmd": fmd,
            "width": captura["width"],
            "height": captura["height"],
            "dpi": captura["dpi"],
        }

    def comparar(self, fmd_a, fmd_b):
        return self.sdk.comparar(fmd_a, fmd_b)

    def identificar(self, fmd, lista_fmds, umbral=None):
        """Identifica un FMD contra una lista. Devuelve (indice, score) si hay
        candidato con score <= umbral, o None si no coincide."""
        umbral = config.UMBRAL_DISIMILARIDAD if umbral is None else umbral
        resultado = self.sdk.identificar(fmd, lista_fmds)
        if not resultado:
            return None
        idx, score = resultado
        if score > umbral:
            return None
        return (idx, score)

    def cerrar(self):
        self.sdk.cerrar()

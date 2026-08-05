import os
import platform
import subprocess
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
    """Capa de alto nivel de captura/comparación biométrica.

    Multiplataforma:
    - Windows: usa el SDK DigitalPersona (dpfpdd.dll + dpfj.dll) vía ctypes.
    - Linux / Raspberry Pi: usa el servicio nativo fprintd (fprintd-verify).
    """

    def __init__(self):
        self.is_windows = platform.system() == "Windows"
        if self.is_windows:
            self.sdk = obtener_sdk()
        else:
            self.sdk = None

    def abrir(self):
        """Prepara el lector. Devuelve True si está listo."""
        if self.is_windows:
            return self.sdk.abrir_lector()
        return True

    def capturar_huella(self, timeout_ms=None):
        """Captura la huella y devuelve el resultado de la captura.

        Windows: dict con 'fmd', 'width', 'height', 'dpi' o None.
        Linux:   dict con 'status' ('SUCCESS'/'NO_MATCH'/'ERROR'), 'user' y 'message'.
        """
        if self.is_windows:
            return self._capturar_windows(timeout_ms)
        return self._capturar_linux()

    def _capturar_windows(self, timeout_ms=None):
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

    def _capturar_linux(self):
        """Verifica la huella del usuario actual mediante fprintd."""
        try:
            try:
                emitir_beep(1200, 200)
            except Exception:
                pass

            res = subprocess.run(
                ["fprintd-verify"],
                capture_output=True,
                text=True,
                timeout=config.FPRINTD_TIMEOUT_S,
            )
            if "verify-match" in res.stdout or res.returncode == 0:
                return {"status": "SUCCESS", "user": None, "message": res.stdout.strip()}
            return {"status": "NO_MATCH", "user": None, "message": res.stdout.strip()}
        except subprocess.TimeoutExpired:
            return {"status": "TIMEOUT", "user": None, "message": "Tiempo agotado en fprintd."}
        except FileNotFoundError:
            return {"status": "ERROR", "user": None, "message": "fprintd-verify no está instalado."}
        except Exception as e:
            return {"status": "ERROR", "user": None, "message": str(e)}

    def comparar(self, fmd_a, fmd_b):
        if self.is_windows:
            return self.sdk.comparar(fmd_a, fmd_b)
        raise NotImplementedError("comparar solo está disponible en Windows.")

    def identificar(self, fmd, lista_fmds, umbral=None):
        """Identifica un FMD contra una lista. Devuelve (indice, score) si hay
        candidato con score <= umbral, o None si no coincide."""
        if not self.is_windows:
            raise NotImplementedError("identificar solo está disponible en Windows.")
        umbral = config.UMBRAL_DISIMILARIDAD if umbral is None else umbral
        resultado = self.sdk.identificar(fmd, lista_fmds)
        if not resultado:
            return None
        idx, score = resultado
        if score > umbral:
            return None
        return (idx, score)

    def cerrar(self):
        if self.is_windows:
            self.sdk.cerrar()

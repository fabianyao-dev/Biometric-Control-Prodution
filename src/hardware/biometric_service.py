import json
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


RUTA_HELPER = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "bin", "fp_helper"
)


def _helper_disponible():
    return os.path.isfile(RUTA_HELPER) and os.access(RUTA_HELPER, os.X_OK)


class BiometricService:
    """Capa de alto nivel de captura/comparación biométrica.

    Modos:
    - windows: SDK DigitalPersona (dpfpdd.dll + dpfj.dll) vía ctypes.
    - libfprint: helper C (fp_helper) sobre libfprint 2 en la Raspberry Pi.
      Enrola plantillas serializables y hace identificación 1:N en el lector.
    - fprintd: fallback con fprintd-verify (solo verifica el usuario del
      sistema, sin plantillas; no sirve para identificar operadores).
    """

    def __init__(self):
        self.is_windows = platform.system() == "Windows"
        if self.is_windows:
            self.sdk = obtener_sdk()
            self.modo = "windows"
        elif _helper_disponible():
            self.sdk = None
            self.modo = "libfprint"
        else:
            self.sdk = None
            self.modo = "fprintd"

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

    def enrollar(self, timeout_ms=None, on_progress=None):
        """Enrola una huella y devuelve dict con 'fmd' (bytes de la plantilla).

        - Windows: captura única (misma API que capturar_huella).
        - libfprint: enrolamiento multipasada vía helper C con progreso.
        - fprintd: verificación sin plantilla (status SUCCESS/NO_MATCH/ERROR).
        """
        if self.is_windows:
            return self.capturar_huella(timeout_ms)
        if self.modo == "libfprint":
            return self._enrollar_libfprint(on_progress)
        return self._capturar_linux()

    def _enrollar_libfprint(self, on_progress=None):
        try:
            proc = subprocess.Popen(
                [RUTA_HELPER, "enroll"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            ultimo = None
            for linea in proc.stdout:
                linea = linea.strip()
                if not linea:
                    continue
                try:
                    ev = json.loads(linea)
                except ValueError:
                    continue
                estado = ev.get("status")
                if estado == "stage":
                    if on_progress:
                        on_progress(ev.get("stage", 0), ev.get("n", 0))
                elif estado in ("complete", "error"):
                    ultimo = ev
            proc.wait()

            if ultimo is None:
                return {"status": "ERROR", "message": "Respuesta vacía del helper."}
            if ultimo.get("status") == "complete":
                data = bytes.fromhex(ultimo["data"])
                return {"fmd": data, "size": len(data)}
            return {
                "status": "ERROR",
                "message": ultimo.get("message", "Error de enrolamiento."),
            }
        except FileNotFoundError:
            return {"status": "ERROR", "message": "Helper libfprint no está compilado."}
        except Exception as e:
            return {"status": "ERROR", "message": str(e)}

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

    def identificar_en_lector(self, lista_plantillas, timeout_ms=None, on_progress=None):
        """Captura una huella y la identifica contra las plantillas dadas.

        - Windows: captura única y compara FMDs -> (indice, score) o None.
        - libfprint: captura + coincidencia 1:N en el lector -> (indice, 0) o None.
        - fprintd: no puede identificar operadores; lanza RuntimeError.
        """
        if self.is_windows:
            captura = self.capturar_huella(timeout_ms)
            if not captura or not captura.get("fmd"):
                raise RuntimeError("Captura sin plantilla.")
            return self.identificar(captura["fmd"], lista_plantillas)
        if self.modo == "libfprint":
            return self._identificar_libfprint(lista_plantillas, on_progress)
        raise RuntimeError(
            "fprintd no puede identificar operadores; compila el helper libfprint."
        )

    def _identificar_libfprint(self, lista_plantillas, on_progress=None):
        if not lista_plantillas:
            return None
        try:
            hex_galeria = "".join(p.hex() + "\n" for p in lista_plantillas)
            proc = subprocess.Popen(
                [RUTA_HELPER, "identify"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            proc.stdin.write(hex_galeria)
            proc.stdin.close()

            resultado = None
            for linea in proc.stdout:
                linea = linea.strip()
                if not linea:
                    continue
                try:
                    ev = json.loads(linea)
                except ValueError:
                    continue
                estado = ev.get("status")
                if estado == "retry":
                    if on_progress:
                        on_progress(ev.get("attempt", 0), None)
                elif estado == "match":
                    resultado = (ev.get("index", 0), 0)
                elif estado == "nomatch":
                    resultado = None
                elif estado == "error":
                    raise RuntimeError(ev.get("message", "Error de identificación."))
            proc.wait()
            return resultado
        except FileNotFoundError:
            raise RuntimeError("Helper libfprint no está compilado.")
        except RuntimeError:
            raise
        except Exception as e:
            raise RuntimeError(str(e))

    def cerrar(self):
        if self.is_windows:
            self.sdk.cerrar()

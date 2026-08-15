import logging
import sys
import threading

from src import config
from src.hardware.biometric_sdk import obtener_sdk

log = logging.getLogger(__name__)

# En un .exe PyInstaller sin consola `sys.stdout` es None; proteger el
# reconfigure para no crashear al importar.
if sys.stdout is not None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass

import winsound


def emitir_beep(freq=2000, duration=200):
    winsound.Beep(freq, duration)


class BiometricService:
    """Capa de alto nivel de captura/comparación biométrica (Windows).

    Usa el SDK de DigitalPersona (dpfpdd.dll + dpfj.dll) vía ctypes.
    """

    def __init__(self):
        self.sdk = obtener_sdk()
        self._lock_lector = threading.Lock()

    @property
    def disponible(self):
        """True si los DLLs de DigitalPersona se cargaron y la biometria puede
        usarse. En una maquina sin el driver (o en dev sin lector) es False y
        la app sigue corriendo, pero las capturas devuelven None/mensaje."""
        return self.sdk.disponible

    def abrir(self):
        """Prepara el lector. Devuelve True si está listo."""
        return self.sdk.abrir_lector()

    def capturar_huella(self, timeout_ms=None):
        """Captura la huella y devuelve dict con 'fmd', 'width', 'height' y
        'dpi', o None si no se capturó nada."""
        return self._capturar_windows(timeout_ms)

    def enrollar(self, timeout_ms=None, on_progress=None):
        """Enrola una huella y devuelve dict con 'fmd' (plantilla).

        En Windows es una captura única (misma API que capturar_huella);
        on_progress se ignora en esta plataforma.
        """
        return self.capturar_huella(timeout_ms)

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

    def identificar_en_lector(self, lista_plantillas, timeout_ms=None, on_progress=None):
        """Captura una huella y la identifica contra las plantillas dadas.

        Windows: captura única y compara FMDs -> (indice, score) o None.
        """
        captura = self.capturar_huella(timeout_ms)
        if not captura or not captura.get("fmd"):
            raise RuntimeError("Captura sin plantilla.")
        return self.identificar(captura["fmd"], lista_plantillas)

    def autenticar_operador(self, on_progress=None):
        """Captura una huella y devuelve (id_operador, nombre) o None.

        Consulta los operadores activos y usa identificar_en_lector(). Util
        para el login y para autorizar la reanudacion de un paro. El
        threading.Lock garantiza que solo haya una captura a la vez, ya que
        el lector es un recurso compartido; al arrancar cada captura avisa
        al lector con un beep para que el operador sepa que debe apoyar
        el dedo.
        """
        from src.database import listar_fmds, obtener_operador_temporal

        filas = listar_fmds(activos_solo=True)
        if not filas:
            # Sin usuarios reales: acceso automatico (modo desarrollo).
            if on_progress:
                on_progress("Sin operadores registrados; acceso automatico.")
            return obtener_operador_temporal()
        if not self.disponible:
            # Driver DigitalPersona ausente (maquina sin el SDK instalado).
            raise RuntimeError(
                "Driver de DigitalPersona no instalado. La biometria no esta "
                "disponible en este equipo."
            )
        plantillas = [fila[2] for fila in filas]
        with self._lock_lector:
            if on_progress:
                on_progress("Coloca el dedo en el lector...")
            emitir_beep()
            resultado = self.identificar_en_lector(plantillas, on_progress=on_progress)
        if not resultado:
            return None
        idx = resultado[0]
        if not (0 <= idx < len(filas)):
            return None
        return filas[idx][0], filas[idx][1]

    def cerrar(self):
        self.sdk.cerrar()

import logging
import sys
import threading

from src import config
from src.domain.biometria import elegir_candidato
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
        # RLock: autenticar_operador ya retiene el lock y llama a metodos que
        # tambien lo toman (capturar_huella, identificar...). Un Lock normal
        # haria deadlock.
        self._lock_lector = threading.RLock()

    @property
    def disponible(self):
        """True si los DLLs de DigitalPersona se cargaron y la biometria puede
        usarse. En una maquina sin el driver (o en dev sin lector) es False y
        la app sigue corriendo, pero las capturas devuelven None/mensaje."""
        return self.sdk.disponible

    def lector_presente(self):
        """True si el lector fisico esta conectado y detectado por el SDK.

        Complementa a `disponible`: los DLLs pueden cargar (driver instalado)
        y aun asi el lector estar desconectado del USB. Barato de consultar.
        """
        return self.sdk.lector_presente()

    def abrir(self):
        """Prepara el lector. Devuelve True si está listo."""
        with self._lock_lector:
            return self.sdk.abrir_lector()

    def reiniciar_lector(self) -> bool:
        """Reboot por software del lector (cierra handle stale, reinicia
        dpfpdd, re-enumera y reabre). Devuelve True si quedo listo."""
        if not self.disponible:
            return False
        try:
            with self._lock_lector:
                return bool(self.sdk.reiniciar_lector())
        except Exception:  # noqa: BLE001 - nunca debe crashear la UI
            log.error("reiniciar_lector fallo", exc_info=True)
            return False

    def capturar_huella(self, timeout_ms=None):
        """Captura la huella y devuelve dict con 'fmd', 'width', 'height' y
        'dpi', o None si no se capturó nada."""
        with self._lock_lector:
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
        with self._lock_lector:
            return self.sdk.comparar(fmd_a, fmd_b)

    def identificar(self, fmd, lista_fmds, umbral=None, ids=None):
        """Identifica un FMD contra una lista. Devuelve (indice, score) si hay
        un candidato inequivoco con score <= umbral, o None si no coincide o
        si dos operadores quedan demasiado cerca (ambiguedad).

        `ids` mapea cada indice de plantilla a su operador; si se omite, cada
        plantilla se trata como un operador distinto.
        """
        if not lista_fmds:
            return None
        umbral = config.UMBRAL_DISIMILARIDAD if umbral is None else umbral
        ids = list(range(len(lista_fmds))) if ids is None else list(ids)
        if len(ids) != len(lista_fmds):
            log.error(
                "identificar: %d plantillas pero %d ids de operador.",
                len(lista_fmds),
                len(ids),
            )
            return None
        with self._lock_lector:
            candidatos = self.sdk.identificar_candidatos(
                fmd,
                lista_fmds,
                umbral=umbral,
                max_candidatos=2,
            )
        return self._decidir_candidato(candidatos, ids, umbral)

    def _decidir_candidato(self, candidatos, ids, umbral):
        resultado = elegir_candidato(
            candidatos,
            ids,
            umbral,
            config.MARGEN_AMBIGUEDAD,
        )
        if resultado is None and candidatos:
            log.warning(
                "Identificacion sin candidato inequivoco: %d candidato(s) "
                "dentro del umbral %d (posible ambiguedad).",
                len(candidatos),
                umbral,
            )
        return resultado

    def identificar_en_lector(
        self,
        lista_plantillas,
        timeout_ms=None,
        on_progress=None,
        ids=None,
    ):
        """Captura una huella y la identifica contra las plantillas dadas.

        Windows: captura única y compara FMDs -> (indice, score) o None.
        """
        captura = self.capturar_huella(timeout_ms)
        if not captura or not captura.get("fmd"):
            raise RuntimeError(
                getattr(self.sdk, "ultimo_error_captura", "")
                or "No se pudo capturar la huella."
            )
        return self.identificar(captura["fmd"], lista_plantillas, ids=ids)

    def autenticar_operador(self, on_progress=None):
        """Captura una huella y devuelve (id_operador, nombre) o None.

        Consulta los operadores activos y usa identificar_en_lector(). Util
        para el login y para autorizar la reanudacion de un paro. El
        threading.RLock garantiza que solo haya una captura a la vez, ya que
        el lector es un recurso compartido; al arrancar cada captura avisa
        al lector con un beep para que el operador sepa que debe apoyar
        el dedo.
        """
        from src.database import (
            OPERADOR_TEMPORAL_NOMBRE,
            listar_fmds,
            listar_operadores_admin,
            obtener_operador_temporal,
        )

        # Modo DESARROLLO sin lector: entra directo con el operador temporal,
        # sin intentar usar el lector.
        if config.MODO_DEV:
            if on_progress:
                on_progress("Modo desarrollo sin lector; acceso como DEV.")
            return obtener_operador_temporal()

        filas = listar_fmds(activos_solo=True)
        if not filas:
            # El operador temporal interno no cuenta: si es lo unico que
            # queda activo, se permite rehacer el alta (evita lockout).
            activos = [
                op
                for op in listar_operadores_admin()
                if op["activo"] and op["nombre"] != OPERADOR_TEMPORAL_NOMBRE
            ]
            if not activos:
                # Primera instalacion: sin operadores no hay con que
                # autenticarse. Se deja crear el primer administrador.
                log.warning(
                    "Sin operadores reales registrados: acceso automatico de "
                    "primera instalacion. Registra un administrador con "
                    "huella cuanto antes."
                )
                if on_progress:
                    on_progress(
                        "Sin operadores registrados; acceso automatico de "
                        "primera instalacion."
                    )
                return obtener_operador_temporal()
            # Hay operadores pero ninguno tiene huella: NO se regala acceso
            # (seria una puerta trasera en produccion).
            raise RuntimeError(
                "Hay operadores activos sin huellas registradas. Registra "
                "una huella desde Administracion antes de iniciar sesion."
            )
        if not self.disponible:
            # Driver DigitalPersona ausente (maquina sin el SDK instalado).
            raise RuntimeError(
                "Driver de DigitalPersona no instalado. La biometria no esta "
                "disponible en este equipo."
            )
        plantillas = [fila[2] for fila in filas]
        ids = [fila[0] for fila in filas]
        with self._lock_lector:
            if on_progress:
                on_progress("Coloca el dedo en el lector...")
            emitir_beep()
            resultado = self.identificar_en_lector(
                plantillas,
                on_progress=on_progress,
                ids=ids,
            )
        if not resultado:
            return None
        idx = resultado[0]
        if not (0 <= idx < len(filas)):
            return None
        return filas[idx][0], filas[idx][1]

    def cerrar(self):
        self.sdk.cerrar()

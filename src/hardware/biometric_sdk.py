import ctypes
import logging
import os
import struct
import sys
import time
import winreg

log = logging.getLogger(__name__)

# Device drivers del DDK: dpfpdd.dll los carga POR NOMBRE al enumerar. Si en
# el sistema hay versiones distintas (driver MSI instalado, SDK, Windows
# Update) o no las encuentra, query_devices devuelve 0 aunque el lector este
# visible en Administrador de dispositivos. Se precargan desde _internal.
DDK_DEVICE_DRIVERS = (
    "dpfpdd5000.dll",
    "dpfpdd_4k.dll",
    "dpfpdd7k.dll",
    "dpfpdd_ptapi.dll",
)

MAX_DEVICE_NAME_LENGTH = 1024
MAX_STR_LENGTH = 128
MAX_FMD_SIZE = 26 + 4 + 255 * 6 + 2

DPFPDD_E_MORE_DATA = 0x0d | (0x05BA << 16)

DPFJ_SUCCESS = 0
DPFJ_E_MORE_DATA = 0x0d | (0x05BA << 16)
DPFJ_PROBABILITY_ONE = 0x7FFFFFFF
DPFJ_FMD_ANSI_378_2004 = 0x001B0001
DPFJ_FMD_ISO_19794_2_2005 = 0x01010001
DPFJ_POSITION_UNKNOWN = 0

DPFPDD_IMG_FMT_PIXEL_BUFFER = 0
DPFPDD_IMG_PROC_DEFAULT = 0

# OJO: el puente WBF del SDK reporta VID 0x05BA y nombre interno
# "$00$05ba&..." para TODOS los sensores que enumera via Windows Biometric
# Framework — incluidos los integrados de la PC (p. ej. Broadcom ControlVault,
# cuyo VID USB real es 0x0A5C). El VID NO distingue un lector DigitalPersona
# real de un sensor integrado: el filtro se hace por producto/fabricante.
NOMBRES_LECTOR_DP = ("u.are.u", "uareu", "digital persona", "digitalpersona")


def _es_lector_digitalpersona(info):
    """True si el dispositivo enumerado es un lector DigitalPersona/HID.

    El SDK tambien enumera por WBF sensores integrados de la computadora
    (p. ej. el lector de la laptop de desarrollo), que NO estan soportados.
    Decide por producto/fabricante: 'U.are.U(R) 4500 Fingerprint Reader'
    pasa; 'Control Vault w/ Fingerprint Touch Sensor' (Broadcom) no.
    """
    producto = info.descr.product_name.decode("utf-8", errors="ignore").lower()
    fabricante = info.descr.vendor_name.decode("utf-8", errors="ignore").lower()
    texto = f"{producto} {fabricante}"
    return any(p in texto for p in NOMBRES_LECTOR_DP)


def _nombre_dispositivo(info):
    """Etiqueta legible de un dispositivo enumerado (para logs)."""
    return (
        info.descr.product_name.decode("utf-8", errors="ignore").strip()
        or info.name.decode("utf-8", errors="ignore").strip()
        or "(sin nombre)"
    )


class DPFPDD_VER_INFO(ctypes.Structure):
    _fields_ = [
        ("major", ctypes.c_int),
        ("minor", ctypes.c_int),
        ("maintenance", ctypes.c_int),
    ]


class DPFPDD_HW_DESCR(ctypes.Structure):
    _fields_ = [
        ("vendor_name", ctypes.c_char * MAX_STR_LENGTH),
        ("product_name", ctypes.c_char * MAX_STR_LENGTH),
        ("serial_num", ctypes.c_char * MAX_STR_LENGTH),
    ]


class DPFPDD_HW_ID(ctypes.Structure):
    _fields_ = [
        ("vendor_id", ctypes.c_ushort),
        ("product_id", ctypes.c_ushort),
    ]


class DPFPDD_HW_VERSION(ctypes.Structure):
    _fields_ = [
        ("hw_ver", DPFPDD_VER_INFO),
        ("fw_ver", DPFPDD_VER_INFO),
        ("bcd_rev", ctypes.c_ushort),
    ]


class DPFPDD_DEV_INFO(ctypes.Structure):
    _fields_ = [
        ("size", ctypes.c_uint),
        ("name", ctypes.c_char * MAX_DEVICE_NAME_LENGTH),
        ("descr", DPFPDD_HW_DESCR),
        ("id", DPFPDD_HW_ID),
        ("ver", DPFPDD_HW_VERSION),
        ("modality", ctypes.c_uint),
        ("technology", ctypes.c_uint),
    ]


class DPFPDD_CAPTURE_PARAM(ctypes.Structure):
    _fields_ = [
        ("size", ctypes.c_uint),
        ("image_fmt", ctypes.c_uint),
        ("image_proc", ctypes.c_uint),
        ("image_res", ctypes.c_uint),
    ]


class DPFPDD_IMAGE_INFO(ctypes.Structure):
    _fields_ = [
        ("size", ctypes.c_uint),
        ("width", ctypes.c_uint),
        ("height", ctypes.c_uint),
        ("res", ctypes.c_uint),
        ("bpp", ctypes.c_uint),
    ]


class DPFPDD_CAPTURE_RESULT(ctypes.Structure):
    _fields_ = [
        ("size", ctypes.c_uint),
        ("success", ctypes.c_int),
        ("quality", ctypes.c_uint),
        ("score", ctypes.c_uint),
        ("info", DPFPDD_IMAGE_INFO),
    ]


class DPFPDD_DEV_CAPS(ctypes.Structure):
    _fields_ = [
        ("size", ctypes.c_uint),
        ("can_capture_image", ctypes.c_int),
        ("can_stream_image", ctypes.c_int),
        ("can_extract_features", ctypes.c_int),
        ("can_match", ctypes.c_int),
        ("can_identify", ctypes.c_int),
        ("has_fp_storage", ctypes.c_int),
        ("indicator_type", ctypes.c_uint),
        ("has_pwr_mgmt", ctypes.c_int),
        ("has_calibration", ctypes.c_int),
        ("piv_compliant", ctypes.c_int),
        ("resolution_cnt", ctypes.c_uint),
        ("resolutions", ctypes.c_uint * 1),
    ]


class DPFJ_CANDIDATE(ctypes.Structure):
    _fields_ = [
        ("size", ctypes.c_uint),
        ("fmd_idx", ctypes.c_uint),
        ("view_idx", ctypes.c_uint),
    ]


def _version_dll(ruta):
    """Devuelve la version del archivo (major.minor.build.rev) o None."""
    try:
        size = ctypes.windll.version.GetFileVersionInfoSizeW(ruta, None)
        if size <= 0:
            return None
        buf = ctypes.create_string_buffer(size)
        if not ctypes.windll.version.GetFileVersionInfoW(ruta, 0, size, buf):
            return None
        ptr = ctypes.c_void_p()
        n = ctypes.c_uint()
        if not ctypes.windll.version.VerQueryValueW(
            buf, "\\", ctypes.byref(ptr), ctypes.byref(n)
        ):
            return None
        # VS_FIXEDFILEINFO: dwFileVersionMS en offset 8, dwFileVersionLS en 12.
        datos = ctypes.string_at(ptr, n.value)
        ms = struct.unpack_from("<I", datos, 8)[0]
        ls = struct.unpack_from("<I", datos, 12)[0]
        return "%d.%d.%d.%d" % (
            (ms >> 16) & 0xFFFF,
            ms & 0xFFFF,
            (ls >> 16) & 0xFFFF,
            ls & 0xFFFF,
        )
    except Exception as e:  # noqa: BLE001
        log.debug("No se pudo leer version de %s: %s", ruta, e)
        return None


class BiometricSDK:
    """Wrapper de bajo nivel (ctypes) de dpfpdd.dll y dpfj.dll."""

    def __init__(self):
        self.dpfpdd = None
        self.dpfj = None
        self.h_reader = None
        self._tiempo_captura_s = 0.0
        # Ultimo motivo de fallo de captura (para mensajes al operador).
        self.ultimo_error_captura = ""
        # Estado de enumeracion previo: el polling periodico (indicador de
        # advertencias) consulta el lector cada pocos segundos y loggearlo
        # siempre inunda los logs; solo se registra cuando cambia.
        self._firma_lectores = None
        # El diagnostico de registro/PnP se muestra UNA vez por episodio de
        # ausencia del lector (se resetea al detectarlo de nuevo).
        self._diag_mostrado = False
        self._cargar_dpfpdd()
        self._cargar_dpfj()

    def _ruta_dll(self, nombre):
        """Ruta completa a un DLL de DigitalPersona.

        En desarrollo se carga por nombre (System32 / PATH, SDK instalado en
        el sistema). Empaquetado con PyInstaller onedir, los DLLs viven en
        `_internal` (`sys._MEIPASS`) y NO estan en el buscador por defecto,
        asi que se carga la ruta absoluta y se registra su carpeta para que
        las dependencias entre DLLs (dpfpdd -> dpfpdd5000, dpdevctlx64, ...)
        tambien se resuelvan.
        """
        frozen = getattr(sys, "frozen", False)
        if frozen:
            base = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
            ruta = os.path.join(base, nombre)
            log.info(
                "biometrico empaquetado (frozen): buscando %s en %s (existe=%s)",
                nombre, base, os.path.exists(ruta),
            )
            if os.path.exists(ruta):
                try:
                    os.add_dll_directory(base)
                except (OSError, AttributeError) as e:
                    log.warning("os.add_dll_directory(%s) fallo: %s", base, e)
                return ruta
            log.warning("DLL %s NO existe en %s; se intenta carga por nombre.", nombre, base)
        else:
            log.debug("biometrico en desarrollo: %s por nombre (System32/PATH).", nombre)
        return nombre

    @property
    def disponible(self):
        """True si los DLLs de DigitalPersona se cargaron correctamente."""
        return self.dpfpdd is not None and self.dpfj is not None

    def lector_presente(self):
        """True si hay al menos un lector DIGITALPERSONA conectado y detectado.

        Distinto de `disponible`: aqui no importa que los DLLs carguen, se
        enumera el hardware real (dpfpdd_query_devices). No abre el lector,
        asi que es barato para consultarlo periodicamente. Filtra por
        DigitalPersona: un sensor integrado (WBF) de la PC no cuenta.
        """
        return any(
            _es_lector_digitalpersona(info)
            for info in self._enumerar_lectores()
        )

    def _log_cambio_lectores(self, dispositivos):
        """Loggea la lista de dispositivos SOLO cuando cambia.

        El estado se consulta periodicamente (indicador de advertencias,
        reintento de capturas); repetirlo en cada consulta vuelve ilegible
        el log durante la depuracion del hot-plug.
        """
        firma = [
            (_nombre_dispositivo(d), int(d.id.vendor_id)) for d in dispositivos
        ]
        if firma == self._firma_lectores:
            return
        self._firma_lectores = firma
        detalle = ", ".join(f"{n} (VID {hex(v)})" for n, v in firma)
        log.info("SDK enumera %d dispositivo(s) biometrico(s): %s",
                 len(firma), detalle or "ninguno")

    def _enumerar_lectores(self):
        """Enumera los dispositivos que reporta dpfpdd_query_devices.

        Devuelve una lista de DPFPDD_DEV_INFO (posiblemente vacia). No abre
        ningun lector ni crashea si el SDK no esta disponible. Los cambios de
        deteccion se loguean a INFO; las consultas sin cambio, a DEBUG.
        """
        if not self.dpfpdd:
            return []
        capacidad = 4
        for _ in range(3):  # 1 consulta + hasta 2 crecimientos del buffer
            lista = (DPFPDD_DEV_INFO * capacidad)()
            for i in range(capacidad):
                lista[i].size = ctypes.sizeof(DPFPDD_DEV_INFO)
            cnt = ctypes.c_uint(capacidad)
            try:
                res = self.dpfpdd.dpfpdd_query_devices(
                    ctypes.byref(cnt),
                    ctypes.cast(lista, ctypes.POINTER(DPFPDD_DEV_INFO)),
                )
            except Exception:  # noqa: BLE001 - nunca debe crashear la UI
                log.error("dpfpdd_query_devices fallo al enumerar",
                          exc_info=True)
                return []
            if res != 0 and res != DPFPDD_E_MORE_DATA:
                log.warning("dpfpdd_query_devices fallo (res=%s)", hex(res))
                return []
            if cnt.value == 0:
                dispositivos = []
            elif res == 0 or cnt.value <= capacidad:
                dispositivos = list(lista[: min(cnt.value, capacidad)])
            else:
                # E_MORE_DATA: buffer insuficiente; reintentar con el tamano.
                capacidad = int(cnt.value)
                continue
            self._log_cambio_lectores(dispositivos)
            log.debug("dpfpdd_query_devices -> res=%s, devices=%d",
                      hex(res), cnt.value)
            return dispositivos
        return []

    def _cargar_dpfpdd(self):
        ruta = self._ruta_dll("dpfpdd.dll")
        try:
            self.dpfpdd = ctypes.WinDLL(ruta)
            log.info("dpfpdd.dll cargada desde %s (version=%s)",
                     ruta, _version_dll(ruta))
        except OSError as e:
            log.error("No se pudo cargar dpfpdd.dll (%s): %s", ruta, e, exc_info=True)
            self.dpfpdd = None
            return

        self.dpfpdd.dpfpdd_init.restype = ctypes.c_int
        self.dpfpdd.dpfpdd_init.argtypes = []

        self.dpfpdd.dpfpdd_exit.restype = ctypes.c_int
        self.dpfpdd.dpfpdd_exit.argtypes = []

        self.dpfpdd.dpfpdd_query_devices.restype = ctypes.c_int
        self.dpfpdd.dpfpdd_query_devices.argtypes = [
            ctypes.POINTER(ctypes.c_uint),
            ctypes.POINTER(DPFPDD_DEV_INFO),
        ]

        self.dpfpdd.dpfpdd_open.restype = ctypes.c_int
        self.dpfpdd.dpfpdd_open.argtypes = [
            ctypes.c_char_p,
            ctypes.POINTER(ctypes.c_void_p),
        ]

        self.dpfpdd.dpfpdd_close.restype = ctypes.c_int
        self.dpfpdd.dpfpdd_close.argtypes = [ctypes.c_void_p]

        self.dpfpdd.dpfpdd_capture.restype = ctypes.c_int
        self.dpfpdd.dpfpdd_capture.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(DPFPDD_CAPTURE_PARAM),
            ctypes.c_uint,
            ctypes.POINTER(DPFPDD_CAPTURE_RESULT),
            ctypes.POINTER(ctypes.c_uint),
            ctypes.POINTER(ctypes.c_ubyte),
        ]

        self.dpfpdd.dpfpdd_get_device_capabilities.restype = ctypes.c_int
        self.dpfpdd.dpfpdd_get_device_capabilities.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(DPFPDD_DEV_CAPS),
        ]

        res_init = self.dpfpdd.dpfpdd_init()
        log.info("dpfpdd_init -> res=%s", hex(res_init) if res_init else "0x0")

        # Precargar los device drivers del DDK desde _internal para que
        # dpfpdd.dll NO tome versiones del sistema (System32/registro) que
        # pueden no coincidir con las empaquetadas (SDK 3.2.0.89).
        self._precargar_drivers_ddk()

    def _precargar_drivers_ddk(self):
        """Carga por ruta absoluta los device drivers del DDK (dpfpdd*.dll).

        dpfpdd.dll los carga por nombre al enumerar lectores; si ya estan
        cargados en el proceso usa estos, evitando conflictos de version.
        """
        base = None
        if getattr(sys, "frozen", False):
            base = getattr(sys, "_MEIPASS", None) or os.path.dirname(sys.executable)
        for nombre in DDK_DEVICE_DRIVERS:
            ruta = os.path.join(base, nombre) if base else nombre
            if base and not os.path.exists(ruta):
                log.warning("Device driver %s NO existe en %s", nombre, base)
                continue
            try:
                ctypes.WinDLL(ruta)
                log.info("Device driver %s cargado desde %s (version=%s)",
                         nombre, ruta, _version_dll(ruta))
            except OSError as e:
                log.error("No se pudo cargar device driver %s (%s): %s",
                          nombre, ruta, e, exc_info=True)

    def _diagnostico_lectores(self):
        """Log de estado del registro de DigitalPersona y del dispositivo USB
        cuando query_devices devuelve 0. Permite distinguir si el lector esta
        vinculado al driver legacy (usbdpfp) o al WBF (Windows Hello)."""
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                                r"SOFTWARE\DigitalPersona\Driver") as k:
                claves = []
                i = 0
                while True:
                    try:
                        claves.append(winreg.EnumKey(k, i))
                        i += 1
                    except OSError:
                        break
                log.info("Diagnostico: HKLM\\SOFTWARE\\DigitalPersona\\Driver "
                         "subclaves = %s", claves or ["(ninguna)"])
        except OSError as e:
            log.warning("Diagnostico: sin clave DigitalPersona\\Driver (%s)", e)

        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                                r"SYSTEM\CurrentControlSet\Enum\USB") as k:
                i = 0
                while True:
                    try:
                        dev = winreg.EnumKey(k, i)
                        i += 1
                        if "VID_05BA" not in dev:
                            continue
                        log.info("Diagnostico: USB %s presente en el registro PnP", dev)
                        with winreg.OpenKey(k, dev) as inst:
                            j = 0
                            while True:
                                try:
                                    instancia = winreg.EnumKey(inst, j)
                                    j += 1
                                    with winreg.OpenKey(inst, instancia) as d:
                                        for prop in ("Service", "DeviceDesc", "Mfg"):
                                            try:
                                                val, _ = winreg.QueryValueEx(d, prop)
                                                log.info("Diagnostico:   %s -> %s = %s",
                                                         instancia, prop, val)
                                            except OSError:
                                                pass
                                except OSError:
                                    break
                    except OSError:
                        break
        except OSError as e:
            log.warning("Diagnostico: sin clave PnP USB (%s)", e)

    def _cargar_dpfj(self):
        ruta = self._ruta_dll("dpfj.dll")
        try:
            self.dpfj = ctypes.WinDLL(ruta)
            log.info("dpfj.dll cargada desde %s", ruta)
        except OSError as e:
            log.error("No se pudo cargar dpfj.dll (%s): %s", ruta, e, exc_info=True)
            self.dpfj = None
            return

        self.dpfj.dpfj_create_fmd_from_raw.restype = ctypes.c_int
        self.dpfj.dpfj_create_fmd_from_raw.argtypes = [
            ctypes.POINTER(ctypes.c_ubyte),
            ctypes.c_uint,
            ctypes.c_uint,
            ctypes.c_uint,
            ctypes.c_uint,
            ctypes.c_int,
            ctypes.c_uint,
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_ubyte),
            ctypes.POINTER(ctypes.c_uint),
        ]

        self.dpfj.dpfj_compare.restype = ctypes.c_int
        self.dpfj.dpfj_compare.argtypes = [
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_ubyte),
            ctypes.c_uint,
            ctypes.c_uint,
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_ubyte),
            ctypes.c_uint,
            ctypes.c_uint,
            ctypes.POINTER(ctypes.c_uint),
        ]

        self.dpfj.dpfj_identify.restype = ctypes.c_int
        self.dpfj.dpfj_identify.argtypes = [
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_ubyte),
            ctypes.c_uint,
            ctypes.c_uint,
            ctypes.c_int,
            ctypes.c_uint,
            ctypes.POINTER(ctypes.POINTER(ctypes.c_ubyte)),
            ctypes.POINTER(ctypes.c_uint),
            ctypes.c_uint,
            ctypes.POINTER(ctypes.c_uint),
            ctypes.POINTER(DPFJ_CANDIDATE),
        ]

    def _cerrar_lector(self):
        """Cierra el handle del lector (si existe) y lo marca como cerrado.

        Tras un desconecta/conecta del USB el handle queda "stale" y las
        capturas fallan aunque el lector vuelva a estar presente. Cerrarlo
        hace que la siguiente captura re-enumere y reabra el dispositivo.
        """
        if self.h_reader and self.dpfpdd:
            try:
                self.dpfpdd.dpfpdd_close(self.h_reader)
            except Exception:  # noqa: BLE001
                pass
        self.h_reader = None

    def _reinit_sdk(self):
        """Reinicia dpfpdd (exit/init) como ultimo recurso tras un hot-plug
        cuando el lector ya no abre. Los device drivers quedan cargados."""
        try:
            if self.dpfpdd:
                self.dpfpdd.dpfpdd_exit()
        except Exception:  # noqa: BLE001
            pass
        try:
            if self.dpfpdd:
                self.dpfpdd.dpfpdd_init()
        except Exception:  # noqa: BLE001
            pass

    def abrir_lector(self):
        """Abre el primer lector DIGITALPERSONA detectado. Devuelve True/False.

        Solo se aceptan lectores DigitalPersona/HID (VID 0x05BA o nombre
        U.are.U/DigitalPersona): el SDK tambien enumera sensores integrados
        via WBF (p. ej. el lector de la laptop), y si el externo se
        desconecta NO debe abrirse el integrado. Sin lector soportado
        devuelve False (la reconexion por hot-plug reintenta al capturar).
        """
        if not self.dpfpdd:
            log.warning("abrir_lector: dpfpdd.dll no cargada.")
            return False
        # Cerrar cualquier handle previo: tras un hot-plug el handle viejo es
        # invalido y abrir encima puede fallar o filtrar recursos.
        self._cerrar_lector()

        elegido = None
        for info in self._enumerar_lectores():
            if _es_lector_digitalpersona(info):
                elegido = info
                break
            log.info(
                "Lector ignorado (no es DigitalPersona): %s (VID %s)",
                _nombre_dispositivo(info), hex(info.id.vendor_id),
            )
        if elegido is None:
            log.warning("Sin lector DigitalPersona conectado.")
            if not self._diag_mostrado:
                # El diagnostico PnP es verboso: una vez por episodio de
                # ausencia (los reintentos de captura lo llamarian en loop).
                self._diag_mostrado = True
                self._diagnostico_lectores()
            return False
        self._diag_mostrado = False

        self.h_reader = ctypes.c_void_p()
        res = self.dpfpdd.dpfpdd_open(elegido.name, ctypes.byref(self.h_reader))
        if res != 0:
            self.h_reader = None
            log.warning("Error al abrir lector (codigo %s).", hex(res))
            return False
        log.info("Lector abierto: %s", _nombre_dispositivo(elegido))
        return True

    def _obtener_resolucion(self):
        size = ctypes.c_uint(ctypes.sizeof(ctypes.c_uint))
        res = self.dpfpdd.dpfpdd_get_device_capabilities(
            self.h_reader,
            ctypes.cast(ctypes.byref(size), ctypes.POINTER(DPFPDD_DEV_CAPS)),
        )
        if res != DPFPDD_E_MORE_DATA:
            return 0

        buf = (ctypes.c_ubyte * size.value)()
        caps = ctypes.cast(buf, ctypes.POINTER(DPFPDD_DEV_CAPS)).contents
        caps.size = size.value
        res = self.dpfpdd.dpfpdd_get_device_capabilities(self.h_reader, ctypes.byref(caps))
        if res != 0 or caps.resolution_cnt == 0:
            return 0
        return caps.resolutions[0]

    def capturar_imagen(self, timeout_ms=5000, buffer_size=512 * 1024):
        """Captura una imagen raw de la huella.

        Devuelve un dict con 'image', 'width', 'height', 'dpi', 'quality'
        o None si la captura falla o expira.

        Tolerante a desconexion/reconexion del lector en plena ejecucion: si
        la captura falla "rapido" (menos de la mitad del timeout - tipico de
        un handle stale tras desconecta/conecta, o lector ausente), se cierra
        el handle, se reabre el lector y se reintenta una vez. Un timeout
        normal (operador sin apoyar el dedo) NO dispara la reconexion.

        Al fallar deja en `ultimo_error_captura` un mensaje legible para el
        operador.
        """
        self.ultimo_error_captura = ""
        if not self.h_reader and not self.abrir_lector():
            self.ultimo_error_captura = "Sin lector DigitalPersona conectado."
            return None

        captura = self._capturar_una(timeout_ms, buffer_size)
        if captura is not None:
            return captura

        if self._tiempo_captura_s < (timeout_ms / 1000.0) * 0.5:
            log.warning("Captura fallo rapido; reconectando lector...")
            self._cerrar_lector()
            if not self.abrir_lector():
                log.warning("Reconexion fallo; re-inicializando SDK.")
                self._reinit_sdk()
                if not self.abrir_lector():
                    self.ultimo_error_captura = (
                        "Sin lector DigitalPersona conectado."
                    )
                    return None
            captura = self._capturar_una(timeout_ms, buffer_size)
            if captura is None and not self.ultimo_error_captura:
                self.ultimo_error_captura = "No se pudo leer la huella."
            return captura
        if not self.ultimo_error_captura:
            self.ultimo_error_captura = (
                "No se recibio la huella (retiro el dedo o lectura muy baja)."
            )
        return None

    def _capturar_una(self, timeout_ms, buffer_size):
        """Una sola captura raw sobre el handle actual. Registra el tiempo
        transcurrido en self._tiempo_captura_s. Devuelve dict o None."""
        self._tiempo_captura_s = 0.0
        if not self.h_reader:
            return None

        params = DPFPDD_CAPTURE_PARAM()
        params.size = ctypes.sizeof(DPFPDD_CAPTURE_PARAM)
        params.image_fmt = DPFPDD_IMG_FMT_PIXEL_BUFFER
        params.image_proc = DPFPDD_IMG_PROC_DEFAULT
        params.image_res = self._obtener_resolucion()
        if params.image_res == 0:
            self.ultimo_error_captura = (
                "El lector no responde (reconectando automaticamente...)."
            )
            log.warning("No se pudo obtener la resolución del lector.")
            return None

        log.info("Coloca tu huella sobre el sensor...")

        image_buffer = (ctypes.c_ubyte * buffer_size)()
        c_image_size = ctypes.c_uint(buffer_size)

        capture_result = DPFPDD_CAPTURE_RESULT()
        capture_result.size = ctypes.sizeof(DPFPDD_CAPTURE_RESULT)
        capture_result.info.size = ctypes.sizeof(DPFPDD_IMAGE_INFO)

        inicio = time.monotonic()
        try:
            res = self.dpfpdd.dpfpdd_capture(
                self.h_reader,
                ctypes.byref(params),
                ctypes.c_uint(timeout_ms),
                ctypes.byref(capture_result),
                ctypes.byref(c_image_size),
                image_buffer,
            )
        except OSError as e:
            # El DLL puede fallar a nivel nativo (p. ej. "integer divide by
            # zero") si el handle apunta a un dispositivo no soportado o quedo
            # en estado invalido tras un hot-plug: tratarlo como captura
            # fallida rapida para que la reconexion cierre y reabra limpio.
            self._tiempo_captura_s = time.monotonic() - inicio
            self.ultimo_error_captura = (
                "Fallo interno del lector; reintentando automaticamente..."
            )
            log.error("dpfpdd_capture fallo nativo: %s", e)
            return None
        self._tiempo_captura_s = time.monotonic() - inicio

        if res == 0 and capture_result.success == 1 and capture_result.quality == 0:
            log.info("Imagen capturada (%dx%d @ %ddpi, %d bytes).",
                     capture_result.info.width, capture_result.info.height,
                     capture_result.info.res, c_image_size.value)
            return {
                "image": bytes(image_buffer[:c_image_size.value]),
                "width": capture_result.info.width,
                "height": capture_result.info.height,
                "dpi": capture_result.info.res,
                "quality": capture_result.info.bpp,
            }
        self.ultimo_error_captura = (
            f"Lectura rechazada (calidad {capture_result.quality}); "
            "vuelve a apoyar el dedo sin moverlo."
        )
        log.warning("Captura sin éxito: res=%s, success=%d, quality=%d, score=%d",
                    hex(res), capture_result.success,
                    capture_result.quality, capture_result.score)
        return None

    def extraer_fmd(self, image_data, width, height, dpi, fmd_type=DPFJ_FMD_ANSI_378_2004):
        """Extrae minucias (FMD) de una imagen raw. Devuelve bytes del FMD."""
        if not self.dpfj:
            return None
        image_arr = (ctypes.c_ubyte * len(image_data)).from_buffer_copy(image_data)
        fmd = (ctypes.c_ubyte * MAX_FMD_SIZE)()
        fmd_size = ctypes.c_uint(MAX_FMD_SIZE)

        res = self.dpfj.dpfj_create_fmd_from_raw(
            image_arr,
            ctypes.c_uint(len(image_data)),
            ctypes.c_uint(width),
            ctypes.c_uint(height),
            ctypes.c_uint(dpi),
            ctypes.c_int(DPFJ_POSITION_UNKNOWN),
            ctypes.c_uint(0),
            ctypes.c_int(fmd_type),
            fmd,
            ctypes.byref(fmd_size),
        )
        if res != DPFJ_SUCCESS:
            log.warning("dpfj_create_fmd_from_raw fallo: %s", hex(res))
            return None
        log.info("FMD extraido: %d bytes", fmd_size.value)
        return bytes(fmd[:fmd_size.value])

    def comparar(self, fmd1, fmd2, fmd_type=DPFJ_FMD_ANSI_378_2004):
        """Compara dos FMD. Devuelve score de disimilitud (0 = match)."""
        if not self.dpfj:
            return None
        buf1 = (ctypes.c_ubyte * len(fmd1)).from_buffer_copy(fmd1)
        buf2 = (ctypes.c_ubyte * len(fmd2)).from_buffer_copy(fmd2)
        score = ctypes.c_uint(0)

        res = self.dpfj.dpfj_compare(
            ctypes.c_int(fmd_type),
            buf1,
            ctypes.c_uint(len(fmd1)),
            ctypes.c_uint(0),
            ctypes.c_int(fmd_type),
            buf2,
            ctypes.c_uint(len(fmd2)),
            ctypes.c_uint(0),
            ctypes.byref(score),
        )
        if res != DPFJ_SUCCESS:
            return None
        return score.value

    def identificar(self, fmd, lista_fmds, fmd_type=DPFJ_FMD_ANSI_378_2004):
        """Busca 'fmd' en 'lista_fmds' (1:N). Devuelve (indice, score) del mejor
        candidato o None si la lista está vacía o falla."""
        if not self.dpfj:
            return None
        if not lista_fmds:
            return None

        n = len(lista_fmds)
        ptrs = (ctypes.POINTER(ctypes.c_ubyte) * n)()
        sizes = (ctypes.c_uint * n)()
        buffers = []
        for i, f in enumerate(lista_fmds):
            buf = (ctypes.c_ubyte * len(f)).from_buffer_copy(f)
            buffers.append(buf)
            ptrs[i] = buf
            sizes[i] = ctypes.c_uint(len(f))

        query = (ctypes.c_ubyte * len(fmd)).from_buffer_copy(fmd)

        candidate_cnt = ctypes.c_uint(1)
        candidates = (DPFJ_CANDIDATE * 1)()
        candidates[0].size = ctypes.sizeof(DPFJ_CANDIDATE)

        res = self.dpfj.dpfj_identify(
            ctypes.c_int(fmd_type),
            query,
            ctypes.c_uint(len(fmd)),
            ctypes.c_uint(0),
            ctypes.c_int(fmd_type),
            ctypes.c_uint(n),
            ptrs,
            sizes,
            ctypes.c_uint(DPFJ_PROBABILITY_ONE),
            ctypes.byref(candidate_cnt),
            candidates,
        )
        if res != DPFJ_SUCCESS or candidate_cnt.value == 0:
            return None

        idx = candidates[0].fmd_idx
        score = self.comparar(fmd, lista_fmds[idx], fmd_type)
        if score is None:
            return None
        log.info("Identificacion: %d candidato(s), mejor = #%d (score %d)",
         candidate_cnt.value, idx, score)
        return (idx, score)

    def cerrar(self):
        if self.h_reader and self.dpfpdd:
            try:
                self.dpfpdd.dpfpdd_close(self.h_reader)
            except Exception:
                pass
            self.h_reader = None
        if self.dpfpdd:
            try:
                self.dpfpdd.dpfpdd_exit()
            except Exception:
                pass


_SDK_UNICA = None


def obtener_sdk():
    """Devuelve la instancia única del SDK (compartida entre vistas)."""
    global _SDK_UNICA
    if _SDK_UNICA is None:
        _SDK_UNICA = BiometricSDK()
    return _SDK_UNICA

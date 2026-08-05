import ctypes

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


class BiometricSDK:
    """Wrapper de bajo nivel (ctypes) de dpfpdd.dll y dpfj.dll."""

    def __init__(self):
        self.dpfpdd = None
        self.dpfj = None
        self.h_reader = None
        self._cargar_dpfpdd()
        self._cargar_dpfj()

    def _cargar_dpfpdd(self):
        self.dpfpdd = ctypes.WinDLL("dpfpdd.dll")

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

        self.dpfpdd.dpfpdd_init()

    def _cargar_dpfj(self):
        self.dpfj = ctypes.WinDLL("dpfj.dll")

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

    def abrir_lector(self):
        """Abre el primer lector DigitalPersona detectado. Devuelve True/False."""
        if not self.dpfpdd:
            print("❌ dpfpdd.dll no cargada.")
            return False

        dev_cnt = ctypes.c_uint(1)
        dev_info = DPFPDD_DEV_INFO()
        dev_info.size = ctypes.sizeof(DPFPDD_DEV_INFO)

        res = self.dpfpdd.dpfpdd_query_devices(ctypes.byref(dev_cnt), ctypes.byref(dev_info))
        if res != 0 or dev_cnt.value == 0:
            print(f"❌ No se encontraron lectores (res={hex(res)}, count={dev_cnt.value}).")
            return False

        self.h_reader = ctypes.c_void_p()
        res = self.dpfpdd.dpfpdd_open(dev_info.name, ctypes.byref(self.h_reader))
        if res != 0:
            self.h_reader = None
            print(f"❌ Error al abrir lector (código {hex(res)}).")
            return False
        nombre = dev_info.descr.product_name.decode("utf-8", errors="ignore")
        print(f"✅ Lector abierto: {nombre}")
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
        """
        if not self.h_reader and not self.abrir_lector():
            return None

        params = DPFPDD_CAPTURE_PARAM()
        params.size = ctypes.sizeof(DPFPDD_CAPTURE_PARAM)
        params.image_fmt = DPFPDD_IMG_FMT_PIXEL_BUFFER
        params.image_proc = DPFPDD_IMG_PROC_DEFAULT
        params.image_res = self._obtener_resolucion()
        if params.image_res == 0:
            print("❌ No se pudo obtener la resolución del lector.")
            return None

        print("🖐️ Coloca tu huella sobre el sensor...")

        image_buffer = (ctypes.c_ubyte * buffer_size)()
        c_image_size = ctypes.c_uint(buffer_size)

        capture_result = DPFPDD_CAPTURE_RESULT()
        capture_result.size = ctypes.sizeof(DPFPDD_CAPTURE_RESULT)
        capture_result.info.size = ctypes.sizeof(DPFPDD_IMAGE_INFO)

        res = self.dpfpdd.dpfpdd_capture(
            self.h_reader,
            ctypes.byref(params),
            ctypes.c_uint(timeout_ms),
            ctypes.byref(capture_result),
            ctypes.byref(c_image_size),
            image_buffer,
        )

        if res == 0 and capture_result.success == 1 and capture_result.quality == 0:
            print(f"✅ Imagen capturada ({capture_result.info.width}x{capture_result.info.height} "
                  f"@ {capture_result.info.res}dpi, {c_image_size.value} bytes).")
            return {
                "image": bytes(image_buffer[:c_image_size.value]),
                "width": capture_result.info.width,
                "height": capture_result.info.height,
                "dpi": capture_result.info.res,
                "quality": capture_result.info.bpp,
            }
        print(f"⚠️ Captura sin éxito: res={hex(res)}, success={capture_result.success}, "
              f"quality={capture_result.quality}, score={capture_result.score}")
        return None

    def extraer_fmd(self, image_data, width, height, dpi, fmd_type=DPFJ_FMD_ANSI_378_2004):
        """Extrae minucias (FMD) de una imagen raw. Devuelve bytes del FMD."""
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
            print(f"❌ dpfj_create_fmd_from_raw falló: {hex(res)}")
            return None
        print(f"🔑 FMD extraído: {fmd_size.value} bytes")
        return bytes(fmd[:fmd_size.value])

    def comparar(self, fmd1, fmd2, fmd_type=DPFJ_FMD_ANSI_378_2004):
        """Compara dos FMD. Devuelve score de disimilitud (0 = match)."""
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
        print(f"🎯 Identificación: {candidate_cnt.value} candidato(s), mejor = #{idx} (score {score})")
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

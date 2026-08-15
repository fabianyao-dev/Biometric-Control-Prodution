import ctypes
from ctypes import wintypes
import sys

sys.stdout.reconfigure(encoding="utf-8")

# Cargar la librería DLL del driver que acabamos de instalar
try:
    dpfpdd = ctypes.CDLL("dpfpdd.dll")
    print("DLL de DigitalPersona cargada correctamente.")
except Exception as e:
    print(f"Error al cargar dpfpdd.dll: {e}")
    sys.exit(1)

# Inicializar la librería C
result = dpfpdd.dpfpdd_init()
if result == 0:
    print("SDK de DigitalPersona inicializado con éxito.")
else:
    print(f"Error al inicializar SDK. Código de respuesta: {result}")

# Finalizar prueba limpia
dpfpdd.dpfpdd_exit()

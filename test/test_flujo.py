import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.database import guardar_operador, listar_fmds
from src.hardware.biometric_service import BiometricService

sys.stdout.reconfigure(encoding="utf-8")

def registrar(archivo_fmd, nombre):
    with open(archivo_fmd, "rb") as f:
        fmd = f.read()
    ok, msg = guardar_operador(nombre, fmd)
    print(f"{'OK' if ok else 'ERROR'}: {msg}")
    return 0 if ok else 1

def identificar(archivo_fmd):
    with open(archivo_fmd, "rb") as f:
        fmd = f.read()
    filas = listar_fmds()
    if not filas:
        print("No hay operadores registrados.")
        return 1
    s = BiometricService()
    resultado = s.identificar(fmd, [fila[2] for fila in filas])
    if resultado:
        idx, score = resultado
        print(f"IDENTIFICADO: {filas[idx][1]} (score {score})")
    else:
        print("Huella no reconocida.")
    s.cerrar()
    return 0

def main():
    comando = sys.argv[1]
    if comando == "registrar":
        return registrar(sys.argv[2], sys.argv[3])
    if comando == "identificar":
        return identificar(sys.argv[2])
    print("Uso: test\\test_flujo.py registrar <fmd> <nombre> | identificar <fmd>")
    return 1

if __name__ == "__main__":
    sys.exit(main())

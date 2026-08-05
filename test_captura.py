import sys

from src.hardware.biometric_service import BiometricService

sys.stdout.reconfigure(encoding="utf-8")

def main():
    salida = sys.argv[1] if len(sys.argv) > 1 else "captura.fmd"
    servicio = BiometricService()
    if not servicio.abrir():
        print("❌ No se pudo abrir el lector.")
        return 1

    captura = servicio.capturar_huella()
    if not captura:
        print("❌ Falló la captura.")
        servicio.cerrar()
        return 1

    with open(salida, "wb") as f:
        f.write(captura["fmd"])
    print(f"✅ FMD capturado y guardado en {salida} ({len(captura['fmd'])} bytes, "
          f"{captura['width']}x{captura['height']} @ {captura['dpi']}dpi)")
    servicio.cerrar()
    return 0

if __name__ == "__main__":
    sys.exit(main())

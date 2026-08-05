import sys

from src.hardware.biometric_service import BiometricService

sys.stdout.reconfigure(encoding="utf-8")

def main():
    servicio = BiometricService()
    if not servicio.abrir():
        print("❌ No se pudo abrir el lector. Conéctalo y reintenta.")
        return

    print("🖐️ Captura #1: coloca la MISMA huella sobre el sensor...")
    cap1 = servicio.capturar_huella()
    if not cap1:
        print("❌ Falló la captura #1.")
        servicio.cerrar()
        return
    print(f"✅ FMD #1 extraído ({len(cap1['fmd'])} bytes, {cap1['width']}x{cap1['height']} @ {cap1['dpi']}dpi)")

    print("🖐️ Captura #2: coloca la MISMA huella otra vez...")
    cap2 = servicio.capturar_huella()
    if not cap2:
        print("❌ Falló la captura #2.")
        servicio.cerrar()
        return
    print(f"✅ FMD #2 extraído ({len(cap2['fmd'])} bytes)")

    score = servicio.comparar(cap1["fmd"], cap2["fmd"])
    print(f"🔎 Comparación 1:1 -> score de disimilitud: {score} (0 = match perfecto)")

    resultado = servicio.identificar(cap1["fmd"], [cap2["fmd"]])
    if resultado:
        idx, s = resultado
        print(f"🔎 Identificación 1:N -> candidato #{idx} con score {s} -> COINCIDE" if s <= 0x04000000
              else f"🔎 Identificación 1:N -> candidato #{idx} con score {s} -> NO coincide (umbral)")
    else:
        print("🔎 Identificación 1:N -> sin candidatos")

    servicio.cerrar()

if __name__ == "__main__":
    main()

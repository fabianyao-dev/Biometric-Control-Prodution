"""
test_pines.py - Barrido guiado de pines y polaridad para encontrar donde
responde el modulo rele.

Por cada pin:
    1) Se escribe LOW  (3s) -> preguntas si hubo click
    2) Se escribe HIGH (3s) -> preguntas si hubo click
    3) Se escribe LOW  (3s) -> preguntas si hubo click (confirmacion)

Interpretacion:
    - Click al pasar a LOW  -> rele ACTIVO-BAJO (igual que config.GPIO_CONFIG)
    - Click al pasar a HIGH -> rele ACTIVO-ALTO (polaridad invertida)
    - Ningun click          -> senal no llega a ese pin / modulo sin alimentar

Uso:
    python test_pines.py                    # barre la lista sugerida
    python test_pines.py --pines 17 22 4 5  # probar solo esos pines
    python test_pines.py --pin 17           # probar un solo pin
"""

import argparse
import logging
import sys
import time

import RPi.GPIO as GPIO

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("test_pines")

PINES_SUGERIDOS = [17, 22, 4, 5, 6, 12, 13, 16, 18, 19, 20, 21, 23, 24, 25, 26]

FISICO = {
    17: 11, 22: 15, 4: 7, 5: 29, 6: 31, 12: 32, 13: 33, 16: 36,
    18: 12, 19: 35, 20: 38, 21: 40, 23: 16, 24: 18, 25: 22, 26: 37,
}

ESPERA_S = 3


def abrir_terminal():
    try:
        return open("/dev/tty", "r")  # noqa: SIM115
    except OSError as e:
        log.warning("Sin terminal real (%s); usando stdin", e)
        return sys.stdin


def leer(fuente):
    while True:
        try:
            linea = fuente.readline()
        except KeyboardInterrupt:
            print()
            return "q"
        if linea == "":
            log.warning("EOF ignorado. Escribe 'q' para salir.")
            time.sleep(1)
            continue
        return linea


def preguntar(fuente, mensaje):
    print(f"  {mensaje} [s/N]: ", end="", flush=True)
    r = leer(fuente).strip().lower()
    if r in ("q", "salir", "exit"):
        return None
    return r in ("s", "si", "y", "yes")


def probar_pin(pin, fuente, espera=ESPERA_S):
    fisico = FISICO.get(pin, pin)
    log.info("========== PIN GPIO %s (fisico %s) ==========", pin, fisico)
    log.info("Mueve el cable IN del rele a este pin y confirma.")
    print(f"  Conecta el IN del rele al GPIO {pin} = pin fisico {fisico}.",
          flush=True)
    print("  [Enter] para continuar, 'q' para salir: ", end="", flush=True)
    if leer(fuente).strip().lower() in ("q", "salir", "exit"):
        return None

    GPIO.setup(pin, GPIO.OUT)
    GPIO.output(pin, GPIO.HIGH)

    clicks = []
    for nombre, nivel in (("LOW", GPIO.LOW), ("HIGH", GPIO.HIGH), ("LOW", GPIO.LOW)):
        GPIO.output(pin, nivel)
        log.info("  -> %s (rele deberia 'click')", nombre)
        time.sleep(espera)
        resp = preguntar(fuente, f"  Hubo click al pasar a {nombre}?")
        if resp is None:
            return None
        if resp:
            clicks.append(nombre)

    GPIO.output(pin, GPIO.HIGH)

    if clicks == ["LOW", "LOW"]:
        log.info("RESULTADO: ACTIVO-BAJO (funciona con LOW) en GPIO %s", pin)
        return ("activo-bajo", pin)
    if clicks == ["HIGH"]:
        log.info("RESULTADO: ACTIVO-ALTO (funciona con HIGH) en GPIO %s", pin)
        return ("activo-alto", pin)
    log.warning("RESULTADO: sin click o inconsistente en GPIO %s (clicks=%s)",
                pin, clicks)
    return ("sin-respuesta", pin)


def main():
    parser = argparse.ArgumentParser(description="Barrido de pines y polaridad")
    parser.add_argument("--pines", type=int, nargs="+",
                        help="Pines a probar (BCM)")
    parser.add_argument("--pin", type=int, help="Probar un solo pin")
    parser.add_argument("--espera", type=float, default=ESPERA_S,
                        help="Segundos por estado")
    args = parser.parse_args()

    if args.pin:
        pines = [args.pin]
    elif args.pines:
        pines = args.pines
    else:
        pines = PINES_SUGERIDOS

    log.info("Barrido de %d pines: %s", len(pines), pines)
    log.info("Iniciar probando los ya conectados (17 y 22), luego mueve el "
             "cable a cada pin de la lista.")

    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)

    fuente = abrir_terminal()
    resultados = {}
    try:
        for pin in pines:
            res = probar_pin(pin, fuente, args.espera)
            if res is None:
                break
            resultados[pin] = res[0]
        log.info("========== RESUMEN ==========")
        if not resultados:
            log.info("No se probo ningun pin.")
            return 0
        for pin, res in resultados.items():
            log.info("GPIO %s (fisico %s): %s",
                     pin, FISICO.get(pin, pin), res)
        buenos = {p: r for p, r in resultados.items() if r.startswith("activo")}
        if buenos:
            log.info("Pines que responden: %s", buenos)
        else:
            log.warning("NINGUN pin respondio. Revisa alimentacion del modulo "
                        "(VCC + GND + puente JD-VCC).")
    finally:
        for pin in pines:
            try:
                GPIO.setup(pin, GPIO.OUT)
                GPIO.output(pin, GPIO.HIGH)
            except Exception:  # noqa: BLE001
                pass
        GPIO.cleanup()
        log.info("Pines liberados (estado HIGH/seguro)")


if __name__ == "__main__":
    sys.exit(main())

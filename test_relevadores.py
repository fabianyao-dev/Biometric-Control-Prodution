"""
test_relevadores.py - Control manual e interactivo de los reles GPIO 5 y 6.

Los reles de este proyecto son ACTIVOS-BAJO:
    - LOW  = bobina energizada -> rele cerrado (ACTIVADO)
    - HIGH = bobina sin corriente -> rele abierto (DESACTIVADO)

Mapeo de pines (conector de 40 pines de la RPi):
    BCM GPIO 5  -> pin fisico 29  (RELE_ENCENDIDO)
    BCM GPIO 6  -> pin fisico 31  (RELE_PARO)

Cada comando escribe el pin y lee su estado real para confirmar que el valor
quedo aplicado. Al salir (q) ambos reles quedan DESACTIVADOS y se liberan los
pines.

Uso:
    python test_relevadores.py                # polaridad activo-bajo
    python test_relevadores.py --invertir     # para modulos activo-alto

Comandos:
    5 on | 5 off | 6 on | 6 off     -> enciende/apaga un rele
    5 pulso | 6 pulso               -> pulso momentaneo (circuito tipo boton)
    a | b                           -> apaga/enciende AMBOS a la vez
    toggle                          -> invierte ambos (para escuchar clicks)
    estado | s                      -> muestra estado actual
    q                               -> salir (libera pines, reles apagados)
"""

import argparse
import logging
import sys
import time

import RPi.GPIO as GPIO

PIN_START = 5
PIN_PAUSE = 6

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("test_relevadores")

NOMBRES = {
    PIN_START: "RELE_ENCENDIDO",
    PIN_PAUSE: "RELE_PARO",
}
FISICOS = {PIN_START: 29, PIN_PAUSE: 31}
PIN_FISICO = {29: PIN_START, 31: PIN_PAUSE}


def setup_gpio():
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)
    log.info("=== MAPEO DE PINES ===")
    for pin in (PIN_START, PIN_PAUSE):
        log.info("  GPIO %s -> pin fisico %s (%s)", pin, FISICOS[pin], NOMBRES[pin])
    log.info("  Confirmacion: los IN del modulo deben ir a los pines fisicos "
             "%s y %s.", FISICOS[PIN_START], FISICOS[PIN_PAUSE])
    for pin in (PIN_START, PIN_PAUSE):
        GPIO.setup(pin, GPIO.IN)  # estado seguro: alta impedancia = apagado
        ESTADO[pin] = False
        log.info("%s en INPUT (apagado, corriente cortada)", NOMBRES[pin])


ESTADO = {PIN_START: False, PIN_PAUSE: False}


def escribir(pin, activado, invertir):
    if invertir:
        activado = not activado
    if activado:
        GPIO.setup(pin, GPIO.OUT)
        GPIO.output(pin, GPIO.LOW)
        leido = GPIO.input(pin)
        ok = leido == GPIO.LOW
        log.info("%s: ACTIVADO (pin=%s) | OUT/LOW leido=%s %s",
                 NOMBRES[pin], pin,
                 "LOW" if leido == GPIO.LOW else "HIGH",
                 "OK" if ok else "!!! ERROR-REVISA-CABLEADO")
    else:
        GPIO.setup(pin, GPIO.IN)
        log.info("%s: DESACTIVADO (pin=%s) | pin en INPUT, corriente cortada "
                 "(no se lee nivel)", NOMBRES[pin], pin)
        ok = True
    ESTADO[pin] = activado
    return ok


def pulso(pin, duracion_ms=300, invertir=False):
    """Emula el nuevo circuito TIPO BOTON: pulso momentaneo activo-bajo."""
    log.info("%s: PULSO de %s ms (pin=%s)", NOMBRES[pin], duracion_ms, pin)
    if not invertir:
        GPIO.setup(pin, GPIO.OUT)
        GPIO.output(pin, GPIO.LOW)
        leido = GPIO.input(pin)
        ok = leido == GPIO.LOW
        log.info("    bobina energizada (OUT/LOW leido=%s) %s",
                 "LOW" if leido == GPIO.LOW else "HIGH",
                 "OK" if ok else "!!! ERROR-REVISA-CABLEADO")
        time.sleep(duracion_ms / 1000.0)
        GPIO.setup(pin, GPIO.IN)
        log.info("    pulso terminado: pin en INPUT (corriente cortada)")
    else:
        log.info("    (polaridad invertida no soportada para pulso)")
        ok = True
    ESTADO[pin] = False
    return ok


def estado():
    print("  Estado actual de los reles:")
    for pin in (PIN_START, PIN_PAUSE):
        print(f"    {NOMBRES[pin]} (GPIO {pin}): "
              f"{'ACTIVADO' if ESTADO[pin] else 'DESACTIVADO'}")


def ayudas():
    print()
    print("  Comandos:")
    print("    5 on | 5 off      enciende / apaga RELE_ENCENDIDO")
    print("    6 on | 6 off      enciende / apaga RELE_PARO")
    print("    5 pulso | 6 pulso pulso momentaneo (circuito tipo boton)")
    print("    a                 apaga ambos")
    print("    b                 enciende ambos")
    print("    toggle            invierte ambos (escuchar los clicks)")
    print("    estado | s        muestra el estado actual")
    print("    ayuda | h         muestra esta ayuda")
    print("    q                 salir (libera pines, reles apagados)")
    print()


def procesar(cmd, invertir):
    cmd = cmd.strip().lower()
    partes = cmd.split()
    if not partes:
        return False, False
    op = partes[0]

    if op in ("q", "salir", "exit"):
        return True
    if op in ("ayuda", "h", "?"):
        ayudas()
        return False
    if op in ("estado", "s"):
        estado()
        return False

    if op == "a":
        for pin in (PIN_START, PIN_PAUSE):
            escribir(pin, False, invertir)
        estado()
        return False
    if op == "b":
        for pin in (PIN_START, PIN_PAUSE):
            escribir(pin, True, invertir)
        estado()
        return False
    if op == "toggle":
        for pin in (PIN_START, PIN_PAUSE):
            escribir(pin, not ESTADO[pin], invertir)
        estado()
        return False

    if op in ("5", "6") and len(partes) >= 2 and partes[1] in ("on", "off"):
        pin = int(op)
        activar = partes[1] == "on"
        escribir(pin, activar, invertir)
        estado()
        return False

    if op in ("5", "6") and len(partes) >= 2 and partes[1] == "pulso":
        pulso(int(op), invertir=invertir)
        estado()
        return False

    # Tolerancia al nombre del pin fisico (29/31)
    if op in ("29", "31") and len(partes) >= 2 and partes[1] in ("on", "off"):
        pin = PIN_FISICO[int(op)]
        escribir(pin, partes[1] == "on", invertir)
        estado()
        return False

    print(f"  Comando no reconocido: {cmd!r}. Escribe 'ayuda'.")
    return False


def abrir_terminal():
    """Abre el terminal real. El programa lee comandos SOLO de aqui."""
    try:
        tty = open("/dev/tty", "r")  # noqa: SIM115
        log.info("Comandos leidos del terminal real (/dev/tty)")
        return tty
    except OSError as e:
        log.warning("No hay terminal real (%s). Usando stdin.", e)
        return sys.stdin


def leer_comando(fuente):
    """Lee un comando. NUNCA sale por EOF: solo 'q' o Ctrl+C cierran."""
    while True:
        try:
            print("rele> ", end="", flush=True)
            linea = fuente.readline()
        except KeyboardInterrupt:
            print()
            return "q"
        if linea == "":
            # EOF (Ctrl+D o stdin cerrado): NO se sale, los reles quedan igual.
            log.warning("EOF ignorado (Ctrl+D no sale). Escribe 'q' para salir.")
            time.sleep(1)
            continue
        return linea


def main():
    parser = argparse.ArgumentParser(description="Control manual de reles GPIO 5 y 6")
    parser.add_argument("--invertir", action="store_true",
                        help="Polaridad opuesta (modulos ACTIVOS-ALTO)")
    args = parser.parse_args()

    if args.invertir:
        log.warning("POLARIDAD INVERTIDA: bobina ACTIVA con HIGH, se libera con LOW")

    setup_gpio()
    fuente = abrir_terminal()
    try:
        estado()
        ayudas()
        while True:
            cmd = leer_comando(fuente)
            if procesar(cmd, args.invertir):
                break
    finally:
        for pin in (PIN_START, PIN_PAUSE):
            escribir(pin, False, args.invertir)
        GPIO.cleanup()
        log.info("Pines liberados, reles DESACTIVADOS (estado seguro)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""
test_modbus_zelio.py - Diagnostico del SR3NET01BD (Zelio Logic 2 + modulo
Ethernet SR3NET01BD) via Modbus TCP.

El NET01BD NO expone coils individuales: expone 4 palabras de ENTRADA
(J1XT1..J4XT1, lectura/escritura por el master) y 4 palabras de SALIDA
(O1XT1..O4XT1, solo lectura). Direcciones 0-based (como las usa pyModbusTCP):

    J1..J4 -> 16, 17, 18, 19   (PC -> PLC)  ej. START / PAUSE / heartbeat
    O1..O4 -> 20, 21, 22, 23   (PLC -> PC)  ej. contador / estado

Solo lectura por defecto: el script NO escribe nada salvo que se pida
explicitamente con --escribir o --pulso (OJO: eso puede arrancar la maquina).

Uso:
    python test\\test_modbus_zelio.py --ip 192.158.1.80
    python test\\test_modbus_zelio.py --ip 192.158.1.80 --seguir 20
    python test\\test_modbus_zelio.py --ip 192.158.1.80 --escribir J1 1
    python test\\test_modbus_zelio.py --ip 192.158.1.80 --pulso J1 --ms 300
"""

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pyModbusTCP.client import ModbusClient

from src import config

sys.stdout.reconfigure(encoding="utf-8")

J_BASE = 16   # J1XT1
O_BASE = 20   # O1XT1
N_WORDS = 4


def _bits(valor):
    """Muestra los 16 bits de una palabra (bit15 ... bit0)."""
    return format(valor & 0xFFFF, "016b")


def _palabra(valor):
    """Valor sin signo (las palabras del Zelio son 16 bits con signo)."""
    return valor - 0x10000 if valor & 0x8000 else valor


def leer(cliente, base, n=N_WORDS):
    """Lee n palabras desde `base`. Devuelve lista o None."""
    return cliente.read_holding_registers(base, n)


def mostrar(cliente, base, etiqueta):
    """Lee e imprime 4 palabras con su base binaria."""
    regs = leer(cliente, base)
    if regs is None or len(regs) < N_WORDS:
        print(f"  {etiqueta}: no se pudo leer (base {base})")
        return None
    for i, r in enumerate(regs[:N_WORDS], start=1):
        print(f"  {etiqueta}{i} (dir {base + i - 1:>3}) = {r:>5}  "
              f"(con signo {_palabra(r):>6})  bits {_bits(r)}")
    return regs


def interpretar_contador(o):
    """Muestra las dos lecturas posibles del contador de 32 bits (O1/O2)."""
    if o is None or len(o) < 2:
        return
    bajo, alto = o[0], o[1]
    print("  -- contador en O1/O2 --")
    print(f"     O1=palabra baja, O2=palabra alta (little) = "
          f"{alto * 65536 + bajo}")
    print(f"     O1=palabra alta, O2=palabra baja (big)    = "
          f"{bajo * 65536 + alto}")


def main():
    parser = argparse.ArgumentParser(description="Diagnostico Modbus TCP Zelio")
    parser.add_argument("--ip", default=config.MODBUS_CONFIG["host"],
                        help="IP del SR3NET01BD")
    parser.add_argument("--port", type=int,
                        default=config.MODBUS_CONFIG["port"])
    parser.add_argument("--unit", type=int,
                        default=config.MODBUS_CONFIG["unit_id"])
    parser.add_argument("--seguir", type=int, default=0,
                        help="Vigila el contador N segundos (solo lectura)")
    parser.add_argument("--escribir", nargs=2, metavar=("J", "VALOR"),
                        help="Escribe VALOR (0/1) en la palabra J1..J4 "
                             "(OJO: puede arrancar la maquina)")
    parser.add_argument("--pulso", metavar="J",
                        help="Pulso de 1 en la palabra J1..J4 y regreso a 0")
    parser.add_argument("--ms", type=int, default=300,
                        help="Duracion del pulso en ms (default 300)")
    args = parser.parse_args()

    if not args.ip:
        print("Sin IP: usa --ip o configura MODBUS_HOST en el .env")
        return 1

    cliente = ModbusClient(args.ip, args.port, unit_id=args.unit,
                           timeout=3.0, auto_open=True)
    if not cliente.open():
        print(f"No se pudo conectar a {args.ip}:{args.port} (unit {args.unit}).")
        print("Revisa: IP, cable, LED PWR/LK del NET01BD y que el PLC este "
              "en RUN.")
        return 1
    print(f"Conectado a {args.ip}:{args.port} (unit_id={args.unit})")

    try:
        print("\n=== Palabras J (PC -> PLC) ===")
        j = mostrar(cliente, J_BASE, "J")
        print("\n=== Palabras O (PLC -> PC) ===")
        o = mostrar(cliente, O_BASE, "O")
        print()
        interpretar_contador(o)

        if args.seguir:
            print(f"\n=== Vigilando {args.seguir} s "
                  f"(pulsa Ctrl+C para salir) ===")
            fin = time.time() + args.seguir
            while time.time() < fin:
                regs = leer(cliente, O_BASE, 2)
                if regs and len(regs) >= 2:
                    print(f"  {time.strftime('%H:%M:%S')}  O1={regs[0]:>5} "
                          f"O2={regs[1]:>5}  "
                          f"little={regs[1] * 65536 + regs[0]:>8}  "
                          f"big={regs[0] * 65536 + regs[1]:>8}")
                else:
                    print("  (lectura fallida)")
                time.sleep(1)

        if args.escribir:
            palabra = args.escribir[0].upper()
            valor = int(args.escribir[1])
            idx = "J1 J2 J3 J4".split().index(palabra)
            addr = J_BASE + idx
            ok = cliente.write_single_register(addr, valor)
            print(f"\nEscrita {palabra} (dir {addr}) = {valor} -> "
                  f"{'OK' if ok else 'FALLO'}")

        if args.pulso:
            palabra = args.pulso.upper()
            idx = "J1 J2 J3 J4".split().index(palabra)
            addr = J_BASE + idx
            print(f"\nPULSO en {palabra} (dir {addr}) {args.ms} ms...")
            cliente.write_single_register(addr, 1)
            time.sleep(args.ms / 1000.0)
            cliente.write_single_register(addr, 0)
            print("  pulso terminado (vuelto a 0)")
    finally:
        cliente.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

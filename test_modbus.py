"""
test_modbus.py - Diagnostico del modulo Advantech (Modbus TCP).

Se usa en planta para validar el cableado y el mapa de registros que despues
vive en .env (coils de START/PAUSE y registro contador). Lee los parametros
del .env por defecto; los flags de abajo permiten probar a mano.

Uso:
    python test_modbus.py                 # lee contador usando el .env
    python test_modbus.py --ip 192.168.0.10 --port 502
    python test_modbus.py --coil 0 --pulso # pulso 300ms en el coil (tipo boton)
    python test_modbus.py --coil 0 --pulso-invertido # pulso invertido (activo=False)
    python test_modbus.py --coil 1 --on    # deja el coil en True (OJO: energiza)
    python test_modbus.py --coil 1 --off   # pone el coil en False (seguro)
    python test_modbus.py --reg 4 --words 2  # lee un registro cualquiera
"""

import argparse
import sys
import time

from pyModbusTCP.client import ModbusClient

from src import config

sys.stdout.reconfigure(encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="Diagnostico Modbus TCP")
    parser.add_argument("--ip", default=config.MODBUS_CONFIG["host"])
    parser.add_argument("--port", type=int, default=config.MODBUS_CONFIG["port"])
    parser.add_argument("--unit", type=int, default=config.MODBUS_CONFIG["unit_id"])
    parser.add_argument("--reg", type=int,
                        default=config.MODBUS_CONFIG["counter_register"],
                        help="Registro a leer (por defecto el del contador)")
    parser.add_argument("--words", type=int,
                        default=config.MODBUS_CONFIG["counter_words"])
    parser.add_argument("--coil", type=int, help="Coil a escribir (start/pause)")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--pulso", action="store_true",
                       help="Pulso momentaneo (tipo boton)")
    group.add_argument("--pulso-invertido", action="store_true",
                       help="Pulso invertido (activo=False, reposo=True)")
    group.add_argument("--on", action="store_true",
                       help="Dejar el coil en True (energizado!)")
    group.add_argument("--off", action="store_true",
                       help="Dejar el coil en False")
    args = parser.parse_args()

    if not args.ip:
        print("Sin MODBUS_HOST en .env. Configura el .env y reintenta.")
        return 1

    cliente = ModbusClient(args.ip, args.port, unit_id=args.unit,
                           timeout=3.0, auto_open=True)
    if not cliente.open():
        print(f"No se pudo conectar a {args.ip}:{args.port}. "
              "Revisa IP, puerto y cableado.")
        return 1
    print(f"Conectado a {args.ip}:{args.port} (unit_id={args.unit}).")

    # 1) Leer el registro contador (o el registro pedido).
    regs = cliente.read_holding_registers(args.reg, args.words)
    if regs is None:
        print(f"No se pudo leer el registro {args.reg} ({args.words} words).")
        cliente.close()
        return 1
    valor = 0
    for r in reversed(regs):
        valor = (valor << 16) | (r & 0xFFFF)
    print(f"Registro {args.reg}: {regs} -> valor {valor} (little-endian)")

    # 2) Operar un coil si se pidio.
    if args.coil is not None:
        pulso_ms = config.MODBUS_CONFIG["pulso_duracion_ms"]
        if args.pulso or args.pulso_invertido:
            activo = not args.pulso_invertido  # True normal, False invertido
            reposo = args.pulso_invertido
            ok = cliente.write_single_coil(args.coil, activo)
            print(f"Coil {args.coil} activo={activo} ({ok}). "
                  f"Esperando {pulso_ms} ms...")
            time.sleep(pulso_ms / 1000.0)
            ok2 = cliente.write_single_coil(args.coil, reposo)
            print(f"Coil {args.coil} reposo={reposo} ({ok2}). "
                  "Pulso terminado.")
        else:
            valor_coil = args.on
            ok = cliente.write_single_coil(args.coil, valor_coil)
            print(f"Coil {args.coil} = {valor_coil} ({ok}).")
            if args.on:
                print("CUIDADO: el coil quedo energizado; usa --off cuando "
                      "termines la prueba.")

    # 3) Lectura de confirmacion del coil (si aplica).
    if args.coil is not None:
        estado = cliente.read_coils(args.coil, 1)
        print(f"Lectura de confirmacion coil {args.coil}: {estado}")

    cliente.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""
monitoreo_zelio.py - Consola EN VIVO del SR3NET01BD (Zelio Logic 2) por
Modbus TCP.

Muestra cada muestreo:
    - Las 4 palabras J (PC -> PLC) y las 4 palabras O (PLC -> PC).
    - El contador de cortes, leido de O1 (16 bits).
    - El delta entre muestreos (lo que el HAL sumaria como cortes).
    - Con --hal, ademas, lo que ve la APP: el conteo de cortes acumulado
      por el ModbusController real (misma regla de deltas y de descarte de
      saltos anomalos).

MEDIDO en el PLC real (ver MAPA_MODBUS_ZELIO.md): el contador esta en O1 y
es de 16 bits. O2 NO es la palabra alta del contador: es la palabra de
PULSOS del PLC (se enciende un instante en cada corte y se apaga solo), por
eso el HAL lee SOLO O1 (MODBUS_COUNTER_WORDS=1): leer O1+O2 como 32 bits
corrompe el valor (+65536 en cada pulso) y se pierden cortes. Cuando veas el
aviso "O2 = pulso", es eso.

Es de SOLO LECTURA salvo que se usen --marcha o --paro, que escriben en las
palabras J (y requieren confirmacion: pueden arrancar/detener la maquina).

Uso:
    python test\\monitoreo_zelio.py                      # lectura en vivo
    python test\\monitoreo_zelio.py --hal                # + lo que ve la app
    python test\\monitoreo_zelio.py --marcha             # suelta el PARO y pulsa START
    python test\\monitoreo_zelio.py --paro               # latchea el PARO (detiene)
    python test\\monitoreo_zelio.py --duracion 30        # 30 s y sale
    python test\\monitoreo_zelio.py --ip 192.158.1.80
"""

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pyModbusTCP.client import ModbusClient

from src import config
from src.hardware import modbus_controller as mod

sys.stdout.reconfigure(encoding="utf-8")

J_BASE = 16   # J1XT1 (PC -> PLC)
O_BASE = 20   # O1XT1 (PLC -> PC)
N_WORDS = 4


def _leer(cliente, base, n=N_WORDS):
    """Lee n palabras desde `base`. Devuelve lista o None."""
    return cliente.read_holding_registers(base, n)


def _contador16(o):
    """Contador de cortes: O1 (16 bits) es la palabra fiable.

    O2 NO es la palabra alta del contador: es la palabra de PULSOS del PLC
    (se enciende un instante en cada corte y se apaga solo), por eso el HAL
    lee SOLO O1 (`MODBUS_COUNTER_WORDS=1`).
    """
    if not o:
        return None
    return o[0]


def _linea_palabras(regs, prefijo):
    if regs is None:
        return f"{prefijo}: (sin lectura)"
    return "  ".join(f"{prefijo}{i}={r:>5}" for i, r in enumerate(regs, 1))


def main():
    cfg = config.MODBUS_CONFIG
    parser = argparse.ArgumentParser(
        description="Consola en vivo del SR3NET01BD por Modbus TCP")
    parser.add_argument("--ip", default=cfg["host"],
                        help="IP del SR3NET01BD")
    parser.add_argument("--port", type=int, default=cfg["port"])
    parser.add_argument("--unit", type=int, default=cfg["unit_id"])
    parser.add_argument("--periodo", type=float, default=0.5,
                        help="Segundos entre muestreos (default 0.5)")
    parser.add_argument("--duracion", type=float, default=0.0,
                        help="Segundos que dura el monitoreo (0 = hasta Ctrl+C)")
    parser.add_argument("--hal", action="store_true",
                        help="Levanta el HAL real y muestra el conteo de la app")
    parser.add_argument("--marcha", action="store_true",
                        help="Suelta el PARO y pulsa START (arranca la maquina)")
    parser.add_argument("--paro", action="store_true",
                        help="Latchea el PARO (detiene la maquina)")
    parser.add_argument("--sin-confirmar", action="store_true",
                        help="No pide confirmacion antes de escribir")
    args = parser.parse_args()

    if not args.ip:
        print("Sin IP: usa --ip o configura MODBUS_HOST en el .env")
        return 1

    # ------------------------------------------------------------------
    # Cliente simple (solo lectura) para el muestreo en vivo
    # ------------------------------------------------------------------
    cli = ModbusClient(args.ip, args.port, unit_id=args.unit,
                       timeout=3.0, auto_open=True)
    if not cli.open():
        print(f"No se pudo conectar a {args.ip}:{args.port} "
              "(unit %s)." % args.unit)
        print("Revisa: IP, cable, LED PWR/LK del NET01BD y que el PLC este "
              "en RUN.")
        return 1
    print(f"Conectado a {args.ip}:{args.port} (unit_id={args.unit})")

    # ------------------------------------------------------------------
    # HAL real (lo que ve la app)
    # ------------------------------------------------------------------
    ctrl = None
    if args.hal or args.marcha or args.paro:
        modbus_cfg = dict(cfg)
        modbus_cfg.update({
            "host": args.ip, "port": args.port, "unit_id": args.unit,
        })
        ctrl = mod.ModbusController(modbus_cfg)
        print(f"HAL en modo '{modbus_cfg.get('cmd_mode', 'coil')}' "
              f"(J1={modbus_cfg.get('start_register', 16)} para START, "
              f"J2={modbus_cfg.get('pause_register', 17)} para PARO, "
              f"contador en O1={modbus_cfg.get('counter_register', 20)}, "
              f"{modbus_cfg.get('counter_words', 1)} palabra(s))")

    # ------------------------------------------------------------------
    # Acciones de escritura
    # ------------------------------------------------------------------
    if args.marcha or args.paro:
        accion = "MARCHA (suelta el PARO y pulsa START)" if args.marcha \
            else "PARO (latchea el PARO: la maquina queda detenida)"
        if not args.sin_confirmar:
            resp = input(f"  {accion}. Confirmar (s/N)? ").strip().lower()
            if resp not in ("s", "si", "y", "yes"):
                print("Cancelado.")
        if ctrl is not None:
            if args.marcha:
                ctrl.maquina_lista()
                print("  -> MARCHA enviada (pulso de START).")
            else:
                ctrl.maquina_pausada()
                print("  -> PARO latcheado.")

    # ------------------------------------------------------------------
    # Muestreo en vivo
    # ------------------------------------------------------------------
    print()
    print("  hora     | J1  J2  J3  J4 (PC->PLC) | O1  O2  O3  O4 (PLC->PC)"
          " | contador(O1) | delta")
    print("  " + "-" * 100)

    anterior = None
    inicio = time.time()
    try:
        while True:
            ahora = time.time()
            if args.duracion and (ahora - inicio) >= args.duracion:
                break
            j = _leer(cli, J_BASE)
            o = _leer(cli, O_BASE)
            base = _contador16(o)
            base = 0 if base is None else base
            delta = 0 if anterior is None else base - anterior
            anterior = base
            extra = ""
            if ctrl is not None:
                extra = f" | app: {ctrl.cortes_totales():>6} cortes"
            if o is not None and len(o) > 1 and o[1] != 0:
                extra += "  [O2 = pulso del PLC: NO es la palabra alta del contador]"
            print(f"  {time.strftime('%H:%M:%S')} | {_linea_palabras(j, 'J')} "
                  f"| {_linea_palabras(o, 'O')} | "
                  f"{str(base):>11} | {delta:>5}{extra}")
            time.sleep(args.periodo)
    except KeyboardInterrupt:
        print("\n  (Ctrl+C: saliendo)")
    finally:
        if ctrl is not None:
            ctrl.cleanup()
        cli.close()
    print("  Fin del monitoreo.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

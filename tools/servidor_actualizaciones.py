#!/usr/bin/env python
"""
servidor_actualizaciones.py - Servidor HTTP estatico de actualizaciones
(solo stdlib, sin dependencias ni instalacion).

Sirve la carpeta de releases (manifest.json + WTSControl-<version>.zip).
Se enciende SOLO cuando se publica una actualizacion: con el servidor
apagado, las PCs simplemente corren la version que ya tienen instalada
(es el interruptor de seguridad del rollout).

Uso:
    venv\\Scripts\\python tools\\servidor_actualizaciones.py [--carpeta release] [--puerto 8080]

La carpeta por defecto es `release/` en la raiz del proyecto: ahi se copian
el manifest.json y el zip generados por `hacer_manifest.py`. En produccion,
la PC servidora debe tener abierto el puerto en el firewall (regla de
entrada TCP) y las fanless apuntar a http://<ip>:<puerto> en UPDATE_SOURCE.
"""

import argparse
import functools
import http.server
import os
import socketserver


def main():
    parser = argparse.ArgumentParser(description="Servidor HTTP de actualizaciones")
    parser.add_argument(
        "--carpeta", default=os.path.join("release"),
        help="Carpeta con manifest.json + zips (default: release)",
    )
    parser.add_argument("--puerto", type=int, default=8080)
    args = parser.parse_args()

    carpeta = os.path.abspath(args.carpeta)
    os.makedirs(carpeta, exist_ok=True)
    if not os.path.exists(os.path.join(carpeta, "manifest.json")):
        print(f"AVISO: no hay manifest.json en {carpeta}.")
        print("Publica primero con: venv\\Scripts\\python tools\\hacer_manifest.py <version>")
        print()

    handler = functools.partial(
        http.server.SimpleHTTPRequestHandler, directory=carpeta
    )
    with socketserver.ThreadingTCPServer(("0.0.0.0", args.puerto), handler) as httpd:
        print(f"Servidor de actualizaciones en http://0.0.0.0:{args.puerto}/")
        print(f"Sirviendo: {carpeta}")
        print("Ctrl+C para apagar.")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nServidor apagado.")


if __name__ == "__main__":
    main()
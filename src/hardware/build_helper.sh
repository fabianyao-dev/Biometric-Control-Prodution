#!/usr/bin/env bash
# Compila fp_helper contra libfprint 2.
# Uso: bash build_helper.sh  (desde src/hardware)
set -euo pipefail

cd "$(dirname "$0")"

if ! pkg-config --exists libfprint-2; then
    echo "ERROR: libfprint-2 no encontrado. Instala primero:" >&2
    echo "  sudo apt install libfprint-2-dev" >&2
    exit 1
fi

mkdir -p bin
gcc -O2 -Wall -Wextra -o bin/fp_helper fp_helper.c \
    $(pkg-config --cflags --libs libfprint-2)

echo "OK: bin/fp_helper compilado."

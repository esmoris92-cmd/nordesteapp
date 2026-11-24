#!/usr/bin/env bash
# Cuenta del dueño del sistema en la base LOCAL (para probar en la Mac).
#   bash scripts/dueno-sistema.sh crear --correo vos@ejemplo.com --nombre "Tu Nombre"
#   bash scripts/dueno-sistema.sh restablecer --correo vos@ejemplo.com
#   bash scripts/dueno-sistema.sh listar
# Para el servidor usá: bash scripts/servidor/dueno-sistema.sh (mismos comandos).
set -euo pipefail
cd "$(dirname "$0")/../backend"
if [ ! -x .venv/bin/python ]; then
  echo "❌ Falta el entorno virtual del backend. Ver docs/INSTALACION.md, paso 2."
  exit 1
fi
exec .venv/bin/python -m app.dueno_sistema "$@"

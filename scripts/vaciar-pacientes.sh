#!/usr/bin/env bash
# Borra TODOS los pacientes de la base LOCAL (y lo que depende de ellos) para dejar Lumen
# limpio antes de mostrarlo. Conserva la clínica, las sucursales, los usuarios y sus horarios.
#   bash scripts/vaciar-pacientes.sh
# Hace antes una copia de seguridad en ~/MedFlow-copias y pide escribir BORRAR PACIENTES.
# Lumen tiene que estar detenido (Control + C en su Terminal).
set -euo pipefail
cd "$(dirname "$0")/../backend"

if [ ! -x .venv/bin/python ]; then
  echo "❌ Falta el entorno virtual del backend. Ver docs/INSTALACION.md, paso 2."
  exit 1
fi
# pg_dump (para la copia de seguridad) viene con Postgres.app.
if ! command -v pg_dump >/dev/null 2>&1 && [ -d /Applications/Postgres.app/Contents/Versions/latest/bin ]; then
  export PATH="/Applications/Postgres.app/Contents/Versions/latest/bin:$PATH"
fi
umask 077
exec .venv/bin/python -m app.vaciar_pacientes "$@"

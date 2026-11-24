#!/usr/bin/env bash
# Copias de seguridad de Nordeste (base de datos + archivos adjuntos).
#   bash scripts/copia-seguridad.sh                     crea una copia
#   bash scripts/copia-seguridad.sh verificar           prueba restaurar la última copia
#   bash scripts/copia-seguridad.sh verificar ARCHIVO   prueba restaurar esa copia
#   bash scripts/copia-seguridad.sh restaurar ARCHIVO   vuelve la base a esa copia (pide confirmación)
# Funciona desde cualquier carpeta. Las copias se guardan en ~/MedFlow-copias (fuera del proyecto).
set -euo pipefail
cd "$(dirname "$0")/../backend"

if [ ! -x .venv/bin/python ]; then
  echo "❌ Falta el entorno virtual del backend. Ver docs/INSTALACION.md, paso 2."
  exit 1
fi
# Las herramientas de PostgreSQL (pg_dump, pg_restore) vienen con Postgres.app.
if ! command -v pg_dump >/dev/null 2>&1 && [ -d /Applications/Postgres.app/Contents/Versions/latest/bin ]; then
  export PATH="/Applications/Postgres.app/Contents/Versions/latest/bin:$PATH"
fi
umask 077  # todo lo que se cree aquí queda solo para tu usuario
exec .venv/bin/python -m app.backup "$@"

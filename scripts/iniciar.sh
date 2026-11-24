#!/usr/bin/env bash
# Arranca Nordeste (API + interfaz) en http://localhost:8000
# Funciona desde cualquier carpeta. Para detenerlo: Ctrl + C.
set -euo pipefail
cd "$(dirname "$0")/../backend"

if [ ! -f .venv/bin/activate ]; then
  echo "❌ Falta el entorno virtual del backend. Ver docs/INSTALACION.md, paso 2."
  exit 1
fi
if [ ! -f ../frontend/dist/index.html ]; then
  echo "⚠️  La interfaz no está compilada. En otra Terminal ejecutá:"
  echo "    cd $(cd ../frontend && pwd) && npm run build"
  echo "   y luego volvé a ejecutar este script."
  exit 1
fi
if lsof -iTCP:8000 -sTCP:LISTEN >/dev/null 2>&1; then
  echo "❌ El puerto 8000 ya está en uso: probablemente Nordeste ya está encendido en otra"
  echo "   ventana de la Terminal. Andá a esa ventana y apretá Ctrl + C para detenerlo."
  exit 1
fi

source .venv/bin/activate
echo "▶️  Iniciando Nordeste en http://localhost:8000  (Ctrl + C para detenerlo)"
exec uvicorn app.main:app --reload --no-access-log

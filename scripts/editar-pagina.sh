#!/usr/bin/env bash
# Abre el editor de textos de la página promocional (sitio/index.html) en el navegador.
#
#   bash scripts/editar-pagina.sh
#
# Hacés clic en cualquier texto, lo cambiás y tocás «Guardar cambios». Los cambios quedan
# en sitio/index.html de esta Mac; para publicarlos: bash scripts/publicar-pagina.sh
# Para cerrar el editor: Control + C en esta ventana de la Terminal.
set -euo pipefail
cd "$(dirname "$0")/.."

if ! command -v python3 >/dev/null 2>&1; then
  echo "❌ No encuentro python3 en esta Mac."; exit 1
fi
exec python3 scripts/editor-pagina/servidor.py

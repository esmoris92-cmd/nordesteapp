#!/usr/bin/env bash
# Arranca Nordeste para usarlo desde OTROS equipos conectados al MISMO Wi-Fi o red
# (por ejemplo, para una demostración). Para detenerlo: Ctrl + C.
#
#   bash scripts/iniciar-red.sh
#
# Importante:
# * Solo con datos ficticios: la conexión dentro de la red NO va cifrada (http, sin "s").
# * Cualquiera conectado a esa red puede abrir la pantalla de ingreso. No lo uses en un
#   Wi-Fi público ni en el de pacientes.
# * Para el uso diario en tu Mac sigue usando: bash scripts/iniciar.sh (solo esta Mac).
set -euo pipefail
cd "$(dirname "$0")/../backend"
PORT=8000

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
if lsof -iTCP:$PORT -sTCP:LISTEN >/dev/null 2>&1; then
  echo "❌ El puerto $PORT ya está en uso: probablemente Nordeste ya está encendido en otra"
  echo "   ventana de la Terminal. Andá a esa ventana y apretá Ctrl + C para detenerlo."
  exit 1
fi

# Dirección de esta Mac en la red (Wi-Fi o cable).
IP=""
if command -v ipconfig >/dev/null 2>&1; then
  for iface in en0 en1 en2 en3 en4 en5; do
    IP="$(ipconfig getifaddr "$iface" 2>/dev/null || true)"
    [ -n "$IP" ] && break
  done
fi
if [ -z "$IP" ] && command -v hostname >/dev/null 2>&1; then
  IP="$(hostname -I 2>/dev/null | awk '{print $1}' || true)"
fi
if [ -z "$IP" ]; then
  echo "❌ Esta computadora no parece estar conectada a una red (Wi-Fi o cable)."
  exit 1
fi

source .venv/bin/activate
echo ""
echo "▶️  Nordeste está abierto en la red. Desde otro equipo del MISMO Wi-Fi, abrí:"
echo ""
echo "        http://$IP:$PORT"
echo ""
echo "   En esta Mac también funciona http://localhost:$PORT"
echo "   ⚠️  Solo datos ficticios: dentro de la red la conexión no va cifrada."
echo "   ⚠️  Si macOS pregunta si permitir conexiones entrantes, elegí \"Permitir\"."
echo "   Para cerrarlo: Ctrl + C (los demás equipos dejan de poder entrar)."
echo ""
exec uvicorn app.main:app --host 0.0.0.0 --port $PORT --no-access-log

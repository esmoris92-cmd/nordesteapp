#!/usr/bin/env bash
# Abre Lumen por internet con un enlace TEMPORAL (Cloudflare Quick Tunnel), para
# mostrarlo desde otra sucursal. SOLO PARA DEMOSTRACIONES CON DATOS FICTICIOS.
#
#   bash scripts/demo-internet.sh
#
# * No necesita cuenta de Cloudflare ni tiene costo. El enlace (https://….trycloudflare.com)
#   cambia cada vez y deja de funcionar al cerrar con Ctrl + C.
# * Mientras está abierto, CUALQUIERA que tenga el enlace llega a la pantalla de ingreso.
#   Por eso el script no arranca si alguna cuenta usa todavía la contraseña de demostración.
# * Cloudflare lo ofrece para pruebas, sin garantía de funcionamiento: no es para el uso real.
set -euo pipefail
cd "$(dirname "$0")/../backend"
PORT=8000
TOOLS="$HOME/MedFlow-herramientas"

# 1. El programa cloudflared (se descarga a mano, una sola vez; ver docs/INSTALACION.md).
CLOUDFLARED="$TOOLS/cloudflared"
if [ ! -x "$CLOUDFLARED" ]; then
  CLOUDFLARED="$(command -v cloudflared || true)"
fi
if [ -z "$CLOUDFLARED" ]; then
  case "$(uname -m)" in
    arm64) ARCH=arm64 ;;
    *) ARCH=amd64 ;;
  esac
  echo "❌ Falta el programa cloudflared. Descargalo una sola vez con estos comandos:"
  echo ""
  echo "    mkdir -p ~/MedFlow-herramientas && cd ~/MedFlow-herramientas"
  echo "    curl -L -o cloudflared.tgz https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-darwin-$ARCH.tgz"
  echo "    tar xzf cloudflared.tgz && rm cloudflared.tgz && chmod +x cloudflared"
  echo ""
  echo "   y volvé a ejecutar: bash scripts/demo-internet.sh"
  exit 1
fi

# 2. Lo mismo que el arranque normal.
if [ ! -f .venv/bin/activate ]; then
  echo "❌ Falta el entorno virtual del backend. Ver docs/INSTALACION.md, paso 2."
  exit 1
fi
if [ ! -f ../frontend/dist/index.html ]; then
  echo "⚠️  La interfaz no está compilada. Ejecutá: cd $(cd ../frontend && pwd) && npm run build"
  exit 1
fi
if lsof -iTCP:$PORT -sTCP:LISTEN >/dev/null 2>&1; then
  echo "❌ El puerto $PORT ya está en uso: probablemente Lumen ya está encendido en otra"
  echo "   ventana de la Terminal. Andá a esa ventana y apretá Ctrl + C para detenerlo."
  exit 1
fi
source .venv/bin/activate

# 3. Ninguna cuenta con la contraseña de demostración (es pública: figura en el README).
python -m app.demo_check || exit 1

# 4. Confirmación explícita.
echo ""
echo "⚠️  Vas a abrir Lumen por INTERNET con un enlace temporal."
echo "   - Úsalo SOLO si la base tiene datos ficticios (nada de pacientes reales)."
echo "   - Quien tenga el enlace llega a la pantalla de ingreso mientras esté abierto."
read -r -p "   Escribí SI (en mayúsculas) para continuar: " answer
if [ "$answer" != "SI" ]; then
  echo "Cancelado: no se abrió nada."
  exit 0
fi

LOG="$(mktemp -t medflow-tunel.XXXXXX)"
cleanup() {
  [ -n "${TUNNEL_PID:-}" ] && kill "$TUNNEL_PID" 2>/dev/null || true
  [ -n "${APP_PID:-}" ] && kill "$APP_PID" 2>/dev/null || true
  rm -f "$LOG"
  echo ""
  echo "⏹  Lumen cerrado: el enlace ya no funciona."
}
trap cleanup EXIT
trap 'exit 130' INT TERM

# Lumen solo escucha en esta Mac; el túnel lo lleva a internet con HTTPS.
COOKIE_SECURE=true uvicorn app.main:app --host 127.0.0.1 --port $PORT --no-access-log &
APP_PID=$!
"$CLOUDFLARED" tunnel --no-autoupdate --url "http://localhost:$PORT" >"$LOG" 2>&1 &
TUNNEL_PID=$!

URL=""
for _ in $(seq 1 60); do
  URL="$(grep -Eo 'https://[a-z0-9-]+\.trycloudflare\.com' "$LOG" | head -n 1 || true)"
  [ -n "$URL" ] && break
  if ! kill -0 "$TUNNEL_PID" 2>/dev/null; then break; fi
  sleep 1
done
if [ -z "$URL" ]; then
  echo "❌ No se pudo crear el enlace. Últimas líneas de cloudflared:"
  tail -n 15 "$LOG"
  exit 1
fi

echo ""
echo "✅ Lumen está abierto por internet. Compartí este enlace (solo con quien corresponda):"
echo ""
echo "        $URL"
echo ""
echo "   También úsalo en esta Mac (con https la sesión funciona mejor que con localhost)."
echo "   Para cerrarlo: Ctrl + C."
wait "$TUNNEL_PID"

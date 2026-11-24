#!/usr/bin/env bash
# Copias de seguridad AUTOMÁTICAS de Lumen, una vez por día (usa launchd, que trae macOS).
#
#   bash scripts/copias-automaticas.sh instalar         activa la copia diaria a las 22:00
#   bash scripts/copias-automaticas.sh instalar 13:30   activa la copia diaria a esa hora
#   bash scripts/copias-automaticas.sh estado           muestra si está activa y el último registro
#   bash scripts/copias-automaticas.sh desinstalar      la desactiva (no borra ninguna copia)
#
# Cada copia guarda la base y los adjuntos en ~/MedFlow-copias y deja solo las 30 más
# recientes. Si a esa hora la Mac está dormida, la copia se hace al despertarla; si está
# apagada, se saltea ese día. Postgres.app tiene que estar abierto.
set -euo pipefail

LABEL="com.medflow.copia-diaria"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
PROJECT="$(cd "$(dirname "$0")/.." && pwd)"
LOG_DIR="$HOME/MedFlow-copias"
LOG="$LOG_DIR/registro.log"
KEEP=30

xml_escape() { sed -e 's/&/\&amp;/g' -e 's/</\&lt;/g' -e 's/>/\&gt;/g'; }

instalar() {
  local hora="${1:-22:00}"
  if ! [[ "$hora" =~ ^([01][0-9]|2[0-3]):([0-5][0-9])$ ]]; then
    echo "❌ La hora debe tener el formato HH:MM (por ejemplo 22:00)."
    exit 1
  fi
  local hh=$((10#${BASH_REMATCH[1]})) mm=$((10#${BASH_REMATCH[2]}))
  if [ ! -x "$PROJECT/backend/.venv/bin/python" ]; then
    echo "❌ Falta el entorno virtual del backend. Ver docs/INSTALACION.md, paso 2."
    exit 1
  fi
  mkdir -p "$HOME/Library/LaunchAgents" "$LOG_DIR"
  chmod 700 "$LOG_DIR"
  local script
  script="$(printf '%s' "$PROJECT/scripts/copia-seguridad.sh" | xml_escape)"
  local log_xml
  log_xml="$(printf '%s' "$LOG" | xml_escape)"
  cat > "$PLIST" <<PLISTEOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>$script</string>
    <string>crear</string>
    <string>--conservar</string>
    <string>$KEEP</string>
  </array>
  <key>StartCalendarInterval</key>
  <dict><key>Hour</key><integer>$hh</integer><key>Minute</key><integer>$mm</integer></dict>
  <key>StandardOutPath</key><string>$log_xml</string>
  <key>StandardErrorPath</key><string>$log_xml</string>
</dict>
</plist>
PLISTEOF
  chmod 600 "$PLIST"
  if command -v plutil >/dev/null 2>&1; then plutil -lint "$PLIST" >/dev/null; fi
  # Si ya estaba activa, se reemplaza.
  launchctl bootout "gui/$(id -u)/$LABEL" >/dev/null 2>&1 || true
  launchctl bootstrap "gui/$(id -u)" "$PLIST"
  printf '✅ Copia automática activada: todos los días a las %02d:%02d.\n' "$hh" "$mm"
  echo "   Se guardan en $LOG_DIR (se conservan las $KEEP más recientes)."
  echo "   Registro de cada ejecución: $LOG"
  echo "   Para probarla ahora mismo:  launchctl kickstart gui/$(id -u)/$LABEL"
}

desinstalar() {
  launchctl bootout "gui/$(id -u)/$LABEL" >/dev/null 2>&1 || true
  if [ -f "$PLIST" ]; then
    rm "$PLIST"
  fi
  echo "✅ Copia automática desactivada. Las copias ya hechas siguen en $LOG_DIR."
}

estado() {
  if launchctl print "gui/$(id -u)/$LABEL" >/dev/null 2>&1; then
    echo "✅ La copia automática está ACTIVA ($PLIST)."
  else
    echo "ℹ️  La copia automática NO está activa. Para activarla: bash scripts/copias-automaticas.sh instalar"
  fi
  if [ -f "$LOG" ]; then
    echo "Últimas líneas del registro ($LOG):"
    tail -n 6 "$LOG"
  fi
  local ultima
  ultima="$(ls -1 "$LOG_DIR"/medflow-copia-*.tar.gz 2>/dev/null | tail -n 1 || true)"
  if [ -n "$ultima" ]; then
    echo "Copia más reciente: $ultima"
  fi
}

case "${1:-}" in
  instalar) instalar "${2:-}" ;;
  desinstalar) desinstalar ;;
  estado) estado ;;
  *)
    echo "Uso: bash scripts/copias-automaticas.sh instalar [HH:MM] | estado | desinstalar"
    exit 1
    ;;
esac

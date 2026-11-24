#!/usr/bin/env bash
# Copias de seguridad del SERVIDOR guardadas en esta Mac (fuera del servidor).
# Si la VPS se borra o se rompe, con estas copias se puede volver a armar Nordeste.
#
#   bash scripts/servidor/copias-del-servidor.sh preparar          una sola vez: llave y permiso en el servidor
#   bash scripts/servidor/copias-del-servidor.sh bajar             baja ahora la copia más reciente
#   bash scripts/servidor/copias-del-servidor.sh instalar [HH:MM]  la baja sola todos los días (por defecto 21:00)
#   bash scripts/servidor/copias-del-servidor.sh estado            si está activa, la última copia y el registro
#   bash scripts/servidor/copias-del-servidor.sh verificar [ARCH]  prueba restaurar una copia en la base de pruebas
#   bash scripts/servidor/copias-del-servidor.sh desinstalar       deja de bajarlas solo (no borra ninguna copia)
#
# Las copias quedan en ~/Nordeste-copias-servidor (se conservan las 30 más recientes). Tienen
# datos de pacientes: la Mac tiene que tener FileVault activado (disco cifrado).
set -euo pipefail

DESTINO_CONF="$(cd "$(dirname "$0")" && pwd)/destino.env"
# shellcheck disable=SC1090
[ -f "$DESTINO_CONF" ] && . "$DESTINO_CONF"
falta_destino() {
  echo "❌ Falta el servidor de Nordeste: copiá scripts/servidor/destino.env.example como"
  echo "   scripts/servidor/destino.env y completalo (o pasá las variables NORDESTE_*)."
  exit 1
}
[ -n "${NORDESTE_SERVIDOR:-}" ] && [ -n "${NORDESTE_USUARIO:-}" ] || falta_destino
SERVIDOR="$NORDESTE_SERVIDOR"
PUERTO="${NORDESTE_PUERTO:-22}"
ADMIN="$NORDESTE_USUARIO"               # tu usuario con sudo (solo para "preparar")
CUENTA="lumencopia"                       # la cuenta que solo puede bajar copias
LLAVE="$HOME/.ssh/nordeste_copias"
CARPETA="${NORDESTE_COPIAS_MAC:-$HOME/Nordeste-copias-servidor}"
CONSERVAR=30
LABEL="uy.nordeste.copias-del-servidor"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
REGISTRO="$CARPETA/registro.log"
PROYECTO="$(cd "$(dirname "$0")/../.." && pwd)"
PATRON='^medflow-copia-[0-9]{4}-[0-9]{2}-[0-9]{2}_[0-9]{6}\.tar\.gz$'

ahora() { date '+%Y-%m-%d %H:%M:%S'; }

huella() {
  if command -v shasum >/dev/null 2>&1; then shasum -a 256 "$1" | cut -d' ' -f1
  else sha256sum "$1" | cut -d' ' -f1; fi
}

ssh_copias() {
  ssh -i "$LLAVE" -p "$PUERTO" -o BatchMode=yes -o IdentitiesOnly=yes -o ConnectTimeout=20 \
      -o ServerAliveInterval=30 "$CUENTA@$SERVIDOR" "$@"
}

aviso_filevault() {
  if command -v fdesetup >/dev/null 2>&1 && ! fdesetup status 2>/dev/null | grep -q "FileVault is On"; then
    echo "⚠️  FileVault NO está activado en esta Mac: las copias (con datos de pacientes) quedarían sin"
    echo "   cifrar en el disco. Activalo en Configuración del Sistema → Privacidad y seguridad → FileVault."
  fi
}

preparar() {
  mkdir -p "$HOME/.ssh"
  chmod 700 "$HOME/.ssh"
  if [ ! -f "$LLAVE" ]; then
    # Sin frase: la usa la copia automática sin que estés. En el servidor solo sirve para bajar copias.
    ssh-keygen -q -t ed25519 -N "" -C "lumen-copias-$(hostname -s)" -f "$LLAVE"
    echo "✅ Llave creada: $LLAVE"
  else
    echo "   La llave ya existe: $LLAVE"
  fi
  local publica
  publica="$(cut -d' ' -f1,2 "$LLAVE.pub")"
  if ! [[ "$publica" =~ ^ssh-ed25519\ [A-Za-z0-9+/=]+$ ]]; then
    echo "❌ La llave pública no tiene el formato esperado."; exit 1
  fi
  echo "▶️  Autorizando la llave en el servidor (te pide la contraseña del servidor para sudo)…"
  local linea="restrict,command=\"/usr/local/bin/lumen-entregar-copia\" $publica lumen-copias-$(hostname -s)"
  ssh -t -p "$PUERTO" -o StrictHostKeyChecking=accept-new "$ADMIN@$SERVIDOR" "
    set -e
    if ! id $CUENTA >/dev/null 2>&1 || [ ! -x /usr/local/bin/lumen-entregar-copia ]; then
      echo '❌ El servidor todavía no tiene las copias automáticas. Primero: bash scripts/servidor/actualizar.sh'
      exit 1
    fi
    sudo touch /var/lib/lumencopia/.ssh/authorized_keys
    sudo grep -qF '$publica' /var/lib/lumencopia/.ssh/authorized_keys \
      || echo '$linea' | sudo tee -a /var/lib/lumencopia/.ssh/authorized_keys >/dev/null
    sudo chown $CUENTA:$CUENTA /var/lib/lumencopia/.ssh/authorized_keys
    sudo chmod 600 /var/lib/lumencopia/.ssh/authorized_keys
  "
  echo "▶️  Probando la llave…"
  if ssh_copias lista >/dev/null; then
    echo "✅ Listo: esta Mac ya puede bajar las copias del servidor."
    echo "   Siguiente paso: bash scripts/servidor/copias-del-servidor.sh bajar"
  else
    echo "❌ La llave no funcionó. Revisá los mensajes de arriba."
    exit 1
  fi
  aviso_filevault
}

bajar() {
  mkdir -p "$CARPETA"
  chmod 700 "$CARPETA"
  umask 077
  if [ ! -f "$LLAVE" ]; then
    echo "❌ Falta la llave. Primero: bash scripts/servidor/copias-del-servidor.sh preparar"; exit 1
  fi
  echo "[$(ahora)] Buscando copias en el servidor…"
  local lista ultima nombre tamano esperado
  if ! lista="$(ssh_copias lista)"; then
    echo "❌ No se pudo conectar con el servidor (¿hay internet? ¿la Mac está despierta?)."; exit 1
  fi
  ultima="$(printf '%s\n' "$lista" | grep -E '^medflow-copia-' | tail -n 1 || true)"
  if [ -z "$ultima" ]; then
    echo "❌ El servidor no tiene copias para bajar. Revisá allá: journalctl -u lumen-copia -n 30"; exit 1
  fi
  read -r nombre tamano esperado <<< "$ultima"
  if ! [[ "$nombre" =~ $PATRON ]] || ! [[ "$tamano" =~ ^[0-9]+$ ]] || ! [[ "$esperado" =~ ^[0-9a-f]{64}$ ]]; then
    echo "❌ Respuesta inesperada del servidor."; exit 1
  fi
  # Aviso si la copia más nueva del servidor es vieja: la copia nocturna podría estar fallando.
  local fecha epoca dias
  fecha="${nombre:14:10}"
  epoca="$(date -j -f %Y-%m-%d "$fecha" +%s 2>/dev/null || date -d "$fecha" +%s 2>/dev/null || true)"
  if [ -n "$epoca" ]; then
    dias=$(( ( $(date +%s) - epoca ) / 86400 ))
    if [ "$dias" -ge 2 ]; then
      echo "⚠️  La copia más nueva del servidor es de hace $dias días: revisá la copia nocturna allá."
    fi
  fi
  if [ -f "$CARPETA/$nombre" ]; then
    echo "   Ya tenías la más reciente: $nombre"
  else
    echo "   Bajando $nombre ($(( tamano / 1024 )) KB)…"
    local parcial="$CARPETA/.$nombre.parcial"
    if ! ssh_copias enviar "$nombre" > "$parcial"; then
      rm -f "$parcial"; echo "❌ Se cortó la descarga. Se vuelve a intentar la próxima vez."; exit 1
    fi
    if [ "$(huella "$parcial")" != "$esperado" ]; then
      rm -f "$parcial"; echo "❌ La copia llegó dañada (la huella SHA-256 no coincide). No se guardó."; exit 1
    fi
    chmod 600 "$parcial"
    mv "$parcial" "$CARPETA/$nombre"
    echo "✅ Copia guardada: $CARPETA/$nombre"
  fi
  # Deja solo las CONSERVAR más recientes.
  local todas total
  todas="$(ls -1 "$CARPETA"/medflow-copia-*.tar.gz 2>/dev/null | sort || true)"
  total="$(printf '%s\n' "$todas" | grep -c . || true)"
  if [ "$total" -gt "$CONSERVAR" ]; then
    printf '%s\n' "$todas" | head -n "$(( total - CONSERVAR ))" | while read -r vieja; do rm -f "$vieja"; done
    echo "   Se borraron $(( total - CONSERVAR )) copias viejas (se conservan las $CONSERVAR más recientes)."
  fi
  aviso_filevault
}

xml_escape() { sed -e 's/&/\&amp;/g' -e 's/</\&lt;/g' -e 's/>/\&gt;/g'; }

instalar() {
  local hora="${1:-21:00}"
  if ! [[ "$hora" =~ ^([01][0-9]|2[0-3]):([0-5][0-9])$ ]]; then
    echo "❌ La hora debe tener el formato HH:MM (por ejemplo 21:00)."; exit 1
  fi
  local hh=$((10#${BASH_REMATCH[1]})) mm=$((10#${BASH_REMATCH[2]}))
  if [ ! -f "$LLAVE" ]; then
    echo "❌ Falta la llave. Primero: bash scripts/servidor/copias-del-servidor.sh preparar"; exit 1
  fi
  mkdir -p "$HOME/Library/LaunchAgents" "$CARPETA"
  chmod 700 "$CARPETA"
  local script registro
  script="$(printf '%s' "$PROYECTO/scripts/servidor/copias-del-servidor.sh" | xml_escape)"
  registro="$(printf '%s' "$REGISTRO" | xml_escape)"
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
    <string>bajar</string>
  </array>
  <key>StartCalendarInterval</key>
  <dict><key>Hour</key><integer>$hh</integer><key>Minute</key><integer>$mm</integer></dict>
  <key>StandardOutPath</key><string>$registro</string>
  <key>StandardErrorPath</key><string>$registro</string>
</dict>
</plist>
PLISTEOF
  chmod 600 "$PLIST"
  if command -v plutil >/dev/null 2>&1; then plutil -lint "$PLIST" >/dev/null; fi
  launchctl bootout "gui/$(id -u)/$LABEL" >/dev/null 2>&1 || true
  launchctl bootstrap "gui/$(id -u)" "$PLIST"
  printf '✅ Activado: esta Mac baja la copia del servidor todos los días a las %02d:%02d.\n' "$hh" "$mm"
  echo "   Si a esa hora está dormida, la baja al despertarse; si está apagada, ese día se saltea."
  echo "   Registro: $REGISTRO"
  aviso_filevault
}

desinstalar() {
  launchctl bootout "gui/$(id -u)/$LABEL" >/dev/null 2>&1 || true
  [ -f "$PLIST" ] && rm "$PLIST"
  echo "✅ Ya no se bajan solas. Las copias que tenías siguen en $CARPETA."
}

estado() {
  if launchctl print "gui/$(id -u)/$LABEL" >/dev/null 2>&1; then
    echo "✅ La descarga automática está ACTIVA."
  else
    echo "ℹ️  La descarga automática NO está activa. Para activarla: bash scripts/servidor/copias-del-servidor.sh instalar"
  fi
  local ultima
  ultima="$(ls -1 "$CARPETA"/medflow-copia-*.tar.gz 2>/dev/null | sort | tail -n 1 || true)"
  if [ -n "$ultima" ]; then
    echo "Copia más reciente en esta Mac: $ultima"
    echo "Copias guardadas: $(ls -1 "$CARPETA"/medflow-copia-*.tar.gz | wc -l | tr -d ' ')"
  else
    echo "Todavía no hay copias en $CARPETA."
  fi
  if [ -f "$REGISTRO" ]; then
    echo "Últimas líneas del registro:"
    tail -n 6 "$REGISTRO"
  fi
  aviso_filevault
}

verificar() {
  local archivo="${1:-}"
  if [ -z "$archivo" ]; then
    archivo="$(ls -1 "$CARPETA"/medflow-copia-*.tar.gz 2>/dev/null | sort | tail -n 1 || true)"
    [ -n "$archivo" ] || { echo "❌ No hay copias en $CARPETA. Primero: bajar"; exit 1; }
  fi
  # Usa la base de PRUEBAS de esta Mac (la de las pruebas automáticas): no toca tus datos.
  exec bash "$PROYECTO/scripts/copia-seguridad.sh" verificar "$archivo"
}

case "${1:-}" in
  preparar) preparar ;;
  bajar) bajar ;;
  instalar) instalar "${2:-}" ;;
  estado) estado ;;
  verificar) verificar "${2:-}" ;;
  desinstalar) desinstalar ;;
  *)
    sed -n '5,10p' "$0" | sed 's/^# //'
    exit 1
    ;;
esac

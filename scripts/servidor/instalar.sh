#!/usr/bin/env bash
# Instala (o actualiza) Lumen en un servidor Ubuntu 24.04 recién creado.
# Lo ejecuta scripts/servidor/desplegar.sh desde la Mac; no hace falta correrlo a mano.
#
#   bash instalar.sh <paquete.tgz> <nombre-del-sitio> [--demo]
#
# * <nombre-del-sitio>: por ejemplo 164-90-123-45.sslip.io o medflow.tuclinica.com.uy.
#   Pueden ser varios separados por comas (el primero es el principal), por ejemplo
#   lumengestion.uy,190-64-205-231.sslip.io: Lumen responde en todos.
#   Si está "www." + el principal (www.lumengestion.uy), ese nombre redirige al principal.
# * --demo: carga los datos de demostración FICTICIOS con una contraseña nueva al azar.
# * --web=<dominio>: muestra en ese dominio la página promocional (carpeta sitio/ del
#   paquete) y hace que www.<dominio> redirija a él. Las direcciones /sistema y /api de ese
#   dominio llevan a Lumen (el nombre principal). Ejemplo: --web=lumengestion.uy
#
# Qué deja funcionando:
#   PostgreSQL (solo accesible desde el propio servidor) · Lumen como servicio que se
#   reinicia solo · Caddy con HTTPS automático (Let's Encrypt) · cortafuegos con solo
#   SSH (22), HTTP (80) y HTTPS (443) abiertos.
# Se puede volver a ejecutar para actualizar el código: la base, los archivos y la
# configuración (.env) se conservan.
set -euo pipefail

PKG="${1:-}"; SITE="${2:-}"; DEMO=""; WEB_SITE=""
for opt in "${@:3}"; do
  case "$opt" in
    --demo) DEMO="--demo" ;;
    --web=*) WEB_SITE="${opt#--web=}" ;;
    "") ;;
    *) echo "❌ Opción desconocida: $opt"; exit 1 ;;
  esac
done
if [ "$(id -u)" -ne 0 ]; then echo "❌ Ejecútalo como root."; exit 1; fi
if [ -z "$PKG" ] || [ ! -f "$PKG" ] || [ -z "$SITE" ]; then
  echo "Uso: bash instalar.sh <paquete.tgz> <nombre-del-sitio> [--demo]"; exit 1
fi
SITE="${SITE// /}"
if ! [[ "$SITE" =~ ^[a-z0-9.-]+(,[a-z0-9.-]+)*$ ]]; then
  echo "❌ Nombre de sitio no válido: $SITE (solo letras minúsculas, números, puntos y guiones; varios separados por comas)."
  exit 1
fi
if [ -n "$WEB_SITE" ] && ! [[ "$WEB_SITE" =~ ^[a-z0-9.-]+$ ]]; then
  echo "❌ Dominio de la página promocional no válido: $WEB_SITE"; exit 1
fi
MAIN_SITE="${SITE%%,*}"        # el principal: el que se prueba y se muestra al final
CADDY_SITES=""                 # los que muestran Lumen, como los escribe Caddy
REDIRECT_SITE=""               # www.<principal>: redirige al principal
IFS=, read -ra _NAMES <<< "$SITE"
for name in "${_NAMES[@]}"; do
  if [ "$name" = "www.$MAIN_SITE" ]; then
    REDIRECT_SITE="$name"
  else
    CADDY_SITES="${CADDY_SITES:+$CADDY_SITES, }$name"
  fi
done
if ! grep -q 'VERSION_ID="24.04"' /etc/os-release; then
  echo "⚠️  Este script está pensado para Ubuntu 24.04. Sigo igual, pero revisa los mensajes."
fi

BASE=/opt/medflow
APP=$BASE/app
VENV=$BASE/venv
ENV_FILE=$APP/backend/.env
step() { echo ""; echo "▶️  $*"; }

step "1/8 Instalando programas del sistema (puede tardar unos minutos)…"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3-venv python3-pip postgresql caddy ufw openssl >/dev/null

step "2/8 Cuenta del sistema y carpetas…"
id medflow >/dev/null 2>&1 || useradd --system --home-dir "$BASE" --shell /usr/sbin/nologin medflow
mkdir -p "$APP" "$BASE/archivos" "$BASE/copias"
tar xzf "$PKG" -C "$APP"   # reemplaza el código; no toca .env, archivos ni la base
if [ -n "$WEB_SITE" ] && [ ! -f "$APP/sitio/index.html" ]; then
  echo "❌ Falta sitio/index.html en el paquete: no se cambia nada más."; exit 1
fi
chown -R medflow:medflow "$BASE"
chmod 750 "$BASE" "$BASE/archivos" "$BASE/copias"

step "3/8 Entorno de Python y dependencias…"
[ -x "$VENV/bin/python" ] || sudo -u medflow python3 -m venv "$VENV"
sudo -u medflow "$VENV/bin/pip" install -q --upgrade pip
sudo -u medflow "$VENV/bin/pip" install -q -r "$APP/backend/requirements.txt"

step "4/8 Base de datos PostgreSQL…"
if [ ! -f "$ENV_FILE" ]; then
  DB_PASS="$(openssl rand -hex 24)"
  sudo -u postgres psql -qc "CREATE ROLE medflow LOGIN PASSWORD '$DB_PASS';" 2>/dev/null \
    || sudo -u postgres psql -qc "ALTER ROLE medflow PASSWORD '$DB_PASS';"
  sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='medflow'" | grep -q 1 \
    || sudo -u postgres createdb -O medflow medflow
  DEMO_PASS="Demo-$(openssl rand -hex 6)-Prueba"
  umask 077
  cat > "$ENV_FILE" <<ENVEOF
# Configuración del servidor (creada por instalar.sh). NO la compartas ni la subas a Git.
ENVIRONMENT=production
DATABASE_URL=postgresql+psycopg://medflow:$DB_PASS@localhost:5432/medflow
COOKIE_SECURE=true
SESSION_MAX_HOURS=8
SESSION_IDLE_MINUTES=60
DEMO_PASSWORD=$DEMO_PASS
FILES_DIR=$BASE/archivos
BACKUP_DIR=$BASE/copias
MAX_UPLOAD_MB=10
ENVEOF
  chown medflow:medflow "$ENV_FILE"
  chmod 600 "$ENV_FILE"
  NEW_INSTALL=1
else
  echo "   La configuración ya existe: se conserva."
  NEW_INSTALL=0
fi
cd "$APP/backend"
sudo -u medflow "$VENV/bin/python" -m alembic upgrade head

if [ "$DEMO" = "--demo" ]; then
  step "   Cargando datos de demostración FICTICIOS…"
  # El seed se niega en producción a propósito; aquí se pide de forma explícita.
  sudo -u medflow ENVIRONMENT=development "$VENV/bin/python" -m app.seed || true
fi

step "5/8 Lumen como servicio (arranca solo y se reinicia si falla)…"
cat > /etc/systemd/system/medflow.service <<UNIT
[Unit]
Description=Lumen
After=network.target postgresql.service
Requires=postgresql.service

[Service]
User=medflow
Group=medflow
WorkingDirectory=$APP/backend
ExecStart=$VENV/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 2 --proxy-headers --forwarded-allow-ips 127.0.0.1 --no-access-log
Restart=always
RestartSec=3
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ProtectHome=true

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable --quiet medflow
systemctl restart medflow

step "6/8 Copia de seguridad todas las noches (03:00, se conservan las últimas 14)…"
# Cuenta que solo puede BAJAR copias (la usa tu Mac: scripts/servidor/copias-del-servidor.sh).
# Sin contraseña; su llave queda fijada a lumen-entregar-copia (no abre una terminal).
id lumencopia >/dev/null 2>&1 || useradd --system --create-home --home-dir /var/lib/lumencopia \
  --shell /bin/sh lumencopia
install -d -m 700 -o lumencopia -g lumencopia /var/lib/lumencopia/.ssh
install -m 755 "$APP/scripts/servidor/copias/lumen-entregar-copia" /usr/local/bin/lumen-entregar-copia
install -m 755 "$APP/scripts/servidor/copias/lumen-publicar-copia" /usr/local/sbin/lumen-publicar-copia
cat > /etc/systemd/system/lumen-copia.service <<UNIT
[Unit]
Description=Copia de seguridad de Lumen (base de datos + archivos adjuntos)
After=postgresql.service
Requires=postgresql.service

[Service]
Type=oneshot
User=medflow
Group=medflow
UMask=0077
WorkingDirectory=$APP/backend
ExecStart=$VENV/bin/python -m app.backup crear --conservar 14
# "+": este paso corre como root, para dejar la copia en la carpeta de entrega.
ExecStartPost=+/usr/local/sbin/lumen-publicar-copia
UNIT
cat > /etc/systemd/system/lumen-copia.timer <<UNIT
[Unit]
Description=Copia de seguridad diaria de Lumen

[Timer]
OnCalendar=*-*-* 03:00:00 America/Montevideo
Persistent=true
RandomizedDelaySec=10min

[Install]
WantedBy=timers.target
UNIT
systemctl daemon-reload
systemctl enable --now --quiet lumen-copia.timer
if ! ls "$BASE"/copias/medflow-copia-*.tar.gz >/dev/null 2>&1; then
  echo "   Todavía no hay ninguna copia: se hace la primera ahora…"
  systemctl start lumen-copia.service || echo "⚠️  No se pudo hacer la copia: journalctl -u lumen-copia -n 30"
fi
if grep -rqsE '^[[:space:]]*AllowUsers' /etc/ssh/sshd_config /etc/ssh/sshd_config.d/ \
   && ! grep -rqsE '^[[:space:]]*AllowUsers.*[[:space:]]lumencopia([[:space:]]|$)' /etc/ssh/sshd_config /etc/ssh/sshd_config.d/; then
  echo "⚠️  SSH solo permite algunos usuarios (AllowUsers): agregá 'lumencopia' para que tu Mac pueda bajar las copias."
fi

step "7/8 HTTPS con Caddy para $CADDY_SITES${WEB_SITE:+ y la página promocional en $WEB_SITE}…"
if [ -n "$WEB_SITE" ]; then
  # Caddy no puede leer /opt/medflow (es solo de la cuenta medflow): la página va aparte.
  rm -rf /var/www/lumen-sitio
  install -d -m 755 /var/www/lumen-sitio
  cp -r "$APP/sitio/." /var/www/lumen-sitio/
  chmod -R a+rX /var/www/lumen-sitio
fi
cat > /etc/caddy/Caddyfile <<CADDY
$CADDY_SITES {
	reverse_proxy 127.0.0.1:8000
	header Strict-Transport-Security "max-age=31536000"
}
CADDY
if [ -n "$WEB_SITE" ]; then
  cat >> /etc/caddy/Caddyfile <<CADDY

$WEB_SITE {
	header Strict-Transport-Security "max-age=31536000"
	header X-Content-Type-Options "nosniff"
	@lumen path /sistema /sistema/* /api/*
	redir @lumen https://$MAIN_SITE{uri}
	root * /var/www/lumen-sitio
	try_files {path} /index.html
	file_server
}

www.$WEB_SITE {
	redir https://$WEB_SITE{uri} permanent
}
CADDY
fi
if [ -n "$REDIRECT_SITE" ]; then
  cat >> /etc/caddy/Caddyfile <<CADDY

$REDIRECT_SITE {
	redir https://$MAIN_SITE{uri} permanent
}
CADDY
fi
systemctl enable --quiet caddy
systemctl restart caddy

step "8/8 Cortafuegos: solo SSH, HTTP y HTTPS…"
ufw allow OpenSSH >/dev/null
ufw allow 80/tcp >/dev/null
ufw allow 443/tcp >/dev/null
ufw --force enable >/dev/null

echo ""
echo "   Esperando el certificado HTTPS (hasta 1 minuto)…"
ok=0
for _ in $(seq 1 30); do
  if curl -fsS -o /dev/null "https://$MAIN_SITE/api/health" 2>/dev/null; then ok=1; break; fi
  sleep 2
done

echo ""
if [ "$ok" = 1 ]; then
  echo "✅ Lumen está funcionando en:   https://$MAIN_SITE"
  if [ -n "$WEB_SITE" ]; then
    if curl -fsS -o /dev/null "https://$WEB_SITE/" 2>/dev/null; then
      echo "✅ Página promocional en:       https://$WEB_SITE"
    else
      echo "⚠️  La página promocional todavía no respondió en https://$WEB_SITE (probá en un par de minutos)."
    fi
  fi
else
  echo "⚠️  Lumen está instalado, pero el HTTPS todavía no respondió."
  echo "   Espera un par de minutos y abre https://$MAIN_SITE . Si sigue sin abrir:"
  echo "   journalctl -u caddy -n 30   y   journalctl -u medflow -n 30"
fi
if [ "$DEMO" = "--demo" ] && [ "$NEW_INSTALL" = 1 ]; then
  echo ""
  echo "   Cuentas de demostración (datos FICTICIOS): admin@aurora.demo, recepcion@aurora.demo,"
  echo "   recepcion.pando@aurora.demo, lucia@aurora.demo, mateo@aurora.demo, …"
  echo "   Contraseña de todas (anótala; no se vuelve a mostrar):  $(grep '^DEMO_PASSWORD=' "$ENV_FILE" | cut -d= -f2)"
fi

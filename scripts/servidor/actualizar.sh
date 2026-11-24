#!/usr/bin/env bash
# Actualiza Lumen en el servidor propio (VPS) con lo que está guardado en Git en esta Mac.
# Conserva la base de datos, los archivos subidos y la configuración (.env) del servidor.
#
#   bash scripts/servidor/actualizar.sh
#
# Se conecta con un usuario que tiene sudo y un puerto SSH propio. Para otro servidor,
# cambia los valores con variables, por ejemplo:
#   LUMEN_SSH=usuario@1.2.3.4 LUMEN_PUERTO=22 LUMEN_SITIO=lumen.tuclinica.com.uy bash scripts/servidor/actualizar.sh
#
# LUMEN_SITIO puede tener varios nombres separados por comas; el primero es el principal.
# Por defecto: app.lumengestion.uy y, de respaldo, la dirección sslip.io de la IP.
# LUMEN_WEB es el dominio de la página promocional (carpeta sitio/); www.<dominio> redirige
# a él. Por defecto lumengestion.uy; con LUMEN_WEB= (vacío) no se instala la página.
#
# Nunca carga datos de demostración y nunca envía .env, copias ni archivos de pacientes.
set -euo pipefail
cd "$(dirname "$0")/../.."

DESTINO="${LUMEN_SSH:-srv920@190.64.205.231}"
PUERTO="${LUMEN_PUERTO:-2200}"
SITIO="${LUMEN_SITIO:-app.lumengestion.uy,190-64-205-231.sslip.io}"
WEB="${LUMEN_WEB-lumengestion.uy}"

if [ -n "$(git status --porcelain)" ]; then
  echo "⚠️  Hay cambios sin guardar en Git: NO se envían (solo va lo guardado)."
fi
echo "   Versión a enviar: $(git log --oneline -1)"
echo "   Lumen en: https://${SITIO%%,*}${WEB:+   ·   Página promocional en: https://$WEB}"

echo "▶️  Compilando la interfaz…"
(cd frontend && npm run build >/dev/null)

echo "▶️  Preparando el paquete…"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
git archive --format=tar -o "$TMP/medflow.tar" HEAD
tar rf "$TMP/medflow.tar" frontend/dist
gzip "$TMP/medflow.tar"
echo "   $(du -h "$TMP/medflow.tar.gz" | cut -f1) listos para enviar."

echo "▶️  Enviando a $DESTINO (puerto $PUERTO)…"
scp -q -P "$PUERTO" "$TMP/medflow.tar.gz" scripts/servidor/instalar.sh "$DESTINO:~/"

echo "▶️  Instalando en el servidor (te pide la contraseña del servidor para sudo)…"
ssh -t -p "$PUERTO" "$DESTINO" "sudo bash ~/instalar.sh ~/medflow.tar.gz '$SITIO' ${WEB:+--web=$WEB} && rm -f ~/medflow.tar.gz"

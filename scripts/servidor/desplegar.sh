#!/usr/bin/env bash
# Envía Nordeste desde esta Mac a un servidor (por ejemplo, un Droplet de DigitalOcean con
# Ubuntu 24.04) y lo instala con HTTPS.
#
#   bash scripts/servidor/desplegar.sh <IP-del-servidor> [nombre-del-sitio]
#
# Ejemplos:
#   bash scripts/servidor/desplegar.sh 164.90.123.45
#       → https://164-90-123-45.sslip.io (para probar antes de tener dominio)
#   bash scripts/servidor/desplegar.sh 164.90.123.45 app.nordeste.com.uy
#       → con el dominio de la clínica (el dominio ya debe apuntar a esa IP)
#
# Usa SSH con la llave de esta Mac (ver docs/SERVIDOR.md). Envía solo lo que está guardado
# en Git más la interfaz compilada: nunca .env, copias de seguridad ni archivos de pacientes.
set -euo pipefail
cd "$(dirname "$0")/../.."

IP="${1:-}"; shift || true
SITE="${1:-}"
if ! [[ "$IP" =~ ^[0-9]{1,3}(\.[0-9]{1,3}){3}$ ]]; then
  echo "Uso: bash scripts/servidor/desplegar.sh <IP-del-servidor> [nombre-del-sitio]"
  echo "     La IP figura en el panel de DigitalOcean, junto al nombre del Droplet."
  exit 1
fi
[ -n "$SITE" ] || SITE="${IP//./-}.sslip.io"

if [ -n "$(git status --porcelain)" ]; then
  echo "⚠️  Hay cambios sin guardar en Git: NO se envían (solo va lo guardado)."
fi

echo "▶️  Compilando la interfaz…"
(cd frontend && npm run build >/dev/null)

echo "▶️  Preparando el paquete…"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
git archive --format=tar -o "$TMP/medflow.tar" HEAD
tar rf "$TMP/medflow.tar" frontend/dist
gzip "$TMP/medflow.tar"
echo "   $(du -h "$TMP/medflow.tar.gz" | cut -f1) listos para enviar."

echo "▶️  Enviando al servidor $IP (si pregunta \"Are you sure you want to continue connecting\", escribe yes)…"
scp -q "$TMP/medflow.tar.gz" scripts/servidor/instalar.sh "root@$IP:/root/"

echo "▶️  Instalando en el servidor…"
ssh -t "root@$IP" "bash /root/instalar.sh /root/medflow.tar.gz '$SITE' && rm -f /root/medflow.tar.gz"

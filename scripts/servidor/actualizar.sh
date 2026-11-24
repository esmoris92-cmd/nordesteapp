#!/usr/bin/env bash
# Actualiza Nordeste en el servidor propio (VPS) con lo que está guardado en Git en esta Mac.
# Conserva la base de datos, los archivos subidos y la configuración (.env) del servidor.
#
#   bash scripts/servidor/actualizar.sh
#
# Se conecta con un usuario que tiene sudo. El servidor y el sitio salen de
# scripts/servidor/destino.env (ver destino.env.example): no hay valores por defecto, para
# no enviar nunca esta copia a otro servidor por error.
#
# Nunca carga datos de demostración y nunca envía .env, copias ni archivos de pacientes.
set -euo pipefail
cd "$(dirname "$0")/../.."

DESTINO_CONF="$(cd "$(dirname "$0")" && pwd)/destino.env"
# shellcheck disable=SC1090
[ -f "$DESTINO_CONF" ] && . "$DESTINO_CONF"
falta_destino() {
  echo "❌ Falta el servidor de Nordeste: copiá scripts/servidor/destino.env.example como"
  echo "   scripts/servidor/destino.env y completalo (o pasá las variables NORDESTE_*)."
  exit 1
}
[ -n "${NORDESTE_SERVIDOR:-}" ] && [ -n "${NORDESTE_USUARIO:-}" ] && [ -n "${NORDESTE_SITIO:-}" ] || falta_destino
DESTINO="$NORDESTE_USUARIO@$NORDESTE_SERVIDOR"
PUERTO="${NORDESTE_PUERTO:-22}"
SITIO="$NORDESTE_SITIO"

if [ -n "$(git status --porcelain)" ]; then
  echo "⚠️  Hay cambios sin guardar en Git: NO se envían (solo va lo guardado)."
fi
echo "   Versión a enviar: $(git log --oneline -1)"
echo "   Nordeste en: https://${SITIO%%,*}"

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
ssh -t -p "$PUERTO" "$DESTINO" "sudo bash ~/instalar.sh ~/medflow.tar.gz '$SITIO' && rm -f ~/medflow.tar.gz"

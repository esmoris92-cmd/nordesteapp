#!/usr/bin/env bash
# Cuenta del dueño del sistema EN EL SERVIDOR, ejecutado desde la Mac.
#   bash scripts/servidor/dueno-sistema.sh crear --correo vos@ejemplo.com --nombre "Tu Nombre"
#   bash scripts/servidor/dueno-sistema.sh restablecer --correo vos@ejemplo.com
#   bash scripts/servidor/dueno-sistema.sh listar
# Se conecta por SSH (pide la contraseña del servidor para sudo) y usa la versión de Nordeste
# que ya está instalada allá: primero actualizá con scripts/servidor/actualizar.sh.
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
DESTINO="$NORDESTE_USUARIO@$NORDESTE_SERVIDOR"
PUERTO="${NORDESTE_PUERTO:-22}"
if [ $# -eq 0 ]; then
  sed -n '2,5p' "$0" | sed 's/^# //'
  exit 1
fi
ARGS="$(printf '%q ' "$@")"
# La carpeta de Nordeste solo la puede abrir la cuenta "medflow": el comando corre como ella.
ssh -t -p "$PUERTO" "$DESTINO" \
  "sudo -u medflow sh -c 'cd /opt/medflow/app/backend && exec /opt/medflow/venv/bin/python -m app.dueno_sistema \"\$@\"' dueno $ARGS"

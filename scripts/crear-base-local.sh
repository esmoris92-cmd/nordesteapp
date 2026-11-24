#!/usr/bin/env bash
# Crea la base de datos LOCAL de Nordeste (solo para desarrollo, con datos ficticios):
#   - el usuario "medflow" con una contraseña aleatoria nueva
#   - las bases "medflow" y "medflow_test"
#   - el archivo backend/.env con esa contraseña (no se sube a Git)
# La contraseña no se muestra en pantalla.
set -euo pipefail

cd "$(dirname "$0")/.."
ENV_FILE="backend/.env"

PSQL="$(command -v psql || true)"
if [ -z "$PSQL" ] && [ -x /Applications/Postgres.app/Contents/Versions/latest/bin/psql ]; then
  PSQL=/Applications/Postgres.app/Contents/Versions/latest/bin/psql
fi
if [ -z "$PSQL" ]; then
  echo "❌ No encuentro psql. Instalá y abrí Postgres.app (docs/INSTALACION.md, paso 1)."
  exit 1
fi
if ! "$PSQL" -d postgres -tAc "SELECT 1" >/dev/null 2>&1; then
  echo "❌ PostgreSQL no responde. Abrí Postgres.app y verificá que diga 'Running'."
  exit 1
fi

if [ -f "$ENV_FILE" ]; then
  echo "ℹ️  Ya existe $ENV_FILE. No cambio nada para no pisar tu configuración."
  echo "   Si querés empezar de cero, renombralo y volvé a ejecutar este script."
  exit 0
fi

PASSWORD="$(openssl rand -hex 16)"

if [ "$("$PSQL" -d postgres -tAc "SELECT 1 FROM pg_roles WHERE rolname='medflow'")" = "1" ]; then
  echo "ℹ️  El usuario 'medflow' ya existía: le asigno una contraseña nueva."
  "$PSQL" -d postgres -q -v ON_ERROR_STOP=1 -v pw="$PASSWORD" <<'SQL'
ALTER ROLE medflow WITH LOGIN PASSWORD :'pw';
SQL
else
  "$PSQL" -d postgres -q -v ON_ERROR_STOP=1 -v pw="$PASSWORD" <<'SQL'
CREATE ROLE medflow LOGIN PASSWORD :'pw';
SQL
  echo "✅ Usuario 'medflow' creado."
fi

for db in medflow medflow_test; do
  if [ "$("$PSQL" -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='$db'")" = "1" ]; then
    echo "ℹ️  La base '$db' ya existía; la dejo como está."
  else
    "$PSQL" -d postgres -q -v ON_ERROR_STOP=1 -c "CREATE DATABASE $db OWNER medflow;"
    echo "✅ Base '$db' creada."
  fi
done

sed "s/cambia-esta-clave-local/$PASSWORD/g" backend/.env.example > "$ENV_FILE"
chmod 600 "$ENV_FILE"
echo "✅ Archivo $ENV_FILE creado (está en .gitignore: no se sube a GitHub)."
echo
echo "Listo. Siguiente paso: instalar el backend (docs/INSTALACION.md, paso 2)."

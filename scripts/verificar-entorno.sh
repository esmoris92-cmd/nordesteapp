#!/usr/bin/env bash
# Muestra las versiones de las herramientas que necesita Nordeste.
# Solo LEE información: no instala, no cambia ni muestra secretos.

ok()   { printf "✅ %-12s %s\n" "$1" "$2"; }
warn() { printf "⚠️  %-12s %s\n" "$1" "$2"; }

echo "Nordeste — verificación del entorno"
echo "Sistema: macOS $(sw_vers -productVersion 2>/dev/null || echo '?') · arquitectura $(uname -m)"
echo

if command -v python3 >/dev/null; then
  v=$(python3 -c 'import sys; print("%d.%d.%d" % sys.version_info[:3])')
  if python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'; then ok Python "$v"
  else warn Python "$v (se necesita 3.11 o superior)"; fi
else warn Python "no encontrado"; fi

if command -v node >/dev/null; then
  v=$(node --version)
  major=${v#v}; major=${major%%.*}
  if [ "$major" -ge 20 ]; then ok Node "$v"; else warn Node "$v (se necesita 20 o superior)"; fi
else warn Node "no encontrado"; fi

if command -v npm >/dev/null; then ok npm "$(npm --version)"; else warn npm "no encontrado"; fi
if command -v git >/dev/null; then ok Git "$(git --version | awk '{print $3}')"; else warn Git "no encontrado"; fi

if command -v psql >/dev/null; then ok PostgreSQL "$(psql --version | awk '{print $3}') (cliente psql)"
else warn PostgreSQL "psql no encontrado (ver docs/INSTALACION.md, paso 1)"; fi

if command -v brew >/dev/null; then
  echo "ℹ️  Homebrew     $(brew --version 2>/dev/null | head -1) en $(command -v brew) (Nordeste no lo necesita)"
fi

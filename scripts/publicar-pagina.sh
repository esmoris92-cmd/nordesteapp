#!/usr/bin/env bash
# Publica en https://lumengestion.uy los cambios de la página promocional.
#
#   bash scripts/publicar-pagina.sh
#
# 1. Muestra qué cambió en sitio/ y pide confirmación.
# 2. Lo guarda en Git (commit) a nombre de Juan Esmoris.
# 3. Lo sube al servidor con scripts/servidor/actualizar.sh (pide la contraseña del servidor).
# 4. Pregunta si respaldarlo en GitHub (git push).
# Solo guarda archivos de la carpeta sitio/; si hay otros cambios sin guardar, avisa y no los toca.
set -euo pipefail
cd "$(dirname "$0")/.."

if [ -z "$(git status --porcelain -- sitio)" ]; then
  echo "ℹ️  No hay cambios nuevos en la página para publicar."
  echo "   (Si ya hiciste el commit y solo falta subirlo: bash scripts/servidor/actualizar.sh)"
  exit 0
fi

OTROS="$(git status --porcelain | grep -v ' sitio/' || true)"
if [ -n "$OTROS" ]; then
  echo "⚠️  Hay otros cambios sin guardar fuera de sitio/ (no se incluyen en esta publicación):"
  echo "$OTROS" | sed 's/^/     /'
  echo ""
fi

echo "▶️  Cambios en la página:"
git --no-pager diff --stat -- sitio
git status --porcelain -- sitio | grep '^??' | sed 's/^?? /     nuevo: /' || true
echo ""
read -r -p "¿Publicar estos cambios en lumengestion.uy? (s/n) " RESPUESTA
case "$RESPUESTA" in
  s|S|si|sí|SI|Sí) ;;
  *) echo "   No se publicó nada."; exit 0 ;;
esac

read -r -p "Contá en pocas palabras qué cambiaste (Enter para usar «textos de la página»): " QUE
QUE="${QUE:-textos de la página}"

git add -- sitio
git -c user.name="Juan Esmoris" -c user.email="esmoris92@gmail.com" commit -q -m "fix: $QUE (página promocional)"
echo "✅ Guardado en Git: $(git log --oneline -1)"
echo ""

bash scripts/servidor/actualizar.sh

echo ""
read -r -p "¿Respaldar también en GitHub (git push)? (s/n) " PUSH
case "$PUSH" in
  s|S|si|sí|SI|Sí) git push ;;
  *) echo "   Sin git push. Acordate de hacerlo después." ;;
esac

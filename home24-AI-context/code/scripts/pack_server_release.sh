#!/usr/bin/env bash
# Собирает ZIP для выкладки на Ubuntu (/opt/home24).
# Не кладёт .env, .venv, сессии, сырые БД.
# Пример:
#   bash scripts/pack_server_release.sh
#   scp /tmp/home24-release-*.zip root@SERVER:/root/home24.zip
#   # на сервере: bash /opt/home24/deploy/install_ubuntu.sh /root/home24.zip
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
BUILD="$(PYTHONPATH="$ROOT" python3 -c "from bot.version import BUILD; print(BUILD)" 2>/dev/null || echo "dev")"
STAMP="$(date +%Y%m%d-%H%M)"
SAFE_BUILD="$(echo "$BUILD" | sed 's/ · /-/g; s/[ ·/]/-/g' | tr -cd 'A-Za-z0-9._-' | tr -s '-')"
OUT_DIR="${OUT_DIR:-/tmp}"
OUT_ZIP="${OUT_ZIP:-$OUT_DIR/home24-release-${SAFE_BUILD}-${STAMP}.zip}"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

echo "== Stage $STAGE"
mkdir -p "$STAGE/home24"
# без rsync: копируем дерево и чистим лишнее
cp -a "$ROOT"/. "$STAGE/home24/"
rm -rf "$STAGE/home24/.venv" "$STAGE/home24/.git" "$STAGE/home24/logs" "$STAGE/home24/uploads"
find "$STAGE/home24" -type d -name '__pycache__' -prune -exec rm -rf {} + 2>/dev/null || true
find "$STAGE/home24" -type f \( -name '*.pyc' -o -name '.env' -o -name '*.db' -o -name '*.session' -o -name '*.session-journal' \) -delete 2>/dev/null || true
rm -rf "$STAGE/home24/data/locks" 2>/dev/null || true

# гарантируем data/ и RAG-флаги в примере env
mkdir -p "$STAGE/home24/data" "$STAGE/home24/logs"
if [ -f "$STAGE/home24/.env.example" ]; then
  grep -q 'RAG_OFF' "$STAGE/home24/.env.example" || true
fi

# Плоский корень ZIP (= содержимое /opt/home24), как ждёт install_ubuntu.sh
(
  cd "$STAGE/home24"
  zip -qr "$OUT_ZIP" . \
    -x './.venv/*' './**/__pycache__/*' './.env'
)

# копия в artifacts агента, если есть
ART="/opt/cursor/artifacts"
if [ -d "$ART" ]; then
  cp -f "$OUT_ZIP" "$ART/"
  echo "== Artifact: $ART/$(basename "$OUT_ZIP")"
fi

echo "== Ready: $OUT_ZIP"
echo "Сборка: $BUILD"
echo
echo "Дальше на сервере (после scp zip + data + .env):"
echo "  bash deploy/install_ubuntu.sh /root/home24.zip"
echo "  systemctl start home24"

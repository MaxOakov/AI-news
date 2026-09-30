#!/usr/bin/env bash
# Збирає прод-образ бота й пушить його в Docker Hub.
#
#   ./build.sh             перевірки → тести → збірка → push → перевірка в Docker Hub
#   ./build.sh --no-push   те саме, але образ лише завантажується локально (для перевірки)
#
# Змінні середовища (необов'язкові):
#   IMAGE     ім'я образу           (за замовчуванням maksymdubov/ai-news-app)
#   PLATFORM  архітектура образу    (за замовчуванням linux/arm64 — OrangePi)
#   PYTHON    інтерпретатор тестів  (за замовчуванням .venv, інакше python з PATH)
set -euo pipefail

IMAGE="${IMAGE:-maksymdubov/ai-news-app}"
PLATFORM="${PLATFORM:-linux/arm64}"
RELEASE_BRANCH="main"

PUSH=1
for arg in "$@"; do
    case "$arg" in
        --no-push) PUSH=0 ;;
        -h|--help) sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "Невідомий аргумент: $arg (див. --help)" >&2; exit 2 ;;
    esac
done

cd "$(dirname "$0")"

step() { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
fail() { printf '\n\033[1;31m❌ %s\033[0m\n' "$*" >&2; exit 1; }

# ---------------------------------------------------------------- 1. Перевірки
step "Перевірка git"

branch="$(git rev-parse --abbrev-ref HEAD)"
[ "$branch" = "$RELEASE_BRANCH" ] \
    || fail "Поточна гілка '$branch'. Прод збирається лише з '$RELEASE_BRANCH'."

# Образ має відповідати коміту в тезі, тож жодних незакомічених чи нових файлів.
if [ -n "$(git status --porcelain)" ]; then
    git status --short
    fail "Є незакомічені зміни. Закомітьте або сховайте їх (git stash -u)."
fi

# Коміт із тегу має існувати на GitHub, інакше за тегом не знайти код.
git fetch --quiet origin "$RELEASE_BRANCH"
local_sha="$(git rev-parse HEAD)"
remote_sha="$(git rev-parse "origin/$RELEASE_BRANCH")"
[ "$local_sha" = "$remote_sha" ] \
    || fail "Локальний $RELEASE_BRANCH не збігається з origin/$RELEASE_BRANCH. Зробіть git pull / git push."

# prompt.txt у .gitignore, тож git його не перевіряє, а Dockerfile копіює.
[ -s prompt.txt ] || fail "Немає prompt.txt (або він порожній) — Dockerfile копіює його в образ."
echo "✅ $branch @ ${local_sha:0:7}, дерево чисте, синхронізовано з origin"

# ------------------------------------------------------------------ 2. Тести
step "Тести"

if [ -z "${PYTHON:-}" ]; then
    if   [ -x .venv/Scripts/python.exe ]; then PYTHON=.venv/Scripts/python.exe
    elif [ -x .venv/bin/python ];         then PYTHON=.venv/bin/python
    else PYTHON=python
    fi
fi
"$PYTHON" -m pytest -q -p no:cacheprovider || fail "Тести не пройшли — образ не збирається."

# ---------------------------------------------------------- 3. Збірка й push
TAG="$(date +%Y-%m-%d)-${local_sha:0:7}"
step "Збірка $IMAGE:$TAG ($PLATFORM)"

if [ "$PUSH" = 1 ]; then
    output=(--push)
else
    output=(--load)
fi

docker buildx build \
    --platform "$PLATFORM" \
    --label "org.opencontainers.image.revision=$local_sha" \
    --label "org.opencontainers.image.created=$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    -t "$IMAGE:$TAG" \
    -t "$IMAGE:latest" \
    "${output[@]}" \
    . || fail "Збірка не вдалася. Якщо помилка про доступ — виконайте docker login."

if [ "$PUSH" = 1 ]; then
    step "Перевірка образу в Docker Hub"
    docker buildx imagetools inspect "$IMAGE:$TAG" | grep -q "Platform:.*${PLATFORM}" \
        || fail "У Docker Hub немає $IMAGE:$TAG для $PLATFORM."
    echo "✅ $IMAGE:$TAG опубліковано ($PLATFORM)"
else
    echo "✅ Образ $IMAGE:$TAG зібрано локально (--no-push, у Docker Hub нічого не відправлено)"
fi

# ------------------------------------------------------------------ Підсумок
cat <<EOF

────────────────────────────────────────────────────────────
Тег релізу:  $TAG      ← запишіть, він потрібен для відкату
Коміт:       $local_sha

Деплой на OrangePi:
  docker pull $IMAGE:latest
  docker stop ai-news-app && docker rm ai-news-app
  docker run -d --name ai-news-app --restart unless-stopped \\
    --env-file ~/max/.env -v ~/max/.env:/ai-news/.env \\
    $IMAGE:latest
────────────────────────────────────────────────────────────
EOF

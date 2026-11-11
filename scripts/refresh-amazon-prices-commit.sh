#!/bin/bash
# Commit a successful Amazon price refresh on a clean, up-to-date main checkout.
# With --push, push that single commit to origin/main. Without --push, commit only.
# Does not send email. On refresh exit 2 or a failed push, prints a marked ALERT
# hook on stderr so a routine can notify Sheik.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

REFRESH_PY="$ROOT/scripts/refresh-amazon-prices.py"
ALERT_EXIT_2="ALERT:SHEIK:price-refresh:exit=2 fetch failed; existing prices still within priceValidUntil; no commit"
ALERT_PUSH_FAILED="ALERT:SHEIK:price-refresh:push-failed"

PUSH=0
for arg in "$@"; do
  case "$arg" in
    --push) PUSH=1 ;;
    *) echo "ERROR: unknown argument: $arg (only --push is accepted)" >&2; exit 1 ;;
  esac
done

die() { echo "ERROR: $*" >&2; exit 1; }

run_refresh() {
  if [[ -n "${PRICE_REFRESH_BIN:-}" ]]; then
    "$PRICE_REFRESH_BIN" --root "$ROOT"
  else
    python3 "$REFRESH_PY" --root "$ROOT"
  fi
}

revert_tree() {
  git restore --source=HEAD --staged --worktree -- . 2>/dev/null || git checkout -- .
  git clean -f -- data/amazon-prices.json swaddles >/dev/null 2>&1 || true
}

branch="$(git rev-parse --abbrev-ref HEAD)"
[[ "$branch" == "main" ]] || die "must be on main (currently $branch)"

git fetch origin
local_sha="$(git rev-parse main)"
remote_sha="$(git rev-parse origin/main)"
[[ "$local_sha" == "$remote_sha" ]] || die "main ($local_sha) != origin/main ($remote_sha); update the checkout before refreshing"

if [[ -n "$(git status --porcelain)" ]]; then
  die "working tree is not clean; refusing to refresh"
fi

set +e
run_refresh
rc=$?
set -e

if [[ "$rc" -eq 2 ]]; then
  echo "$ALERT_EXIT_2" >&2
  exit 2
fi

if [[ "$rc" -eq 1 ]]; then
  echo "ERROR: refresh exited 1; reverting the working tree; no commit" >&2
  revert_tree
  exit 1
fi

if [[ "$rc" -ne 0 && "$rc" -ne 3 ]]; then
  echo "ERROR: refresh exited $rc; reverting the working tree; no commit" >&2
  revert_tree
  exit "$rc"
fi

set +e
python3 "$REFRESH_PY" --root "$ROOT" --check-commit-diff
guard=$?
set -e
if [[ "$guard" -ne 0 ]]; then
  echo "ERROR: commit guard failed; leaving the worktree in place; no commit" >&2
  exit 1
fi

if [[ -z "$(git status --porcelain)" ]]; then
  echo "No price changes to commit."
  exit 0
fi

git add -- \
  data/amazon-prices.json \
  swaddles/rose-petal.html \
  swaddles/baby-blue.html \
  swaddles/cozy-teddy-bear.html \
  swaddles/dreamy-clouds.html \
  swaddles/little-butterfly.html \
  swaddles/pickaboo-bear.html

set +e
python3 "$REFRESH_PY" --root "$ROOT" --check-cached-index
index_guard=$?
set -e
if [[ "$index_guard" -ne 0 ]]; then
  echo "ERROR: cached index check failed; running git reset --hard HEAD; no commit" >&2
  git reset --hard HEAD
  exit 1
fi

date_et="$(TZ=America/New_York date +%F)"
git commit -m "chore(prices): refresh Amazon Buy Box prices ${date_et}"

if [[ "$PUSH" -eq 1 ]]; then
  set +e
  git push origin HEAD:main
  push_rc=$?
  set -e
  if [[ "$push_rc" -ne 0 ]]; then
    echo "$ALERT_PUSH_FAILED" >&2
    git fetch origin >/dev/null 2>&1 || true
    git reset --hard origin/main >/dev/null 2>&1 || true
    exit 1
  fi
  echo "Pushed HEAD to origin/main."
  exit 0
fi

echo "Committed locally. Push to origin/main requires --push and is gated on an explicit GO."
exit 0

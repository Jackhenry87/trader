#!/usr/bin/env bash
# Bootstrap a fresh Ubuntu VM (Oracle Always Free ARM, GCP e2-micro, any x86/ARM
# host) to run the insider-copy paper bot 24/7.
#
#   curl -fsSL <raw-url>/scripts/bootstrap-host.sh -o bootstrap.sh
#   bash bootstrap.sh <your-repo-url>
#
# Idempotent: safe to re-run. Deliberately STOPS before starting the scheduler —
# it leaves you at a verified, dry-run state and makes you take the last step by
# hand. Nothing here ever enables live trading.
set -euo pipefail

REPO_URL="${1:-}"
BRANCH="${2:-claude/add-mcp-scteyn}"
DIR="${3:-$HOME/trader}"

die() { echo "ERROR: $*" >&2; exit 1; }
say() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }

[ -n "$REPO_URL" ] || die "usage: bash bootstrap.sh <repo-url> [branch] [dir]"

say "1/5  Installing Docker"
if command -v docker >/dev/null 2>&1; then
  echo "    already installed: $(docker --version)"
else
  curl -fsSL https://get.docker.com | sh
  sudo usermod -aG docker "$USER"
  NEEDS_RELOGIN=1
fi

# Group membership does not apply to the current shell until re-login, so run
# docker via `sg docker` for the rest of this script rather than telling you to
# log out halfway through.
d() { if docker info >/dev/null 2>&1; then docker "$@"; else sg docker -c "docker $*"; fi; }

say "2/5  Fetching the code"
if [ -d "$DIR/.git" ]; then
  git -C "$DIR" fetch origin "$BRANCH"
  git -C "$DIR" checkout "$BRANCH"
  git -C "$DIR" pull --ff-only origin "$BRANCH"
else
  git clone "$REPO_URL" "$DIR"
  git -C "$DIR" checkout "$BRANCH"
fi
cd "$DIR"
echo "    on branch: $(git branch --show-current)  @ $(git rev-parse --short HEAD)"

say "3/5  Preparing .env"
if [ -f .env ]; then
  echo "    .env already exists — leaving it alone"
else
  cp .env.example .env
  cat <<'MSG'

    Created .env from the template. Fill these in now, then re-run this script:

      SEC_USER_AGENT=Your Name your.email@domain.com
      ALPACA_API_KEY=<your PAPER key>
      ALPACA_SECRET_KEY=<your PAPER secret>
      SLACK_WEBHOOK_URL=<optional, but strongly recommended>

    Leave DRY_RUN=true, ALLOW_LIVE=false, CONFIRM_LIVE=false as they are.

      nano .env

MSG
  exit 0
fi

# Fail early and clearly rather than letting the smoke test produce a confusing
# auth error.
for key in SEC_USER_AGENT ALPACA_API_KEY ALPACA_SECRET_KEY; do
  val="$(grep -E "^${key}=" .env | cut -d= -f2- | tr -d '[:space:]' || true)"
  [ -n "$val" ] || die ".env is missing a value for ${key}. Edit .env and re-run."
done
echo "    required keys present"

if [ -z "${SLACK_WEBHOOK_URL:-}" ] && ! grep -qE '^SLACK_WEBHOOK_URL=.+' .env; then
  echo "    NOTE: SLACK_WEBHOOK_URL is unset. Notifications fall back to logs only,"
  echo "          so a data outage will be silent unless you read them. Recommended."
fi

say "4/5  Building the image"
d compose build

say "5/5  Smoke test (read-only, places nothing)"
echo "    Expect real balances AND a real price. A price of 'None' means the"
echo "    data feed is broken even though the trading keys work."
echo
d compose run --rm trader account

cat <<'MSG'

────────────────────────────────────────────────────────────────────────
Verified. Nothing is running yet — that last step is yours, on purpose.

  1. Watch a dry run and read the "would buy" lines:
       docker compose run --rm trader post-open --force

  2. When those look right, set DRY_RUN=false in .env

  3. Start the scheduler:
       docker compose up -d
       docker compose logs -f

Checking on it later:
       docker compose exec trader python -m src.main report
       docker compose exec trader python -m src.main health

Expect an empty report for the first few weeks — qualifying cluster buys are a
handful a week and the max hold is 20 days. Read the signal funnel at the bottom
of `report` to tell healthy silence from a broken pipeline.
────────────────────────────────────────────────────────────────────────
MSG

if [ "${NEEDS_RELOGIN:-0}" = "1" ]; then
  echo
  echo "NOTE: Docker was installed just now. Log out and back in (or run"
  echo "      'newgrp docker') before running docker commands yourself."
fi

# Deploying the bot to run 24/7

This bot is a long-running scheduler that must be up through market opens/closes.
That means an **always-on host** — not a laptop that sleeps, and not an ephemeral
cloud dev container. Below is the minimal, reliable way to run it unattended.

> **Reminder:** it still trades **paper** by default. Nothing places a live order
> without `ALLOW_LIVE=true` **and** `CONFIRM_LIVE=true`, which this repo does not
> ship. "Going 24/7" just means the paper bot runs on a schedule reliably.

## 1. Pick a host

Anything that stays on works. Cheapest sensible options (~$4–6/mo):

- **Hetzner Cloud** CX22, **DigitalOcean** Basic Droplet, **AWS Lightsail**, or a
  spare **Raspberry Pi** at home.
- 1 vCPU / 1 GB RAM / 10 GB disk is plenty — this bot is tiny.

You need Docker on it:

```bash
curl -fsSL https://get.docker.com | sh
```

## 2. Get the code onto the host

```bash
git clone <your repo url> trader
cd trader
git checkout claude/insider-copy-trading-bot-7f125s
```

## 3. Create `.env` on the host (never commit it)

The `.env` file lives **only on the server**. Do not commit it, do not bake keys
into the image. Copy the template and fill it in:

```bash
cp .env.example .env
nano .env   # or your editor of choice
```

Fill in at minimum:

```ini
SEC_USER_AGENT=Your Name your.email@domain.com
ALPACA_API_KEY=PK...            # your PAPER key id
ALPACA_SECRET_KEY=...           # your PAPER secret
ALPACA_BASE_URL=https://paper-api.alpaca.markets
ALPACA_DATA_FEED=iex            # free/paper feed

# Start SAFE. Watch one full cycle in dry-run before flipping to real paper orders.
DRY_RUN=true
ALLOW_LIVE=false
CONFIRM_LIVE=false

# optional
SLACK_WEBHOOK_URL=
```

## 4. First: a read-only smoke test

Before starting the scheduler, confirm the container can see EDGAR and your paper
account:

```bash
docker compose run --rm trader account
docker compose run --rm trader signals --date 2024-05-10 --max-filings 40
```

You should see your paper equity and a handful of qualifying signals.

## 5. Start it 24/7

```bash
docker compose up -d --build
```

- `-d` runs it detached (survives your SSH session closing).
- `restart: unless-stopped` (already in `docker-compose.yml`) brings it back after
  a crash or host reboot.
- The scheduler runs on **America/New_York** time regardless of the host's
  timezone (set in config), firing:
  - **~4:30pm ET** — pull the day's Form 4 filings, qualify, queue.
  - **~9:40am ET** — reconcile, place queued entries, run the exit pass.
  - Weekends/holidays are skipped (cron + Alpaca clock check).

## 6. Watch it

```bash
docker compose logs -f            # live structured JSON logs
docker compose ps                 # is it up?
```

State (SQLite) persists in the `./data` volume, so restarts don't lose positions
or the processed-filings history. On boot the bot reconciles its DB against
Alpaca's real positions and logs any drift.

## 7. Flip to real paper orders (when you're ready)

After you've watched at least one post-open cycle log "would buy" lines and
they look right:

```bash
# edit .env: DRY_RUN=false
docker compose up -d            # recreates the container with the new setting
```

Now it places real **paper** orders at the open. To stop trading at any time:

```bash
docker compose down             # stops the bot; state is preserved in ./data
```

## Notes / gotchas

- **Keys rotate per paper account.** If you create a new paper account (e.g. to
  change the starting balance), generate fresh API keys and update `.env`.
- **IEX vs SIP.** Free/paper plans only include the IEX data feed; keep
  `ALPACA_DATA_FEED=iex`. SIP requires a paid subscription.
- **Timezone.** You don't need to set the host TZ — scheduling is pinned to
  `SCHEDULE_TZ=America/New_York` in config.
- **Upgrades.** `git pull && docker compose up -d --build` to redeploy new code.
- **This is not a live-trading deployment.** Live remains gated off by design.

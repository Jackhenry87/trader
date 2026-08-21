# Deploying the bot to run 24/7

This bot is a long-running scheduler that must be up through market opens/closes.
That means an **always-on host** — not a laptop that sleeps, and not an ephemeral
cloud dev container. Below is the minimal, reliable way to run it unattended.

> **Reminder:** it still trades **paper** by default. Nothing places a live order
> without `ALLOW_LIVE=true` **and** `CONFIRM_LIVE=true`, which this repo does not
> ship. "Going 24/7" just means the paper bot runs on a schedule reliably.

---

## Quickstart: Oracle Cloud "Always Free" ARM (recommended, $0)

Oracle's Always Free tier includes an Ampere A1 (ARM64) VM that costs nothing,
forever, and is far more than this bot needs. The Docker image is multi-arch, so
it runs on ARM with no changes.

### A. Create the VM

1. Sign up at <https://cloud.oracle.com> (a card is required for identity
   verification, but Always Free resources are never charged).
2. **Compute → Instances → Create instance.**
3. **Image:** Canonical **Ubuntu 22.04** (or 24.04).
4. **Shape:** click *Change shape* → **Ampere** → `VM.Standard.A1.Flex`. Set
   **1 OCPU / 6 GB RAM** (well within the always-free 4 OCPU / 24 GB allowance).
5. **SSH keys:** upload your public key (or let Oracle generate one and download
   the private key).
6. Leave networking at defaults and **Create**. Note the instance's **public IP**.

> **Capacity tip:** Always-Free ARM is popular and a region can return
> "out of host capacity." If so, try a different Availability Domain, pick a less
> busy home region at signup, or retry later — it frees up.

> **No inbound ports needed.** The bot only makes *outbound* calls (SEC + Alpaca),
> so you don't have to open any ingress rules. SSH (22) is open by default.

### B. Deploy on it

SSH in (`ssh ubuntu@<public-ip>`), then:

```bash
# Docker
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER && newgrp docker

# Code
git clone <your repo url> trader && cd trader
git checkout claude/add-mcp-scteyn

# Secrets (never committed) — fill in SEC_USER_AGENT + your PAPER keys
cp .env.example .env && nano .env

# Smoke test, then launch 24/7
docker compose run --rm trader account
docker compose up -d --build
docker compose logs -f
```

That's it — it now runs unattended on America/New_York time and restarts on
reboot. The rest of this document is the generic version of the same steps plus
day-2 operations (flipping to real paper orders, upgrades, gotchas).

---

## Quickstart: Google Cloud "Always Free" e2-micro ($0)

Google Cloud's Always Free tier includes one `e2-micro` VM that is free **forever**
(not a 12-month trial). It's x86, but the Docker image is multi-arch so nothing
changes. Two hard rules to stay in the free tier:

- **Machine type must be `e2-micro`**, and
- **the VM must live in one of these three regions:** `us-west1` (Oregon),
  `us-central1` (Iowa), or `us-east1` (South Carolina).

Only **one** free e2-micro per billing account across those regions. Use a
**standard** persistent disk (up to 30 GB is free; SSD/balanced disks are not).

### A. Create the VM (Console)

1. Sign up / sign in at <https://cloud.google.com/free> → open the **Console**.
2. Create/select a project, and enable billing (a card is required; Always-Free
   resources are not charged).
3. **Compute Engine → VM instances → Create instance.**
4. **Name:** `trader`.
5. **Region:** one of `us-west1` / `us-central1` / `us-east1`. **Zone:** any.
6. **Machine configuration:** series **E2**, machine type **`e2-micro`**.
7. **Boot disk → Change:** OS **Ubuntu**, version **Ubuntu 22.04 LTS**, boot disk
   type **Standard persistent disk**, size **30 GB**.
8. Leave firewall unchecked — the bot only makes **outbound** calls, so you do
   **not** need to allow HTTP/HTTPS. SSH works through the console.
9. **Create.**

> **CLI alternative** (if you have `gcloud`):
> ```bash
> gcloud compute instances create trader \
>   --zone=us-central1-a --machine-type=e2-micro \
>   --image-family=ubuntu-2204-lts --image-project=ubuntu-os-cloud \
>   --boot-disk-size=30GB --boot-disk-type=pd-standard
> ```

### B. Deploy on it

Click **SSH** next to the instance in the Console (opens a browser terminal), or
`gcloud compute ssh trader --zone=<your-zone>`. Then:

```bash
# Docker
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER && newgrp docker

# Code
git clone <your repo url> trader && cd trader
git checkout claude/add-mcp-scteyn

# Secrets (never committed) — fill in SEC_USER_AGENT + your PAPER keys
cp .env.example .env && nano .env

# Smoke test, then launch 24/7
docker compose run --rm trader account
docker compose up -d --build
docker compose logs -f
```

### C. Stay inside the free tier

- **Don't** upgrade the machine type or switch the disk to SSD/balanced.
- Free egress is **1 GB/month**. This bot is light (SEC downloads are *inbound*
  and free; outbound is just small API calls + Slack pings), so you're fine — but
  don't co-host anything chatty on the same VM.
- Set a **Budget alert** at $1 (Billing → Budgets & alerts) so you're emailed if
  anything ever starts to cost money.

---

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
git checkout claude/add-mcp-scteyn
```

## 2b. Checking on it once it's up

Three commands, all read-only and safe to run against a live scheduler:

```bash
docker compose exec trader python -m src.main report      # performance scorecard
docker compose exec trader python -m src.main health      # heartbeat freshness
docker compose logs --tail=100 trader                     # recent structured logs
```

`report` is the one that matters. It pairs order legs into closed round trips and
leads with **expectancy per trade**, not win rate — and it says so in words when
most trades win while expectancy is negative.

### Reading an empty report

For the first few weeks `report` will show no closed trades. That is normal —
qualifying cluster buys are a handful a week and the max hold is 20 days. Use the
**signal funnel** at the bottom to tell healthy silence from a broken pipeline:

| Funnel shows | Means |
| --- | --- |
| `filings processed: 0` after a post-close run | EDGAR ingestion is broken — check `SEC_USER_AGENT` |
| `filings processed: 500+`, `signals qualified: 0` | Working correctly. Most days genuinely have nothing |
| signals qualified but none queued | Check the logs for `signal_rejected` reasons |

### The one alert you must not ignore

A `liquidity_data_unavailable` event (error level, so it reaches Slack) means
market-data lookups failed and those signals were dropped **without ever being
screened**. Before this existed, a broken feed and a quiet market produced
identical output — "0 queued" — so an outage could mute the bot for weeks
unnoticed. If you see it, check `ALPACA_API_KEY`/`ALPACA_SECRET_KEY` and
`ALPACA_DATA_FEED` (`sip` needs a paid subscription; `iex` is the free default).

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

### Health & alerts

- **Container healthcheck.** The scheduler writes a heartbeat every minute; the
  image's `HEALTHCHECK` fails if it goes stale (>180s). `docker compose ps` shows
  `healthy`/`unhealthy`, and a wedged scheduler is restarted by the
  `restart: unless-stopped` policy. Check manually with:
  ```bash
  docker compose exec trader python -m src.main health
  ```
- **Slack alerts (optional but recommended).** Set `SLACK_WEBHOOK_URL` in `.env`
  and you'll get pushed messages on: startup, every fill, every exit, every guard
  trip, and every job exception. If unset, these still go to the JSON logs.
- **Daily dead-man's switch.** Once a day (08:00 ET by default,
  `DAILY_HEARTBEAT_HOUR`) the bot sends a "still alive" ping with equity, cash,
  and open-position count. If you *stop* seeing it, the bot is down — that
  absence is the alert. Requires `SLACK_WEBHOOK_URL`.

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

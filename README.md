# Insider-Copy Paper Trading Bot

An autonomous **paper-trading** bot that copies **corporate insider open-market
buys** (SEC Form 4, transaction code `P`) and mirrors qualifying signals into an
**Alpaca paper account** seeded with ~$200 of simulated capital.

## What this is (and isn't)

This is **signal plumbing plus risk management, not a proven edge.** Be honest
with yourself about it:

- Insider buying — especially **cluster buying** (several insiders buying the
  same company in a short window) — has a *modest, documented* tilt in the
  academic literature. It is not a money printer.
- **The filing is public the instant it lands.** Everyone sees the same Form 4
  at the same time, so a chunk of any price move happens *before* a bot reacting
  to the filing can act. We are, structurally, late.
- This is a **learning and paper-forward-testing** system. Treat every number it
  produces with suspicion, and read the backtest caveats below.

Performance ordering, best to worst, always: **backtest ≥ paper ≥ live.** The
backtest overstates paper (idealized fills), and paper overstates live (no real
slippage, borrow, or fill competition).

## Safety constraints (hard requirements)

1. **Paper only by default.** Uses `TradingClient(..., paper=True)` against
   `https://paper-api.alpaca.markets`.
2. **Live is gated and shipped OFF.** Any non-paper endpoint requires
   `ALLOW_LIVE=true` **and** `CONFIRM_LIVE=true`. Without both, the code raises
   before touching a live endpoint. There are no live keys anywhere in this repo.
3. **Dry-run default ON.** With `DRY_RUN=true` (the default) the bot logs every
   intended order ("would buy $25 of TICKER") and places nothing. Real paper
   orders happen only when you explicitly set `DRY_RUN=false`.
4. **No secrets in code or git.** All keys come from `.env` (git-ignored). Only
   `.env.example` (blank placeholders) is committed.
5. **Respects SEC limits.** Every EDGAR request sends a real `User-Agent` and is
   rate-limited under 10 req/s.
6. **Fails loud.** Exceptions are logged structured and pushed to notifications,
   never silently swallowed.

## Architecture

```
EDGAR daily index ──> Form 4 XML parse ──> P-buys
                                             │
                              qualify (size / cluster)
                                             │
                          liquidity screen + dedupe vs holdings
                                             │
                                   queue in SQLite  (post-close job)
                                             │
                          size ──> risk guards ──> notional paper buy  (post-open job)
                                             │
                       bot-managed exits: trailing + hard stop + max hold
```

- **`src/edgar/`** — rate-limited SEC client, Form 4 fetch/parse, daily-index
  ingestion. Only transaction code `P` counts as a buy.
- **`src/signals/`** — `InsiderBuy` / `Signal` models and the qualification
  filters (size threshold, cluster detection, liquidity, dedupe).
- **`src/broker/`** — paper-gated `alpaca-py` wrapper and market data.
- **`src/execution/`** — notional sizing, entry queue/placement, exit manager.
- **`src/risk/`** — the risk rails (kill switch, position caps, paper assertion).
- **`src/state/`** — SQLite schema + repository. State survives restarts and is
  reconciled against Alpaca on boot.
- **`src/notify/`** — structured JSON logging + Slack sink (log-only fallback).
- **`backtest/`** — historical simulation harness + metrics.

## Setup

### 1. Install

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

### 2. Configure credentials

Copy the example env file and fill in the blanks:

```bash
cp .env.example .env
```

You must fill these in `.env`:

| Variable            | What to put                                                                 |
| ------------------- | --------------------------------------------------------------------------- |
| `SEC_USER_AGENT`    | `"Your Name your.email@domain.com"` — **required**, EDGAR 403s without it.   |
| `ALPACA_API_KEY`    | Your Alpaca **paper** API key (app.alpaca.markets → Paper Trading → Keys).   |
| `ALPACA_SECRET_KEY` | Your Alpaca **paper** secret key.                                            |
| `SLACK_WEBHOOK_URL` | *(optional)* Slack incoming-webhook URL; unset = log-only notifications.     |

Leave `DRY_RUN=true`, `ALLOW_LIVE=false`, `CONFIRM_LIVE=false` until you have
watched the dry-run logs and are ready to place paper orders.

## Usage (phased, read-only first)

The CLI mirrors the read-only-before-orders build discipline.

### Phase 1 — signals (read-only, needs only `SEC_USER_AGENT`)

```bash
python -m src.main signals --date 2024-05-10
# add --max-filings 40 for a quick capped smoke test
```

Prints every qualifying `P`-buy signal for the date. No Alpaca, no orders.

### Phase 2 — account (read-only, needs Alpaca paper keys)

```bash
python -m src.main account --ticker AAPL
```

Prints your paper account, buying power, positions, and a test quote. Asserts
the client is paper.

### Phase 3+ — the daily jobs

```bash
# After close: qualify + queue entries (honors DRY_RUN).
python -m src.main post-close --date 2024-05-10

# After open: reconcile, place queued entries, run the exit pass.
python -m src.main post-open            # skips when market closed
python -m src.main post-open --force    # run anyway (dry-run testing)
```

With `DRY_RUN=true` these log intended orders and place nothing. Set
`DRY_RUN=false` in `.env` to place real **paper** orders.

### Run the scheduler

```bash
python -m src.main run
```

Starts APScheduler:

- **~4:30pm ET (Mon–Fri):** pull the day's Form 4 filings, qualify, queue.
- **~9:40am ET (Mon–Fri):** place queued entries, then run the exit pass.

Weekends are skipped by the cron trigger; holidays are skipped because the
post-open path checks Alpaca's clock (`is_market_open`) before placing anything.

## Strategy defaults (sized for ~$200)

All tunables live in `config/settings.py` / `.env`.

| Parameter               | Default   | Meaning                                          |
| ----------------------- | --------- | ------------------------------------------------ |
| `STARTING_EQUITY`       | 200       | Paper account seed                               |
| `DOLLARS_PER_POSITION`  | 25        | Equal-weight notional per name                   |
| `MAX_OPEN_POSITIONS`    | 8         | Hard cap on concurrent holdings                  |
| `MAX_DAILY_LOSS_PCT`    | 10        | Halt **new** entries if today's P/L ≤ −10%       |
| `MIN_INSIDER_BUY_USD`   | 50000     | Single-filer size threshold                      |
| `CLUSTER_MIN_INSIDERS`  | 2         | Distinct insiders needed for a cluster           |
| `CLUSTER_WINDOW_DAYS`   | 5         | Cluster lookback window                          |
| `MIN_PRICE`             | 5.0       | Skip sub-$5 names                                |
| `MIN_AVG_DOLLAR_VOLUME` | 1,000,000 | Liquidity floor (avg daily $ volume)             |
| `TRAIL_PCT`             | 10        | Trailing stop from the high-water mark           |
| `HARD_STOP_PCT`         | 15        | Hard stop from entry                             |
| `MAX_HOLD_DAYS`         | 20        | Time-based exit                                  |
| `MAX_POSITION_EQUITY_PCT` | 20      | Never let one position exceed ~20% of equity     |

### Why bot-managed exits

Alpaca fractional/notional orders are market/day and **don't support native
trailing-stop order types.** So the bot owns the trailing stop: it tracks each
position's high-water mark and exits at market when the drawdown from that peak
exceeds `TRAIL_PCT`. Hard stop and max-hold are checked the same way. This keeps
exits compatible with fractional notional entries.

## Backtest

```bash
python -m backtest.run_backtest --csv backtest/sample_filings.csv \
    --start 2024-01-01 --end 2024-04-01 --out trades.csv
```

Applies the **same** qualification filters and the **same** trailing/hard/
max-hold exits to historical daily bars, and reports total return, win rate,
average hold days, max drawdown, trade count, and a per-trade log.

> **⚠️ Backtest fills are idealized.** No slippage, no partial fills, no
> liquidity limits, clean daily-bar entries/exits. This **overstates**
> performance versus paper, which itself overstates versus live. Treat the
> numbers as an upper bound and a logic sanity-check, not a forecast.

You can also drive `run_backtest.run_backtest(buys, price_frames, settings)`
directly with injected price frames for offline/deterministic testing (see
`tests/test_backtest.py`).

## State & persistence

SQLite (`data/trader.db`) holds `processed_filings`, `signals`, `positions`, and
`trades`. Accession numbers of processed filings are persisted so restarts never
double-count. On boot the bot **reconciles** its DB against Alpaca's real
positions and logs any drift (adopting broker positions the DB doesn't know
about, closing DB positions the broker no longer holds).

## Notifications

Every meaningful event is a structured JSON log line. Notable events (fills,
exits, guard trips, exceptions) additionally push to Slack if
`SLACK_WEBHOOK_URL` is set; otherwise notifications fall back to log-only.

### A broken data feed is an incident, not a quiet day

The liquidity screen distinguishes **"we could not ask"** from **"we asked and
the name is thin."** Both leave price and volume unset, but they mean opposite
things, and conflating them is how a misconfigured account looks healthy:

| Situation | `LiquiditySnapshot` | Event | Level |
| --------- | ------------------- | ----- | ----- |
| Feed answered, name is thin | `price`/`volume` set | `signal_rejected` (`illiquid`) | info |
| Feed answered, no bars for symbol | both `None`, `error=None` | `signal_rejected` (`no_price`) | info |
| Lookup **failed** (bad keys, unentitled SIP, network) | both `None`, `error` set | `signal_rejected` (`data_unavailable(...)`) | **error** |

A data fault is logged at `error`, so it reaches Slack, and the run additionally
emits one `liquidity_data_unavailable` summary naming every ticker that was
dropped without ever being screened. Without that, an outage mutes every signal
and the run reports "0 queued" — indistinguishable from a genuinely quiet day.

If you see that event, check `ALPACA_API_KEY`/`ALPACA_SECRET_KEY` and
`ALPACA_DATA_FEED` (`sip` requires a paid subscription; `iex` is the free
default).

### Alpaca Request IDs

Every Alpaca Trading API response carries a unique `X-Request-ID` header, and
Alpaca recommends persisting recent ones because they identify the call in their
systems and **can't be looked up after the fact**. The broker attaches a hook to
alpaca-py's HTTP session so every call's Request ID is captured into a
thread-safe ring buffer and logged structured. The most recent ID is included in
`order_submitted` / `position_closed` logs, printed by `python -m src.main
account`, and attached to `order_submit_failed` / `position_close_failed` errors
— so when you file an Alpaca support ticket you have the Request ID ready.

## Docker

```bash
docker compose build
docker compose up                                   # runs the scheduler
docker compose run --rm trader signals --date 2024-05-10   # one-off
```

State persists in the `./data` volume. `.env` supplies secrets. The image ships
with `DRY_RUN=true` and live trading disabled.

## TradingView MCP server (vendored)

`mcp/tradingview-mcp/` vendors the upstream
[tradingview-mcp](https://github.com/atilaahmettaner/tradingview-mcp) server
(MIT, v0.8.0) — 37 MCP tools for TradingView screeners, technical indicators,
Yahoo Finance quotes, sentiment, and strategy backtesting.

It is a **research and analysis** surface only. It is completely separate from
the trading path: nothing in `src/` imports it, and it cannot place orders. The
bot's signals still come from EDGAR Form 4 alone.

`.mcp.json` registers it for MCP clients that read project scope:

```json
{ "command": "uv", "args": ["run", "--directory", "mcp/tradingview-mcp", "tradingview-mcp", "stdio"] }
```

`uv run` provisions the server's own isolated environment from its `uv.lock` on
first launch, so its dependency pins (which include a hard `tradingview-screener==3.0.0`
and `mcp[cli]<2`) never mix with the bot's. Run it standalone with:

```bash
uv run --directory mcp/tradingview-mcp tradingview-mcp stdio
uv run --directory mcp/tradingview-mcp pytest -q     # 227 upstream tests
```

The vendored tree is excluded from this repo's `ruff` and `black` config, and
the root `pytest` run (`testpaths = ["tests"]`) does not collect its tests.

### ⚠️ Its backtest numbers are optimistic — more so than ours

`backtest_strategy` / `compare_strategies` / `walk_forward_backtest_strategy`
are upstream code we have not modified. They do model transaction costs by
default (0.1% commission + 0.05% slippage per side), but four issues push the
reported numbers up. Read them before trusting any leaderboard:

- **Sharpe is inflated several-fold.** `_calc_metrics` annualizes *per-trade*
  returns by a *per-bar* factor (`√252` for `1d`). A 12-trades-per-year strategy
  gets scaled by √252 instead of √12. Measured: a true Sharpe of **0.71 reports
  as 4.9**. Treat any Sharpe from these tools as unitless ordering, not a level.
- **Open positions vanish.** The strategy loops never flush a position still
  open at the end of the window. A strategy that bought into an 84% crash and is
  still holding returns an *empty* trade list — no loss recorded anywhere. For
  mean-reversion strategies (RSI, Bollinger) this systematically deletes losers,
  since an unreverted position is exactly a losing one.
- **Same-bar signal and fill.** Entries fill at the very `close[i]` that
  generated the signal — knowable only after that bar closed. Real fills happen
  at `open[i+1]`. Again biased favorably for mean-reversion entries.
- **Drawdown is close-to-close only.** `max_drawdown_pct` is measured at trade
  exits, so intra-trade drawdown is invisible, and `calmar_ratio` divides
  *total* (not annualized) return by that understated figure.

Our own `backtest/` harness has its own idealized-fill caveat above; this one is
looser still. Same rule applies, harder: **backtest ≥ paper ≥ live.**

## Testing

```bash
pytest            # unit tests
ruff check . && black --check .
```

Unit tests cover the logic that can silently lose money: the Form 4 parser
(P-only extraction), the qualification filters (cluster/size/liquidity/dedupe),
notional sizing + equity cap, the risk guards (daily-loss halt, position cap,
paper assertion), the exit manager, and the backtest simulation.

## Enabling paper orders (deliberate opt-in)

1. Watch `python -m src.main post-open --force` output with `DRY_RUN=true` and
   confirm the "would buy" lines look right.
2. Set `DRY_RUN=false` in `.env`. The bot now places real **paper** orders.
3. Live trading is a separate, documented decision. It requires **both**
   `ALLOW_LIVE=true` and `CONFIRM_LIVE=true` and real live keys, which this repo
   intentionally does not ship. Don't enable it until you have paper-traded long
   enough to trust the whole pipeline — and even then, understand you are trading
   a late, public, modest-edge signal.

## License

MIT.

"""Entrypoint + APScheduler wiring.

Subcommands:
* ``signals``  — Phase 1: fetch a day's Form 4 P-buys and print qualifying signals
                 (read-only, no Alpaca).
* ``account``  — Phase 2: print Alpaca paper account, buying power, positions, a
                 test quote (read-only, no orders).
* ``post-close`` — qualify + queue entries for a date (dry-run honored).
* ``post-open``  — place queued entries, then run the exit pass.
* ``run``      — start the APScheduler loop (post-close + post-open jobs).

Every path honors ``DRY_RUN`` and the paper gate. Nothing places a live order.
"""

from __future__ import annotations

import argparse
from datetime import UTC, date, datetime

from config.settings import Settings, get_settings
from src.notify.notifier import configure_logging, get_logger, notify

_log = get_logger("main")


# --------------------------------------------------------------------------- #
# Phase 1: read-only signal dump
# --------------------------------------------------------------------------- #
def cmd_signals(args: argparse.Namespace, settings: Settings) -> None:
    """Fetch Form 4 P-buys for a date and print qualifying signals. Read-only."""
    from src.edgar.client import EdgarClient
    from src.edgar.form4 import fetch_p_buys_for_day
    from src.signals.filters import qualify_signals

    day = _parse_date(args.date)
    with EdgarClient() as client:
        buys = fetch_p_buys_for_day(day, client, max_filings=args.max_filings)

    print(f"\n=== Form 4 open-market (P) buys for {day} ===")
    print(f"raw P-buys extracted: {len(buys)}")

    signals = qualify_signals(buys, settings)
    print(f"qualifying signals (pre-liquidity/holdings): {len(signals)}\n")
    for sig in sorted(signals, key=lambda s: s.total_value_usd, reverse=True):
        print(
            f"  {sig.ticker:<8} {sig.kind.value:<8} "
            f"${sig.total_value_usd:>12,.0f}  "
            f"insiders={sig.distinct_insiders}  {sig.issuer_name}"
        )
    print()
    notify("signals_dump_complete", level="info", day=str(day), signals=len(signals))


# --------------------------------------------------------------------------- #
# Phase 2: read-only Alpaca connection check
# --------------------------------------------------------------------------- #
def cmd_account(args: argparse.Namespace, settings: Settings) -> None:
    """Print account, buying power, positions, and a test quote. Read-only."""
    from src.broker.alpaca_client import AlpacaBroker
    from src.broker.market_data import MarketData

    broker = AlpacaBroker(settings)
    acct = broker.get_account()
    print("\n=== Alpaca paper account ===")
    print(f"  paper:        {settings.is_paper}")
    print(f"  status:       {getattr(acct, 'status', '?')}")
    print(f"  equity:       ${float(acct.equity):,.2f}")
    print(f"  last_equity:  ${float(acct.last_equity):,.2f}")
    print(f"  cash:         ${float(acct.cash):,.2f}")
    print(f"  buying_power: ${float(acct.buying_power):,.2f}")

    positions = broker.get_positions()
    print(f"\n  open positions: {len(positions)}")
    for p in positions:
        print(f"    {p.symbol:<8} qty={p.qty} mv=${float(p.market_value):,.2f}")

    market = MarketData(settings)
    price = market.latest_price(args.ticker)
    print(f"\n  test quote {args.ticker}: ${price}")
    print()


# --------------------------------------------------------------------------- #
# Post-close job: qualify + queue
# --------------------------------------------------------------------------- #
def cmd_post_close(args: argparse.Namespace, settings: Settings) -> None:
    from src.broker.alpaca_client import AlpacaBroker
    from src.broker.market_data import MarketData
    from src.edgar.client import EdgarClient
    from src.edgar.form4 import fetch_p_buys_for_day
    from src.execution.entry import gather_and_queue
    from src.state.db import connect
    from src.state.repo import Repo

    day = _parse_date(args.date)
    conn = connect(settings.db_path)
    repo = Repo(conn)

    with EdgarClient() as client:
        buys = fetch_p_buys_for_day(day, client)

    # Mark filings processed so restarts never double-count.
    for accession in {b.accession_no for b in buys}:
        repo.mark_filing_processed(accession, form_type="4")

    broker = AlpacaBroker(settings)
    market = MarketData(settings)
    held = broker.get_position_symbols()
    pending = broker.open_order_symbols()

    queued = gather_and_queue(buys, settings, repo, market, held, pending)
    notify("post_close_complete", level="info", day=str(day), queued=len(queued))


# --------------------------------------------------------------------------- #
# Post-open job: place entries + exit pass
# --------------------------------------------------------------------------- #
def cmd_post_open(args: argparse.Namespace, settings: Settings) -> None:
    from src.broker.alpaca_client import AlpacaBroker
    from src.broker.market_data import MarketData
    from src.execution.entry import place_queued_entries
    from src.execution.exit import run_exit_pass
    from src.reconcile import reconcile
    from src.state.db import connect
    from src.state.repo import Repo

    conn = connect(settings.db_path)
    repo = Repo(conn)
    broker = AlpacaBroker(settings)
    market = MarketData(settings)

    reconcile(repo, broker)

    if not args.force and not broker.is_market_open():
        notify("market_closed_skip", level="info")
        return

    place_queued_entries(settings, repo, broker, market)
    run_exit_pass(settings, repo, broker, market)
    notify("post_open_complete", level="info")


# --------------------------------------------------------------------------- #
# Scheduler
# --------------------------------------------------------------------------- #
def cmd_run(args: argparse.Namespace, settings: Settings) -> None:
    """Start APScheduler with post-close and post-open jobs (weekdays)."""
    from apscheduler.schedulers.blocking import BlockingScheduler
    from apscheduler.triggers.cron import CronTrigger

    tz = settings.schedule_tz
    scheduler = BlockingScheduler(timezone=tz)

    def _post_close_job() -> None:
        _safe_run(lambda: cmd_post_close(_ns(date=None), settings), "post_close")

    def _post_open_job() -> None:
        _safe_run(lambda: cmd_post_open(_ns(force=False), settings), "post_open")

    # ~4:30pm ET after close, Mon–Fri. Holidays are skipped via Alpaca calendar
    # inside the placement path (post-open checks is_market_open).
    scheduler.add_job(
        _post_close_job,
        CronTrigger(day_of_week="mon-fri", hour=16, minute=30, timezone=tz),
        id="post_close",
        misfire_grace_time=3600,
    )
    # Shortly after the 9:30am ET open, Mon–Fri.
    scheduler.add_job(
        _post_open_job,
        CronTrigger(day_of_week="mon-fri", hour=9, minute=40, timezone=tz),
        id="post_open",
        misfire_grace_time=3600,
    )

    notify(
        "scheduler_started", level="info", tz=tz, dry_run=settings.dry_run, paper=settings.is_paper
    )
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        notify("scheduler_stopped", level="info")


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _safe_run(fn, job: str) -> None:
    """Run a scheduled job, logging + notifying on any exception. Fail loud."""
    try:
        fn()
    except Exception as exc:  # noqa: BLE001 — top-level job boundary.
        notify(
            "job_exception", level="error", job=job, error=str(exc), error_type=type(exc).__name__
        )
        _log.exception("job_failed", job=job)


def _parse_date(value: str | None) -> date:
    if not value:
        return datetime.now(UTC).date()
    return datetime.strptime(value, "%Y-%m-%d").date()


def _ns(**kwargs) -> argparse.Namespace:
    return argparse.Namespace(**kwargs)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Insider-copy paper trading bot.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_sig = sub.add_parser("signals", help="Phase 1: print qualifying Form 4 P-buy signals.")
    p_sig.add_argument("--date", help="YYYY-MM-DD (default: today).")
    p_sig.add_argument(
        "--max-filings",
        type=int,
        default=None,
        help="Cap Form 4 fetches (useful for a quick smoke test).",
    )
    p_sig.set_defaults(func=cmd_signals)

    p_acct = sub.add_parser("account", help="Phase 2: print paper account + test quote.")
    p_acct.add_argument("--ticker", default="AAPL", help="Ticker for the test quote.")
    p_acct.set_defaults(func=cmd_account)

    p_pc = sub.add_parser("post-close", help="Qualify + queue entries for a date.")
    p_pc.add_argument("--date", help="YYYY-MM-DD (default: today).")
    p_pc.set_defaults(func=cmd_post_close)

    p_po = sub.add_parser("post-open", help="Place queued entries + run exit pass.")
    p_po.add_argument(
        "--force", action="store_true", help="Run even when the market is closed (dry-run testing)."
    )
    p_po.set_defaults(func=cmd_post_open)

    p_run = sub.add_parser("run", help="Start the APScheduler loop.")
    p_run.set_defaults(func=cmd_run)
    return parser


def cli() -> None:
    configure_logging()
    settings = get_settings()
    parser = build_parser()
    args = parser.parse_args()
    args.func(args, settings)


if __name__ == "__main__":
    cli()

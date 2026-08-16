"""Adversarial validation for any strategy that produces ``TradeRecord``s.

A backtest's headline numbers are the least informative thing about it. Across
this project the same three tests have repeatedly turned an attractive result
into a rejected one, and they are cheap enough that there is no excuse for
skipping them:

1. **Out-of-sample split.** Chronological, no shuffling. A strategy positive on
   the whole sample but negative on the first half has a regime, not an edge.
   This alone killed the best candidate found here — z-score mean reversion
   showed +0.477%/trade overall and −0.222% on 2018–2022.
2. **Regime breakdown.** High-win-rate strategies usually sell optionality, and
   the bill arrives in a crisis. Mean reversion was negative in 2018 Q4, March
   2020 *and* 2022, and positive only in calm markets.
3. **Independence.** Correlated instruments fire together, so N trades are not
   N bets. Opening-range breakout produced 142 trades on 54 distinct dates —
   97% shared — meaning both the confidence interval and the diversification
   were illusions.

A fourth, ``cost_sensitivity``, separates "the edge is small" from "there is no
edge and friction is doing the work." ORB's gross expectancy was −0.09%; at a
realistic 0.30% round trip it became −0.39%. Nothing was being eroded — the
trading itself was the loss.

Everything here works on the ``TradeRecord`` list any engine in this package
returns, so a new strategy gets the same scrutiny for free.
"""

from __future__ import annotations

import collections
from datetime import date

import pandas as pd

from backtest.run_backtest import TradeRecord

# Regimes worth checking any US-equity strategy against. Each is a period where
# a short-optionality strategy would have been forced to pay out.
DEFAULT_REGIMES: dict[str, tuple[str, str]] = {
    "2018 Q4 selloff": ("2018-10-01", "2019-01-01"),
    "COVID crash 2020": ("2020-02-01", "2020-05-01"),
    "2022 bear market": ("2022-01-01", "2023-01-01"),
    "2023+ recovery": ("2023-01-01", "2027-01-01"),
}


def _entry_ts(t: TradeRecord) -> pd.Timestamp:
    """Entry timestamp. Handles both date strings and full timestamps."""
    return pd.Timestamp(t.entry_date)


def trade_stats(trades: list[TradeRecord]) -> dict:
    """Core metrics. ``expectancy_pct`` is the one that decides anything."""
    if not trades:
        return {"trades": 0}
    rets = [t.return_pct for t in trades]
    wins = [r for r in rets if r > 0]
    losses = [r for r in rets if r <= 0]
    gross_win, gross_loss = sum(wins), abs(sum(losses))
    return {
        "trades": len(trades),
        "win_rate_pct": round(len(wins) / len(trades) * 100, 1),
        "expectancy_pct": round(sum(rets) / len(rets), 3),
        "avg_win_pct": round(gross_win / len(wins), 3) if wins else 0.0,
        "avg_loss_pct": round(-gross_loss / len(losses), 3) if losses else 0.0,
        "profit_factor": round(gross_win / gross_loss, 2) if gross_loss > 0 else None,
    }


def split_sample(trades: list[TradeRecord], cutoff: str | date | None = None) -> dict:
    """Chronological train/test split. Defaults to the median entry date.

    Chronological on purpose: a random split leaks future information into the
    training half, which is how a regime-dependent strategy passes validation it
    should fail.
    """
    if not trades:
        return {"train": {"trades": 0}, "test": {"trades": 0}, "cutoff": None}
    ordered = sorted(trades, key=_entry_ts)
    cut = pd.Timestamp(cutoff) if cutoff else _entry_ts(ordered[len(ordered) // 2])
    train = [t for t in ordered if _entry_ts(t) < cut]
    test = [t for t in ordered if _entry_ts(t) >= cut]
    return {
        "cutoff": str(cut.date()),
        "train": trade_stats(train),
        "test": trade_stats(test),
        "consistent": bool(
            train
            and test
            and trade_stats(train)["expectancy_pct"] > 0
            and trade_stats(test)["expectancy_pct"] > 0
        ),
    }


def by_regime(
    trades: list[TradeRecord], regimes: dict[str, tuple[str, str]] | None = None
) -> dict[str, dict]:
    """Stats per named period. Empty periods are reported, not dropped."""
    regimes = regimes or DEFAULT_REGIMES
    out: dict[str, dict] = {}
    for name, (a, b) in regimes.items():
        lo, hi = pd.Timestamp(a), pd.Timestamp(b)
        out[name] = trade_stats([t for t in trades if lo <= _entry_ts(t) < hi])
    return out


def independence(trades: list[TradeRecord]) -> dict:
    """How much do entries cluster on the same date across instruments?

    Correlated instruments signal together. When they do, the effective sample
    is the number of distinct dates rather than the number of trades, and a
    losing day loses on every position at once.
    """
    if not trades:
        return {"trades": 0}
    by_day = collections.Counter(str(_entry_ts(t).date()) for t in trades)
    shared = sum(v for v in by_day.values() if v > 1)
    worst_day, worst_n = by_day.most_common(1)[0]
    return {
        "trades": len(trades),
        "distinct_entry_dates": len(by_day),
        "trades_sharing_a_date": shared,
        "shared_pct": round(shared / len(trades) * 100, 1),
        "worst_day": worst_day,
        "worst_day_simultaneous": worst_n,
        # Distinct dates is the honest denominator for a correlated universe.
        "effective_sample_estimate": len(by_day),
    }


def cost_sensitivity(run_fn, cost_levels: tuple[float, ...] = (0.0, 0.30, 0.60)) -> list[dict]:
    """Re-run a strategy at several round-trip cost levels.

    ``run_fn(round_trip_pct) -> list[TradeRecord]``. If expectancy is already
    negative at zero cost there is no edge to erode; if it only turns negative
    once costs are applied, the trading frequency is the problem.
    """
    rows = []
    for c in cost_levels:
        stats = trade_stats(run_fn(c))
        rows.append({"round_trip_cost_pct": c, **stats})
    return rows


def validate(
    trades: list[TradeRecord],
    cutoff: str | date | None = None,
    regimes: dict[str, tuple[str, str]] | None = None,
) -> dict:
    """Run the full battery."""
    return {
        "overall": trade_stats(trades),
        "split": split_sample(trades, cutoff),
        "regimes": by_regime(trades, regimes),
        "independence": independence(trades),
    }


def format_validation(rep: dict) -> str:
    """Human-readable verdict, with the failure modes called out in words."""
    o, sp, ind = rep["overall"], rep["split"], rep["independence"]
    L: list[str] = ["", "=== Overall ==="]
    if not o.get("trades"):
        return "\n=== Overall ===\n  no trades\n"
    L.append(
        f"  trades={o['trades']}  win={o['win_rate_pct']}%  "
        f"expectancy={o['expectancy_pct']}%  PF={o['profit_factor']}"
    )
    if o["expectancy_pct"] <= 0 < o["win_rate_pct"]:
        L.append(
            f"  NOTE: {o['win_rate_pct']}% of trades won but expectancy is "
            f"{o['expectancy_pct']}% — losers outweigh winners."
        )

    L += ["", f"=== Out-of-sample split (cutoff {sp['cutoff']}) ==="]
    for half in ("train", "test"):
        s = sp[half]
        L.append(
            f"  {half:>5}: trades={s.get('trades', 0):>4}  "
            f"win={s.get('win_rate_pct')}%  expectancy={s.get('expectancy_pct')}%"
        )
    L.append(
        "  VERDICT: consistent across both halves."
        if sp["consistent"]
        else "  VERDICT: FAILS — not positive in both halves. Regime, not edge."
    )

    L += ["", "=== Regimes ==="]
    for name, s in rep["regimes"].items():
        if s.get("trades"):
            L.append(
                f"  {name:<18} trades={s['trades']:>4}  win={s['win_rate_pct']:>5}%  "
                f"expectancy={s['expectancy_pct']:>7}%"
            )
        else:
            L.append(f"  {name:<18} no trades in period")
    neg = [n for n, s in rep["regimes"].items() if s.get("trades") and s["expectancy_pct"] < 0]
    if neg:
        L.append(f"  Negative in: {', '.join(neg)}")

    L += ["", "=== Independence ==="]
    L.append(
        f"  {ind['trades']} trades on {ind['distinct_entry_dates']} distinct dates; "
        f"{ind['shared_pct']}% share a date"
    )
    L.append(
        f"  worst day {ind['worst_day']}: {ind['worst_day_simultaneous']} simultaneous entries"
    )
    if ind["shared_pct"] > 50:
        L.append(
            "  WARNING: entries are heavily clustered. Effective sample is closer to "
            f"{ind['effective_sample_estimate']} than {ind['trades']}, and a bad day "
            "hits every position at once."
        )
    L.append("")
    return "\n".join(L)

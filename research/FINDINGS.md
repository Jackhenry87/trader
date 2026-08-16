# Findings — z-score mean reversion on US ETFs

**Date:** 2026-08-12
**Data:** 8 liquid US ETFs (SPY, QQQ, IWM, DIA, XLF, XLE, XLK, GLD), daily bars,
2018-01-02 → 2026-08-11, 2,163 bars each. Source: Yahoo Finance chart API,
fetched directly this session.
**Engine:** `backtest/mean_reversion.py` — next-open fills, open positions
closed, 0.30% round-trip costs, stops checked on the entry bar.

> **This is a backtest, not a live or forward-tested result.** No capital was
> deployed. Every figure below is simulated.

---

## z-score (Bollinger) Mean Reversion

**Claimed win rate:** 69.0% over 2018–2026, 313 trades, 8 US ETFs
**Verdict: LIKELY OVERFIT — regime-dependent, fails out-of-sample**

### Mechanism
Buy when price falls 2σ below its 20-day mean; sell when it returns to the
mean. The edge, if real, is compensation for absorbing short-term liquidity
demand — you buy from forced sellers and get paid when the imbalance clears.

### Payoff profile — the headline

| Metric | Value |
|---|---|
| Trades | 313 |
| Win rate | **69.0%** |
| Expectancy | **+0.477% / trade** |
| Avg hold | 10.7 days |
| Exits | 270 mean_revert, 26 max_hold, 17 hard_stop |
| Buy-and-hold over same period | **+204.28%** |

At face value that clears the original brief: a ~70% win rate *with* positive
expectancy. A 9-cell parameter sweep gave **7/9 cells positive** — broad, not a
single lucky corner, and far better than the 3/9 this same engine produced on a
pure random walk.

**All of that falls apart under three tests.**

### The catch #1 — it fails out-of-sample

| Period | Trades | Win rate | Expectancy |
|---|---|---|---|
| **Train 2018–2022** | 192 | 63.0% | **−0.291%** |
| **Test 2023–2026** | 121 | 76.9% | **+1.585%** |

The strategy **lost money over the first five years** and made it all back in
the last three. The +0.477% headline is the average of a losing era and a
winning one. That is not an edge; it is a regime.

### The catch #2 — it sells volatility, and pays for it in every crisis

| Regime | Trades | Win rate | Expectancy |
|---|---|---|---|
| 2018 Q4 selloff | 10 | 50.0% | **−1.549%** |
| **March 2020 crash** | 14 | 35.7% | **−6.337%** |
| 2022 bear market | 38 | 55.3% | **−0.709%** |
| 2024–2026 calm | 83 | 78.3% | **+1.676%** |

Negative in **every** stress period; positive only in the calm one. This is the
textbook short-optionality profile the strategy's high win rate implies: many
small wins buying dips, then a large loss when a dip keeps going. March 2020
cost **−6.3% per trade** — thirteen times the headline expectancy, wiping out
roughly thirteen winners per loser.

The tail risk being absorbed is *gap risk*: mean reversion assumes dislocations
revert, and in a crash they do not.

### The catch #3 — the 313 trades are not 313 independent bets

| | |
|---|---|
| Distinct entry dates | **182** for 313 trades |
| Trades sharing an entry date with another ticker | **197 (63%)** |
| Worst single day | **6 simultaneous entries** (of 8 ETFs) |

The ETFs are highly correlated, so a market-wide dip fires nearly every signal
at once. Effective sample size is far below 313, which inflates confidence in
the win rate — and, worse, means **there is no diversification**. On the day
this strategy is wrong, it is wrong on six positions simultaneously.

### Evidence quality

Backtested only. No live or forward-tested result. Generated and verified in
this session against real price data, but entirely in-sample apart from the
train/test split above — which it fails.

One metric to disregard: `max_drawdown_pct` reads −92%, which is an artifact of
`summarize()`'s sequential compounding (it reinvests 100% of equity into each
trade in turn across interleaved tickers). It is not a realistic portfolio
drawdown. Documented in the README.

---

## What the search did not find

Across this project, **four strategy families were examined** — insider-copy
Form 4 buys, z-score mean reversion, opening-range breakout, and prediction-
market arbitrage. **None has demonstrated a positive-expectancy edge that
survives scrutiny.**

- **Mean reversion** produced a 69% win rate and positive headline expectancy,
  then failed out-of-sample (−0.291% in 2018–2022) and lost money in every
  stress regime tested. It also underperformed simply holding the ETFs by a
  wide margin (+204% buy-and-hold).
- **Opening-range breakout** is untestable at retail size before it is
  untestable statistically: every trade is a day trade, and a representative
  run peaked at **7 day trades in 5 business days** against a regulatory cap of
  3 for accounts under $25k.
- **Insider-copy** has zero closed trades. No evidence either way yet.
- **Prediction-market arbitrage** was never verified past search snippets, and
  its documented failure mode — correlated settlement divergence between venues
  — is the same shape as the tail risk found here.

**Is a 70–90% win rate at positive expectancy achievable?** In the instruments
examined, a ~70% win rate is easy to produce and means almost nothing. This
project generated one at 69%, and separately produced a **61.2% win rate that
lost money** on a synthetic random walk. Win rate is a free parameter — you buy
it by widening stops and taking small profits, and you pay for it in the tail.

The honest summary: **nothing here survived.** The one candidate that looked
like it might was defeated by a train/test split that took ten seconds to run.
That is the correct outcome to report, and it is worth more than a strategy
that looked good because nobody split the sample.

### What would change this conclusion

A strategy that is positive in *both* halves of an out-of-sample split, and
positive or flat through 2020 and 2022 rather than only in calm markets. None
of the four tested meets that bar today.

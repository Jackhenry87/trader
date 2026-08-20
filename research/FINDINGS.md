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
| **Train 2018–2022** | 192 | 64.1% | **−0.222%** |
| **Test 2023–2026** | 121 | 76.9% | **+1.585%** |

The strategy **lost money over the first five years** and made it all back in
the last three. The +0.477% headline is the average of a losing era and a
winning one. That is not an edge; it is a regime.

### The catch #2 — it sells volatility, and pays for it in every crisis

| Regime | Trades | Win rate | Expectancy |
|---|---|---|---|
| 2018 Q4 selloff | 17 | 35.3% | **−0.799%** |
| **COVID crash 2020** | 21 | 19.0% | **−9.504%** |
| 2022 bear market | 43 | 58.1% | **−0.457%** |
| 2023+ recovery | 121 | 76.9% | **+1.585%** |

> **Corrected 2026-08-12.** An earlier version of this table reported −6.337%
> for 2020 and −0.291% for the train half. Those came from ad-hoc scripts that
> sliced the *price frames* per regime, which truncated the 20-day indicator
> warmup at each boundary and silently dropped trades. `backtest/validate.py`
> partitions the *same* trade set by entry date instead, which is correct. The
> crisis losses are worse than first reported.

Negative in **every** stress period; positive only in the calm one. This is the
textbook short-optionality profile the strategy's high win rate implies: many
small wins buying dips, then a large loss when a dip keeps going. March 2020
cost **−9.5% per trade** at a 19% win rate — twenty times the headline
expectancy, wiping out roughly twenty winners per loser.

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

## Opening Range Breakout

**Claimed win rate:** n/a — measured 20.4% over 60 sessions, 142 trades,
SPY/QQQ/IWM, 5-minute bars, 2026-05-20 → 2026-08-14 (Yahoo)
**Verdict: NO EDGE — uniformly negative, and untradeable at retail size anyway**

### Mechanism
Take the first 15 minutes' high/low, buy the break above, stop at the range low,
exit at the close. The premise is that overnight information resolves at the
open and the range acts as a reference level attracting resting orders.

### Payoff profile

| Metric | Value |
|---|---|
| Trades | 142 |
| Win rate | **20.4%** |
| Expectancy | **−0.39% / trade** |
| Avg hold | 187 minutes |
| Exits | 80 stop, 62 session_close |

Unlike mean reversion, this one does not even flatter itself first:

- **Sweep: 0 of 8 cells positive.** Every combination of 5/15/30/60-minute range
  × long/both is negative, in a tight band of −0.33% to −0.42%.
- **Out-of-sample: negative in both halves** (−0.44% first 30 sessions, −0.33%
  second 30). Consistent, not regime-dependent.
- **Independence: 54 distinct entry dates for 142 trades; 97% share a date with
  another ticker.** The three ETFs break out together almost every time, so this
  is closer to ~54 independent observations than 142.

### The catch — friction is the whole story

| Cost assumption | Win rate | Expectancy |
|---|---|---|
| Zero cost (gross signal) | 35.9% | **−0.09%** |
| Realistic (0.30% round trip) | 20.4% | **−0.39%** |
| Pessimistic (0.60% round trip) | 9.9% | **−0.69%** |

Gross of costs the signal is roughly a coin flip with a slight negative tilt.
**Transaction costs are what turn "nothing" into "reliably losing."** That is
the more precise finding than the raw win rate: there is no edge to erode, and
trading it frequently converts a null into a steady drain.

### And it cannot be traded at this account size regardless

`max_day_trades_in_5d: 15` against a regulatory cap of **3** for accounts under
$25k. Every ORB trade is a same-session round trip.

### Evidence quality

Backtested only. **Small sample and a single regime** — Yahoo caps 5-minute
history at 60 days, so 2018 Q4, March 2020 and 2022 could not be tested here as
they were for mean reversion. The consistency across all 8 parameter cells and
both halves is what carries the conclusion, not the sample length.

---

## Insider-Copy (SEC Form 4 code-P buys)

**Measured:** 54.9% win rate over 91 trades, 91 US tickers, signals from 5
sampled EDGAR filing days (2025-01-15, 2025-08-12, 2025-10-14, 2025-12-09,
2026-02-10). Prices from Yahoo; exits are the bot's own 10% trailing / 15% hard
/ 20-day max hold.
**Verdict: INSUFFICIENT EVIDENCE, leaning negative — fails out-of-sample on a
badly underpowered sample**

### Mechanism
Corporate insiders buying their own stock on the open market (transaction code
`P`) have an information advantage. Cluster buying — several insiders in a short
window — carries a modest documented tilt in the literature.

### Payoff profile — the best-looking headline in this project

| Metric | Value |
|---|---|
| Trades | 91 |
| Win rate | 54.9% |
| **Expectancy** | **+2.444% / trade** |
| Profit factor | **2.05** |
| Avg win | +8.692% |
| Avg loss | −5.176% |
| Exits | 46 trailing_stop, 42 max_hold, 3 hard_stop |

This is the profile you would actually want: a modest win rate carried by a
1.68:1 payoff ratio, rather than a high win rate hiding fat losses. It is the
opposite shape to mean reversion, and on its face the most promising result
found anywhere in this project.

### The catch #1 — it fails out-of-sample, like everything else

| Period | Trades | Win rate | Expectancy |
|---|---|---|---|
| Train (to 2025-10-06) | 45 | 66.7% | **+5.338%** |
| Test (from 2025-10-06) | 46 | 43.5% | **−0.387%** |

The entire +2.444% comes from the first half. The second half is negative.

### The catch #2 — the sample is far thinner than 91 trades suggests

| | |
|---|---|
| Distinct entry dates | **23** for 91 trades |
| Trades sharing a date | **89%** |
| Worst single day | **15 simultaneous entries** |

This is the weakest independence of the three strategies tested — worse than
ORB's 54 dates and mean reversion's 182. **Effective sample size is roughly 23,
not 91.** Each half of the out-of-sample split therefore rests on ~11 effective
observations, which is not enough to conclude much in either direction.

The clustering is structural, not an artifact of sampling: insiders file in
bursts after earnings windows open, so signals arrive together and the strategy
takes many positions on the same day with no diversification.

### The catch #3 — no crisis coverage at all

Every trade falls in the 2023+ recovery regime. Sampling only 2025–2026 filing
days means 2018 Q4, March 2020 and 2022 are untested here. The regime that
broke mean reversion was never sampled.

### Evidence quality

Backtested, real EDGAR filings and real prices, but **the thinnest sample in
this project and the least regime coverage.** 1,033 raw P-buys were parsed from
5 filing days; 95 qualified (70 SIZE, 25 CLUSTER); 91 had usable price history.

A fair backtest needs months of *contiguous* filings — sampling isolated days
also limits cluster detection to same-day filings, so CLUSTER signals are
undercounted. That was not feasible here: EDGAR's rate limit puts a full day at
3–9 minutes and a single day can carry 7,000+ Form 4s.

**This result should not be read as "insider-copy fails."** It should be read as
"this test was too small to tell, and what it did show was not encouraging."

---

## What the search did not find

Across this project, **four strategy families were examined** — insider-copy
Form 4 buys, z-score mean reversion, opening-range breakout, and prediction-
market arbitrage. **None has demonstrated a positive-expectancy edge that
survives scrutiny.**

- **Mean reversion** produced a 69% win rate and positive headline expectancy,
  then failed out-of-sample (−0.222% in 2018–2022) and lost money in every
  stress regime tested. It also underperformed simply holding the ETFs by a
  wide margin (+204% buy-and-hold).
- **Opening-range breakout** was tested on real 5-minute data and showed **no
  edge at all**: 20.4% win rate, −0.39% expectancy, **0 of 8 parameter cells
  positive**, negative in both halves of the split. Gross of costs it is a
  slight-negative coin flip (−0.09%), so friction is what makes it a reliable
  loser. It is also untradeable at retail size — 15 day trades in 5 business
  days against a cap of 3.
- **Insider-copy** was tested on real Form 4 filings and produced the best
  headline in the project — +2.444% expectancy, 2.05 profit factor, a healthy
  1.68:1 payoff ratio — then **failed the same out-of-sample split** (+5.338%
  train, −0.387% test). Its 91 trades fall on just 23 distinct dates, so the
  effective sample is ~23 and neither half proves much.
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

# arXiv 2607.20093 — "Retail Trader's Ruin: An Anatomy of Popular Signal Failure"

**Source assessment. Date compiled: 2026-08-06.**

> **PROVENANCE — READ FIRST.** The paper itself is **unreachable** from this
> environment. `arxiv.org`, `researchgate.net`, `alphaxiv.org`, `openreview.net`,
> `semanticscholar.org` and the third-party analysis blog `agents-quant.com` are
> all denied by egress policy (`connect_rejected`). **Nothing below was read at
> source.** Everything is reconstructed from five independent WebSearch queries,
> which return model-generated summaries of pages, not pages.
>
> This file is *triangulated snippet evidence*, not a verified reading. It is
> filed under `raw/` deliberately — it is input to research, not a finding.

## Paper identity

| Field | Value | Confidence |
|---|---|---|
| arXiv ID | 2607.20093 | High — stable across 5 queries |
| Title | *Retail Trader's Ruin: An Anatomy of Popular Signal Failure* | High |
| Author | Adam Darmanin | High |
| Affiliation | Hecatus Research | Medium — one source |
| Date | July 2026 | Medium — one source |
| Category | q-fin.TR | Medium |

## Core claims (triangulated, consistent across 5 queries)

Tests whether **five widely promoted retail signal families** — trend,
oscillator, candlestick, volume, and calendar rules — deliver a positive,
economically meaningful, net-of-cost, and survivable edge. A sixth arm is a
momentum calibration benchmark.

**Three pre-declared gates.** Practical viability is defined as the
*conjunction* of: (1) statistical edge after multiplicity correction;
(2) economic viability after trading costs; (3) finite-bankroll survival under
leverage. Failing any one gate fails the strategy.

**Result: four of six candidates REFUTED** — oscillator, volume, calendar,
candlestick — on statistical and/or economic materiality grounds. Trend and the
momentum benchmark are **INCONCLUSIVE**, confidence intervals too wide at the
sample size to resolve. **None is SUPPORTED.**

Specific named signals across summaries: RSI, MA crossover, candlestick
patterns, volume rules, Sell-in-May.

## Stated methodology

- Exposure-matched benchmarks
- Stationary-bootstrap confidence intervals
- Hierarchical **Benjamini–Yekutieli** multiplicity control
- One-sided claim-exclusion tests
- **Equivalence tests** — distinguishes *refuted materiality* from *unresolved*
- REFUTED criterion: 95% CI upper bound below a pre-set threshold (or below 0) —
  i.e. "even under the most favourable estimate the effect misses the claimed
  strength"
- Leverage/margin scenarios anchored to **FINRA** and **ESMA** rules. Survival
  is *not* the binding constraint at the US headline scenario, but becomes
  discriminating for trend and oscillator under the higher-leverage **EU CFD**
  scenario.
- Replication code and data reportedly included (one source; unverified)

## What I could NOT obtain

The Pass 2 screen cannot be completed. Repeated targeted searches failed to
surface, and one search explicitly stated the methodology section is not
reproduced in available excerpts:

- Sample size (number of trades or observations)
- Instrument universe
- Exact test period
- Per-family effect sizes, win rates, drawdowns

## Conflict-of-interest assessment

**Hecatus Research sells trading signals, AI-enabled algorithmic trading, and
alpha research.** The author is *not* a disinterested academic.

The incentive direction is worth stating precisely, because it is not the usual
one. This is not a vendor pumping a strategy; it is a vendor **debunking the
free, popular alternatives to what it sells**. A firm marketing proprietary
signals benefits commercially from a finding that widely-available retail
signals do not work. That does not invalidate the methodology — which, as
described, is more rigorous than almost anything else surfaced in this search —
but it means the paper is **not independent corroboration** of anything. It
needs its own independent replication.

## Assessment

**Verdict: PROMISING METHODOLOGY, UNVERIFIED AT SOURCE.**

The described method is the right shape for the question. Pre-declared gates
prevent post-hoc goalpost-moving; Benjamini–Yekutieli handles the
multiple-comparisons problem that inflates most retail backtests; and
**equivalence testing is the correct tool for arguing a null** — it supports
"there is no material effect" rather than merely "we failed to find one," which
is the distinction most debunkings get wrong.

If it holds at source, it is directly material to the original brief: it implies
the popular-signal space does not clear *positive expectancy*, let alone a
70–90% win rate at positive expectancy. The refutation of the **oscillator**
family is specifically relevant here — RSI strategies are the headline offering
of the TradingView MCP vendored into this repo.

But every one of those sentences is conditional on a paper I could not open.
Weight accordingly.

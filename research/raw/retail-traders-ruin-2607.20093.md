# arXiv 2607.20093 — "Retail Trader's Ruin: An Anatomy of Popular Signal Failure"

**Source assessment. Date compiled: 2026-08-06.**

> **PROVENANCE — UPDATED 2026-08-12.** The abstract has now been **read at
> source**. This session's egress policy changed mid-conversation and
> `arxiv.org` became reachable via curl (HTTP 200); `WebFetch` remains blocked
> for it, so the fetch was done with curl and the raw page is saved alongside
> this file as `arxiv-2607.20093-abstract.html`.
>
> Everything previously reconstructed from search snippets is **confirmed
> verbatim** — five families, three pre-declared gates, four of six REFUTED
> (oscillator, volume, calendar, candlestick), trend and momentum INCONCLUSIVE,
> none SUPPORTED. The snippet triangulation was accurate.
>
> Still **not** obtained (they live in the full text, not the abstract): sample
> size, instrument universe, exact test period, per-family effect sizes. The
> Pass 2 screen therefore remains incomplete.

## Two methodological details only the source revealed

- **Survivorship control.** "Cross-sectional tests use point-in-time membership
  and delisting corrections." That is the correct handling and is frequently
  skipped in retail-facing backtests.
- **The positive control behaves correctly.** "The momentum benchmark itself
  does not clear the statistical gate and is classified INCONCLUSIVE, not
  REFUTED — the critical validity signature that a genuinely uncertain positive
  control is never falsely falsified by this design." A design that refuses to
  falsify its own uncertain control is much harder to dismiss as a debunking
  machine that returns REFUTED for everything.

These raise my read of the methodology. They do not change the
conflict-of-interest assessment below.

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

## Replication repo — searched for, NOT found

**GitHub is the one reachable channel in this environment.** Cloned the author's
only public quant repo: **`adamd1985/quant_research`** (HEAD `64ee28d`,
2026-07-01, "chore: final polish" — same month as the paper).

**It does not contain the paper's replication code.** Grepped the full tree
(notebooks, scripts, markdown) for every paper-specific term:

| Search term | Hits |
|---|---|
| `retail trader` | 0 |
| `benjamini` / `yekutieli` | 0 |
| `equivalence test` / `claim-exclusion` | 0 |
| `sell.in.may` | 0 |

No arXiv or paper reference in `README.md`. The topically-closest file,
`oscilators-quant.ipynb`, is a 21-cell explainer of APO/MACD/RSI republished
from Medium — a tutorial, not a falsification study.

**So the snippet claim that the paper "includes replication code and data" is
uncorroborated.** I relayed that claim in an earlier turn; it is not supported
by anything reachable. If replication material exists it is bundled with the
arXiv submission itself, which is blocked.

### One piece of weak corroboration in the repo's favour

`papers/` holds the author's reference PDFs, and two of them are precisely the
methods the paper's abstract claims to use:

- `The Stationary Bootstrap.pdf` — the paper cites stationary-bootstrap CIs
- `A_Test_for_Superior_Predictive_Ability.pdf` — Hansen's SPA test, the
  multiplicity-control family
- also: `The Deflated Sharpe Ratio.pdf`, `The Sharpe Ratio Efficient Frontier.pdf`

And `portfolio_ml_trails_no_phacking_testing.ipynb` is explicitly about "Honest
PSR, DSR, and SPA Tests" — i.e. avoiding false discovery from multiple trials.

This does **not** verify a single result in the paper. What it does establish is
that the author demonstrably works with the exact statistical toolkit the
abstract describes, so the methodology description is plausible rather than
something a search summary invented. Weak evidence, but real, and it is the
only source-level corroboration obtained anywhere in this task.

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

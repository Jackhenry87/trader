# Research task halted — primary sources unreachable

**Date:** 2026-08-06
**Status:** Pass 1 partially complete. Passes 2–4 **cannot be performed** in this environment.

## The blocker

Every source category the task specifies is denied by this session's egress
policy. Verified directly against the proxy — all return `connect_rejected`
(HTTP 403 on CONNECT), which `/root/.ccr/README.md` defines as an organization
policy denial that must be reported rather than routed around:

| Required source | Host | Result |
|---|---|---|
| arXiv q-fin | `arxiv.org` | BLOCKED |
| SSRN | `papers.ssrn.com` | BLOCKED |
| ResearchGate (paper mirror) | `www.researchgate.net` | BLOCKED |
| QuantPedia | `quantpedia.com` | BLOCKED |
| Alpha Architect | `alphaarchitect.com` | BLOCKED |
| Robot Wealth | `robotwealth.com` | BLOCKED |
| Quantocracy aggregator | `quantocracy.com` | BLOCKED |
| r/algotrading | `www.reddit.com` | BLOCKED |
| EliteTrader | `www.elitetrader.com` | BLOCKED |
| QuantConnect forums | `www.quantconnect.com` | BLOCKED |
| Substack (practitioners) | `substack.com` | BLOCKED |
| X threads | `x.com` | BLOCKED |
| Medium | `medium.com` | BLOCKED |
| Option Alpha (0DTE writeups) | `optionalpha.com` | BLOCKED |

`WebSearch` still works. `WebFetch` and `curl` do not, for any of the above.

## Why I stopped instead of writing the report

`WebSearch` returns **model-generated summaries of pages**, not the pages. That
is second-hand provenance. The task's core requirements are specifically the
ones that provenance cannot support:

- **"Quote figures exactly as sourced."** I would be quoting a summary of a
  source, not the source. I cannot confirm any number is on the page.
- **`raw/` — fetched pages saved as .md.** Nothing can be fetched. The directory
  would be empty or, worse, filled with my paraphrases of snippets.
- **Pass 2 screening** requires locating sample size, avg win vs avg loss, max
  drawdown, and exact test period. Snippets almost never carry all four, and I
  cannot open the page to look.
- **Pass 4 independent verification** requires reading a second, unaffiliated
  source. Not possible.

Producing a polished `FINDINGS.md` from search snippets would manufacture
exactly the artifact this task was designed to guard against: confident,
well-formatted numbers with unverifiable provenance. For a document intended to
inform real capital allocation, that is worse than no document.

## Pass 1 partial output — UNVERIFIED CANDIDATE LIST

**Provenance warning: every figure below is a search-snippet summary. None has
been read at source. None is screened. Do not act on any of it.** This exists
only so the search isn't repeated from zero.

### Candidates logged

1. **Prediction-market cross-venue arbitrage (Kalshi vs Polymarket).**
   Genuinely 2025–2026. Snippet cites an IMDEA Networks paper, *"Unravelling the
   Probabilistic Forest"*, claiming >$40M extracted from Polymarket Apr 2024–Apr
   2025 across 86M bets / 7,000+ markets. Structurally high win rate (it's
   arbitrage). Named tail risk: **correlated settlement divergence** — the 2024
   government-shutdown episode reportedly resolved opposite ways on the two
   venues, converting a hedged pair into total loss. Also cited: fee drag ~1.75–2.5c
   gross spread needed, shallow books, and execution windows compressing from
   ~5 min (2024) to ~30 s (2026). *Most promising lead; entirely unverified.*

2. **0DTE opening-range breakout (SPY/SPX).** Snippet reports 42.5% win rate,
   55.2% return over 2 years, 7.6% max DD. **Fails the 70–90% win-rate brief by
   construction** — its edge is payoff ratio, not hit rate. Notable mainly as a
   contrast case: the one candidate with a coherent payoff profile is the one
   with a *low* win rate.

3. **0DTE / wide iron condor premium selling.** This is where 70–90% win rates
   actually live. Snippets themselves flag 1:5-or-worse risk/reward. Not new —
   restatement of a decades-old short-premium structure, so it fails the
   "genuinely new" criterion regardless of its numbers.

4. **Vendor win-rate claims (91.11% newsletter; ~98% strategy; "+78%/+67%
   verified E*TRADE statements").** All traced to sites selling courses,
   newsletters, or signal subscriptions. Flagged as advertisement-class on
   sight; would go to `REJECTED.md` under the task's own rule that a win rate
   without a payoff ratio is an ad.

### Counter-evidence found (relevant to "What the search did not find")

- **arXiv 2607.20093, "Retail Trader's Ruin: An Anatomy of Popular Signal
  Failure"** (Adam Darmanin). Per snippet: tests trend, oscillator, candlestick,
  volume, and calendar signal families through three pre-declared gates
  (statistical edge after multiplicity correction, economic viability after
  costs, finite-bankroll survival). Reported outcome: **four of six candidates
  REFUTED** (oscillator, volume, calendar, candlestick); trend and a momentum
  benchmark inconclusive. Methods cited include stationary-bootstrap CIs and
  Benjamini–Yekutieli control.
  **→ Followed up in `raw/retail-traders-ruin-2607.20093.md`.**
  **Correction:** an earlier note in this file described this paper as
  "unaffiliated with any vendor." That is wrong. The author's firm, Hecatus
  Research, **sells trading signals and algo-trading services**, and therefore
  benefits commercially from a finding that free, popular retail signals do not
  work. The paper is not independent corroboration and needs its own.
- **arXiv 2512.15732, "The Red Queen's Trap: Limits of Deep Evolution in
  High-Frequency Trading."** Not yet examined.
- An **"AI-Assisted Audit of Candle-Based Binance Spot Timing Models"** paper
  (title per snippet: *Predictive Extrema, Unprofitable Policies*). Not examined.

## What would unblock this

Any one of:
1. Allow-list the hosts in the table above for this session's egress policy.
2. Run the task from an environment with open outbound HTTPS.
3. Supply the papers/pages directly (upload PDFs or paste text) — I can then do
   Passes 2–4 properly against real primary text.

## Preliminary read, stated as opinion not finding

The Pass 1 shape is already informative and matches the task's stated prior: the
70–90% win-rate band is populated almost entirely by short-premium structures
(old, not new) and by vendors selling something. The one genuinely novel
2025–2026 candidate — prediction-market arbitrage — earns its high win rate by
being arbitrage, and its documented failure mode is a correlated settlement
break that hits every position at once. That is the classic high-win-rate tail:
many small wins, one total loss. Whether it clears costs at retail size is
exactly the question I cannot answer without the primary sources.

# Sources

**All accessed 2026-08-06 via WebSearch only.** No source in this file was
fetched and read at origin — `WebFetch` and `curl` are denied by egress policy
for every domain listed. Credibility ratings below assess the *source*, and are
capped by the fact that **access level is "search snippet" for all of them**.

## Access legend

- **BLOCKED** — host denied by proxy (`connect_rejected`). Could not be opened.
- **SNIPPET** — content known only via WebSearch's model-generated summary.

## Primary research

| Source | Access | Credibility | Notes |
|---|---|---|---|
| arXiv 2607.20093, *Retail Trader's Ruin* (Darmanin) | BLOCKED / SNIPPET | **Medium-High methodology, but NOT independent** | Pre-declared gates, Benjamini–Yekutieli, stationary bootstrap, equivalence tests. **Author's firm (Hecatus Research) sells trading signals and algo-trading services** — commercially benefits from debunking free retail signals. Replication code reportedly included (unverified). |
| arXiv 2512.15732, *The Red Queen's Trap: Limits of Deep Evolution in HFT* | BLOCKED | Unrated | Surfaced only; not examined. |
| *Predictive Extrema, Unprofitable Policies* — AI-assisted audit of candle-based Binance spot timing models | BLOCKED | Unrated | Title from snippet; arXiv ID not confirmed. Not examined. |
| IMDEA Networks, *Unravelling the Probabilistic Forest* | BLOCKED | Unrated | Cited second-hand by an arbitrage-bot vendor page — citation itself unverified. Claims >$40M arbitrage extracted from Polymarket, Apr 2024–Apr 2025, 86M bets, 7,000+ markets. |

## Aggregators / practitioner blogs (all BLOCKED)

| Source | Access | Credibility | Notes |
|---|---|---|---|
| QuantPedia | BLOCKED | Medium (sells subscription) | Never opened. |
| Alpha Architect | BLOCKED | Medium-High (asset manager; sells funds) | Never opened. |
| Robot Wealth | BLOCKED | Medium (sells education/community) | Never opened. |
| Quantocracy | BLOCKED | N/A (aggregator) | Never opened. |
| r/algotrading, EliteTrader, QuantConnect forums | BLOCKED | Low-Medium (anonymous, unverifiable) | Never opened. |

## Commercial / vendor sources — advertisement-class

Flagged under the brief's rule that *a win rate without a payoff ratio is an
advertisement.* All SNIPPET-level.

| Source | Selling | Claim seen | Assessment |
|---|---|---|---|
| beststockstrategy.com | Courses | "+78% and +67% trailing 12mo, verified E*TRADE statements" | **Low.** Vendor-published, self-verified. No payoff ratio, no trade count, no drawdown. |
| Benzinga premium options newsletter | Subscription | "91.11% average win rate, avg return per trade over 23%" | **Very low.** Newsletter marketing. No loss size, no sample. |
| optionspilot.app | SaaS backtester | "options selling achieves 80-90% win rates but occasional catastrophic losses" | **Low-Medium.** Self-serving but the caveat is honest and matches theory. |
| Various Kalshi/Polymarket arbitrage guides (clawarbs, laikalabs, tradingvps, launchpoly, newyorkcityservers, xclsvmedia) | Arbitrage bots, VPS, affiliate signups | 1–5% per trade; fee/edge math; edge decay 5min→30sec 2024→2026 | **Low.** All sell bots or hosting. Fee arithmetic is checkable in principle and internally consistent; the *edge* claims are not. |
| options.cafe | Blog/tooling | 0DTE ORB: 42.5% win rate, 55.2%/2yr, 7.6% max DD | **Medium-Low.** Notably the *only* candidate volunteering a coherent payoff profile — and its win rate (42.5%) is far below the 70–90% brief. |

## Blocked-host record

Confirmed `connect_rejected` at the proxy on 2026-08-06:

```
arxiv.org            www.arxiv.org        export.arxiv.org
papers.ssrn.com      www.researchgate.net www.alphaxiv.org
openreview.net       www.semanticscholar.org  api.semanticscholar.org
quantpedia.com       alphaarchitect.com   robotwealth.com
quantocracy.com      www.reddit.com       www.elitetrader.com
www.quantconnect.com substack.com         x.com
medium.com           optionalpha.com      agents-quant.com
huggingface.co
```

Market-data upstreams also blocked, disabling independent replication via the
vendored TradingView MCP:

```
query1.finance.yahoo.com  query2.finance.yahoo.com
scanner.tradingview.com   www.tradingview.com
```

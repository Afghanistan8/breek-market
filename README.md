# Breek

**A forecast accuracy contest that grades itself, on GenLayer.**

Each round asks one question: *what will this asset be worth at the end of a
GMT+1 window?*

You pay a flat fee, name a price, and revise it free until the window opens.
When it closes, the contract goes and fetches two independent public feeds
itself and grades everyone against the price those feeds agree on. Your share of
the pot is your accuracy relative to everyone else's.

```
error   = |forecast − settled| ÷ settled
weight  = cutoff − error        (zero once error ≥ cutoff)
payout  = pot × weight ÷ Σ weights
```

There is no owner, no pause, no admin scorer and no upgrade hook.
`score_round(round_id)` takes a round id and nothing else.

---

## This is not a prediction market

That distinction is the whole design, so it is worth being precise about.

| | A prediction market | Breek |
|---|---|---|
| What you submit | a **side** | a **number** |
| Outcome space | binary / categorical | continuous |
| Settlement produces | a **verdict** | a **price** |
| What two feeds do | vote; must agree on the verdict | converge; must agree on the value |
| Who gets paid | the winning side splits the pool | everyone in range, in proportion to accuracy |
| Your position | locked once taken | revisable, free, until the window opens |
| Being slightly wrong | pays the same as being wildly wrong | pays strictly more |

There is no counterparty, no order book, no odds and no side to be on. You are
graded on a continuum against a measured value, so a forecast 0.4% off earns
more than one 3% off, which earns more than one 9% off, which earns more than
one 11% off — that last being nothing at all.

---

## The scoring rule, in full

**Accuracy weight** falls linearly from a perfect call to zero at the cutoff:

- Call it exactly → weight `1000`, the maximum.
- Off by 2.5% (250 bp) → weight `750`.
- Off by 10% (the cutoff) or worse → weight `0`, and you collect nothing.

Three consequences worth naming:

1. **Everyone inside the band is paid.** Nothing is "won"; the pot is divided in
   proportion to accuracy.
2. **Closer strictly beats further.** No threshold to scrape over, no cliff
   except the cutoff itself.
3. **A wild guess costs its owner and nobody else.** It scores zero and
   contributes zero to the denominator, so it cannot dilute people who did the
   work.

If *nobody* lands inside the band, no accuracy earned the pot, so every entry
fee is returned instead.

Here is a real round, graded against live feed data by
`scripts/demo_rounds.py`:

```
settled at 116.58191598   (gate.io 116.61000000 / coingecko 116.55383196, gap 4 bp)

  called         off by     weight   share
  117.30000000   0.61%      939      1.596 GEN
  115.05750000   1.30%      870      1.479 GEN
  121.90000000   4.56%      544      0.925 GEN
  287.50000000   146.60%    0        —
```

---

## Live deployment

| | |
|---|---|
| Network | **studionet** (GenLayer Studio Network) |
| Chain id | `61999` |
| RPC | `https://studio.genlayer.com/api` |
| Contract | [`0x4aDb6a8f9D0B920cC5699F75060324575C01E19a`](https://explorer-studio.genlayer.com/address/0x4aDb6a8f9D0B920cC5699F75060324575C01E19a) |
| Runner | `py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6` |
| Frontend | https://breek-market-puce.vercel.app/ |
| `genlayer-js` | **1.1.8** (pinned exactly) |
| `genlayer` CLI | 0.39.2 · `genlayer-test` 0.29.2 · `genvm-linter` 0.11.0 |

Live status and executed transactions: [`docs/LIVE.md`](docs/LIVE.md).

---

## Getting a price without trusting anyone

A normal smart contract cannot make an HTTP request, so somebody has to push the
price on chain — and that somebody becomes the trust assumption. Breek's
contract fetches both feeds itself, inside a GenLayer `eq_principle.strict_eq`
block. Every validator independently fetches, derives the same midpoint, and
builds one canonical string; consensus passes only if those strings match byte
for byte.

| | Feed A | Feed B |
|---|---|---|
| Source | Gate.io hourly spot candles | CoinGecko `market_chart/range` |
| Window reconstruction | from candle **open times** — 24 for a day, 168 for a week | the sample at **exactly** the closing instant |
| Keyless | yes | yes |

The two are not voting. A forecast needs an actual number, so they have to
**converge**: if they sit more than **50 bp** apart there is no single honest
price to grade against, the round voids, and every fee comes back. The settled
price is their midpoint.

A real agreed payload:

```
f1|CRYPTO|SOL|DAILY|2026-09-24|gate.io|coingecko|116.61000000|116.55383196|4|116.58191598
```

The interface shows you those same two feeds live while you are deciding, with
the gap between them, so you can see where the asset is trading and whether the
round is currently at risk of voiding. That display is exactly that — a display.
No number in the browser is ever passed to the contract; it goes and gets its
own. The only way a price you see becomes a price you forecast is you typing it.

After the block returns, the contract re-derives everything offline — re-binding
the payload to this round and this window, recomputing the gap and the midpoint.
A payload that merely asserts a price is rejected with `INVARIANT:`.

---

## Rules that follow from the design

**Entering.** One flat fee, one entry per wallet, up to 200 per round. Everybody
buys in at the same price, so only accuracy separates the payouts.

**Revising.** Free and unlimited until the window opens; only your last number is
graded. A market locks you to a side because the side *is* the bet. Here the bet
is precision, so there is no reason to punish someone for sharpening an estimate.

**Sealed until scored.** Forecasts stay hidden while a round is accepting.
Publishing them live would let a late entrant copy the field, turning a skill
contest into a herding exercise.

**Nothing gets stranded.** Anything invalid — wrong fee, malformed number, too
late, already entered — is refunded *inside the same transaction* rather than
reverting. A revert after value has been credited would trap the fee with no way
out.

**When a feed is down.** Scoring is retryable: a timeout or rate limit reverts
with `TRANSIENT:`, records nothing, and the round stays in the queue. Five days
after the window closes an unscored round refunds everyone — and on that path it
makes **no web request at all**. The contract never invents a price.

---

## GMT+1, precisely

GMT+1 is a **fixed +3600 second offset**. No daylight saving, no timezone
database. Midnight GMT+1 is **23:00 UTC on the previous day**.

```
window_start = day_index(D) * 86400 - 3600
locks_at     = window_start          # forecasts close when the window opens
scoreable_at = window_start + 86400  # (or + 604800 for a week)
expires_at   = scoreable_at + 5 days
```

A weekly window runs Monday 00:00 GMT+1 to the following Monday 00:00 GMT+1. All
lifecycle time comes from consensus time (`gl.message_raw['datetime']`) — never a
host clock, never `Date.now()`.

---

## What is listed

| Category | Assets | Priceable |
|---|---|---|
| `CRYPTO` | SOL, ETH, NEAR | **yes** |
| `DOMINANCE` | BTC.D, ETH.D, OTHERS.D | **no — listed only** |

Dominance needs BTC and ETH market cap *and total crypto market cap* at a past
instant, from two independent keyless feeds. No second such feed exists:
CoinGecko's historical global chart is `401 PRO API subscribers`, and the feeds
that do work disagree by ~3 percentage points because they aggregate different
coin universes (CoinPaprika `55.95` vs CoinLore `58.82` at the same moment). A
round that cannot be priced twice does not open. Evidence in
[`docs/SPEC.md`](docs/SPEC.md).

Hourly is not offered for the same reason: neither feed could be shown to
reconstruct the same exact GMT+1 hour.

---

## Quick start

```bash
pip install -r requirements.txt -r requirements-dev.txt
```

**Probe the live feeds.** Do this first; it is the gate before trusting any
parser.

```bash
python scripts/check_sources.py --json docs/source-probe.json
```

**Tests and lint.** 124 tests, in-process, no network.

```bash
python -m pytest tests
genvm-lint lint contracts/BreekForecast.py
```

**Walk a whole round against real feeds** — open, enter, revise, warp past the
window, score, collect, with real Gate.io and CoinGecko bytes and no mocks:

```bash
python scripts/demo_rounds.py
```

**Frontend.**

```bash
cd frontend && npm install && npm run dev
```

---

## Contract interface

| Method | Who | What it does |
|---|---|---|
| `open_round(category, asset, timeframe, window_id)` | anyone | Puts a question up for a future GMT+1 window. |
| `submit_forecast(round_id, price)` *(payable)* | anyone | Enters with a number for the flat fee. Refunds in-call if invalid. |
| `revise_forecast(round_id, price)` | entrant | Changes your number, free, before the lock. |
| `score_round(round_id)` | anyone | Fetches both feeds, prices the round, grades the field. |
| `collect(round_id)` | entrant | Your accuracy share, or a refund. Idempotent. |
| `get_catalog` `get_round` `get_phase` `get_evidence` `get_entry` `get_leaderboard` `get_stats` `list_rounds` `list_scoreable` `list_entries` | anyone | Views. Wei as decimal strings, addresses lowercase. |

**Error prefixes.** `EXPECTED:` bad input or wrong phase · `TRANSIENT:`
retryable fetch, round stays scoreable · `EXTERNAL:` feed unusable for this
window · `INVARIANT:` agreed payload failed re-derivation.

---

## Deploying

```bash
genlayer network set studionet
genlayer account unlock
genlayer deploy --contract contracts/BreekForecast.py
```

Then point `VITE_BREEK_CONTRACT` at the new address. For the frontend, import
the repo on Vercel with **Root Directory = `frontend`**; everything else comes
from [`frontend/vercel.json`](frontend/vercel.json). There is deliberately no
`vercel.json` at the repository root — [`docs/SPEC.md`](docs/SPEC.md) records
why it breaks the build.

---

## Known limitations

- `genlayer` CLI 0.39.2 cannot reach `submit_forecast` or `revise_forecast` at
  all: it has no `--value` flag, and its argument parser crashes on decimals
  (`BigInt("120.50")` throws). Use the frontend or `scripts/net_exercise.py`.
- `genvm-lint validate` cannot load the SDK on the current release (it looks
  under `runners/…` while the artifacts moved to
  `executor/v0.2.17/legacy-runners/…`). `genvm-lint lint` passes.
- Accuracy shares use floor division, so at most a few wei of dust stays in the
  contract per round. It is not sweepable — a sweep would need a privileged
  address, and there isn't one.

---

## Layout

```
contracts/BreekForecast.py   the whole protocol, one file
docs/ARCHITECTURE.md         how it is built and why it needs GenLayer
docs/SCORING.md              the grading rule, step by step
docs/SPEC.md                 spec, deviations, and the evidence for each
docs/LIVE.md                 what is deployed and what has actually run
frontend/                    Vite + React + TypeScript app
scripts/check_sources.py     live feed probe
scripts/demo_rounds.py       full round walkthrough against live feeds
scripts/net_exercise.py      drive a deployed contract
tests/direct/                in-process tests through the real runner
tests/consensus/             leader/validator convergence
```

## License

MIT. See [`LICENSE`](LICENSE).

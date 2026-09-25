# Breek Market

**Permissionless GMT+1 prediction markets that settle themselves, on GenLayer.**

Stake GEN on whether a listed asset's GMT+1 candle closes up or down, or on which
asset in a category posts the strongest return over a GMT+1 window. When the
window closes, **anyone** can settle the market — and the contract goes and
fetches the prices itself, from two independent public feeds, inside GenLayer's
equivalence-principle consensus.

- Both feeds agree → the market settles, winners split the pool pro-rata.
- They disagree, or either ties → **inconclusive**, every stake refunded in full.
- A single source can never produce a direction or a winner.
- No owner, no pause, no admin resolve, no upgrade hook, no privileged address.

`resolve_market(market_id)` takes a market id and nothing else. Callers cannot
pass prices, URLs, slugs, winners, directions or results.

---

## Live deployment

| | |
|---|---|
| Network | **studionet** (GenLayer Studio Network) |
| Chain id | `61999` |
| RPC | `https://studio.genlayer.com/api` |
| Contract | [`0xC69eDF8Cd4d723002d1d658CAB3AD616A34532d7`](https://genlayer-explorer.vercel.app/address/0xC69eDF8Cd4d723002d1d658CAB3AD616A34532d7) |
| Runner | `py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6` |
| `genlayer` CLI | **0.39.2** |
| `genlayer-test` | 0.29.2 · `genvm-linter` 0.11.0 |
| `genlayer-js` | **1.1.8** (pinned exactly) |
| Frontend | https://breek-market-puce.vercel.app/ |
| Browser writes | **working** — any EIP-1193 wallet (MetaMask, OKX, Rabby…) |

Live status, executed transactions and what has *not* been executed:
[`docs/LIVE.md`](docs/LIVE.md).

---

## What you can bet on

Assets are a compile-time catalog. Nothing beyond a catalog key is
caller-supplied.

| Category | Assets | "Return" means | Settlable |
|---|---|---|---|
| `CRYPTO` | SOL, ETH, NEAR | `(close - open) / open` on the quoted USD/USDT price | **yes** |
| `DOMINANCE` | BTC.D, ETH.D, OTHERS.D | change in market-cap dominance percentage | **no — catalog only** |

### Market kinds

| Kind | You predict |
|---|---|
| `DIR_DAILY` | one asset closes **UP** or **DOWN** over one GMT+1 day |
| `DIR_WEEKLY` | the same over one GMT+1 week |
| `REL_DAILY` | which catalog asset has the **strictly greatest** return that GMT+1 day |
| `REL_WEEKLY` | the same over that GMT+1 week |

A flat close counts as **DOWN** — a market must resolve to a side someone can
hold. An exact tie in a relative market settles nothing and refunds everyone.

### Why DOMINANCE is listed but not settlable

Settling dominance over a past window needs BTC market cap, ETH market cap **and
total crypto market cap** at two past instants, from two independent keyless
feeds. No second such feed exists: every keyless dominance endpoint publishes
current values only, CoinGecko's historical global chart is `401 PRO API
subscribers`, and the feeds that do work disagree with each other by ~3
percentage points because they aggregate different coin universes
(CoinPaprika `55.95` vs CoinLore `58.82` at the same moment).

Rather than settle from one source, `create_market` rejects the category with
`EXPECTED:CATEGORY_NOT_SETTLABLE`. The catalog still lists it, flagged, so the
gap is visible rather than hidden. Full evidence in
[`docs/SPEC.md`](docs/SPEC.md).

### Why there is no hourly

`scripts/check_sources.py` could not prove that both sources reconstruct the same
exact GMT+1 hour with keyless public APIs. Hourly is therefore not shipped. The
two-source rule was not weakened to keep it.

---

## Stake rules

- **2 to 4 GEN** per wallet per market.
- Top up the **same** side freely inside that band.
- **Never switch sides.** A stake on the other side is refunded.
- Staking closes the instant the window opens.

Anything invalid — too small, too large, too late, wrong side, unknown market —
is **refunded inside the same transaction** and returns `REFUNDED:<reason>`,
rather than reverting. A revert after value has been credited would strand the
stake in the contract with no way out; Breek does not have that bug, and
[`tests/direct/test_lifecycle.py`](tests/direct/test_lifecycle.py) pins every
case.

---

## Two-source settlement

| | Source A | Source B |
|---|---|---|
| Feed | Gate.io hourly spot candlesticks | CoinGecko `market_chart/range` |
| Window reconstruction | from candle **open times** — 24 for a day, 168 for a week | samples at **exactly** the two window instants |
| Keyless | yes | yes |

Both must measure **the same two instants**: the price at `window_start` and the
price at `window_end`. Comparing a 23-hour sample to a 24-hour close is
forbidden, and the parser fails rather than substituting a nearby point.

Gate.io's *daily* bars are UTC-aligned, which is one hour off a GMT+1 day, so the
window is always rebuilt from hourly bars with the first and last open times
asserted exactly.

Each source produces its own verdict from its own numbers. Then:

```
final = a_verdict  if  a_verdict == b_verdict and neither is TIE
        else INCONCLUSIVE
```

After the equivalence block returns, the contract re-derives the entire result
from the agreed payload with **no network access** — re-binding every field to
this market and this window, and recomputing both verdicts and the final result
from the raw prices. A payload that merely asserts a winner is rejected with
`INVARIANT:`.

A real agreed payload, verbatim:

```
v1|DIR_DAILY|CRYPTO|SOL|DAILY|gate.io|coingecko|2026-09-24|SOL:115.15000000:116.61000000|UP|SOL:115.09859487:116.55383196|UP|UP
```

Full walkthrough: [`docs/RESOLUTION.md`](docs/RESOLUTION.md).

---

## GMT+1, precisely

GMT+1 is a **fixed +3600 second offset** from UTC. No daylight saving, no
timezone database, ever. Midnight GMT+1 is **23:00 UTC on the previous day**.

```
window_start        = day_index(D) * 86400 - 3600
cutoff_at           = window_start          # staking closes when the candle opens
settles_at          = window_start + 86400  # (or + 604800 for a week)
terminal_refund_at  = settles_at + 5 days
```

A weekly window runs Monday 00:00 GMT+1 to the following Monday 00:00 GMT+1.
Every time in the interface is labelled GMT+1 for this reason.

All lifecycle time comes from consensus time (`gl.message_raw['datetime']`) —
never a host clock, never `Date.now()`.

---

## If nobody settles

Settling is retryable. A timeout or rate limit reverts with `TRANSIENT:` and
records nothing; the market stays in the resolve queue. A malformed or
incomplete window reverts with `EXTERNAL:`.

If **five days** pass after the window closed and still nobody has settled it,
the market becomes `INCONCLUSIVE` and refunds everyone — and on that path it
makes **no web request at all**. The contract never invents a price.

---

## Quick start

```bash
pip install -r requirements.txt -r requirements-dev.txt
```

### Probe the live feeds

Do this first. It is the gate before trusting any parser.

```bash
python scripts/check_sources.py --json docs/source-probe.json
```

Hits the real endpoints and prints open/close for every asset-window on both
sources, the verdict each would produce, and whether they agree.

### Tests and lint

```bash
python -m pytest tests          # 188 tests, in-process, no network
genvm-lint lint contracts/BreekMarket.py
```

The suite runs the real contract file through the real py-genlayer runner via
`gltest.direct`. It covers GMT+1 calendar maths and leap days, decimal scaling,
both feed parsers, flat-is-DOWN, ties, source disagreement, payload forgery,
stake caps and refunds, pro-rata claims, the zero-HTTP terminal path, and
leader/validator convergence.

### Full lifecycle against live feeds

```bash
python scripts/demo_markets.py
```

Runs create → stake → warp past the GMT+1 window → resolve → claim for
`DIR_DAILY`, `REL_DAILY`, `REL_WEEKLY` and `DIR_WEEKLY`, with **real** Gate.io
and CoinGecko bytes — no mocks. Consensus time is warped rather than slept
through. Also demonstrates the DOMINANCE refusal and the zero-HTTP terminal
refund.

### Frontend

```bash
cd frontend
cp .env.example .env.local     # or keep the defaults
npm install
npm run dev                    # http://localhost:5173
```

---

## Deploying

### Contract

```bash
genlayer network set studionet
genlayer account unlock
genlayer deploy --contract contracts/BreekMarket.py
```

Then point the frontend at the new address via `VITE_BREEK_CONTRACT`.

Verify it is live:

```bash
genlayer call <address> get_catalog
genlayer call <address> get_stats
```

### Frontend (Vercel)

Import the repository and set **Root Directory to `frontend`**. That is the only
setting you need to touch — everything else comes from
[`frontend/vercel.json`](frontend/vercel.json), which pins the framework, the
install and build commands, the output directory and the SPA rewrite:

| Setting | Value |
|---|---|
| Root Directory | `frontend` |
| Framework | Vite (pinned in `frontend/vercel.json`) |
| Install / Build | `npm install` / `npm run build` |
| Output | `dist` |

There is deliberately **no `vercel.json` at the repository root.** When Root
Directory is `frontend`, Vercel still reads a root-level `vercel.json` but runs
its commands with the working directory already inside `frontend/`, so a
root-level `"installCommand": "npm --prefix frontend install"` resolves to
`frontend/frontend` and the build dies with:

```
npm error path /vercel/path0/frontend/frontend/package.json
Error: Command "npm --prefix frontend install" exited with 254
```

A single file cannot be correct for both working directories, so the config
lives only in `frontend/`. Note that a failed import may have **persisted** those
root-level commands into the project's Build & Output Settings;
`frontend/vercel.json` sets `installCommand`, `buildCommand` and
`outputDirectory` explicitly so it overrides them without any dashboard change.

No environment variables are required: the defaults in
[`frontend/src/lib/env.ts`](frontend/src/lib/env.ts) already point at the
studionet deployment above. Set `VITE_BREEK_CONTRACT` (and the other
`VITE_BREEK_*` variables) only when targeting a different deployment.

Verify a build the way Vercel runs it, without deploying:

```bash
vercel link && vercel pull && vercel build   # from the repository root
```

---

## Contract interface

| Method | Who | What it does |
|---|---|---|
| `create_market(kind, category, asset, timeframe, window_id)` | anyone | Lists a market on a catalog asset for a future GMT+1 window. |
| `take_position(market_id, side)` *(payable)* | anyone | Stakes 2–4 GEN. Refunds in-call if invalid. |
| `resolve_market(market_id)` | anyone | Fetches both feeds, settles or refunds. |
| `claim(market_id)` | position owner | Payout or refund. Idempotent. |
| `get_catalog` `get_market` `get_phase` `get_evidence` `get_position` `get_stats` `list_markets` `list_resolvable` `list_positions` | anyone | Views. Wei as decimal strings, addresses lowercase. |

### Error prefixes

| Prefix | Meaning |
|---|---|
| `EXPECTED:` | bad input or wrong phase |
| `TRANSIENT:` | retryable fetch failure; the market stays resolvable |
| `EXTERNAL:` | a source is unusable for this window |
| `INVARIANT:` | the agreed payload failed re-derivation |

---

## Known network limitations

These affect tooling, not the deployed contract. Details and workarounds in
[`docs/SPEC.md`](docs/SPEC.md).

- **`genlayer` CLI 0.39.2 has no `--value` flag**, so `take_position` cannot be
  called from it. Use the frontend, or `scripts/net_exercise.py`.
- **The CLI cannot encode an empty string**, so creating `REL_*` markets from it
  is not possible (`""` is coerced to integer `0`). Same workarounds.
- **The runner tag `py-genlayer:test`** used by the CLI project template does not
  resolve on studionet — it deploys but fails with
  `contract_error: invalid_contract`. Breek pins the runner by content hash.
- **`genvm-lint validate` cannot load the SDK** on the current release (it looks
  under `runners/…` while the artifacts moved to
  `executor/v0.2.17/legacy-runners/…`). `genvm-lint lint` passes and is the
  check to run.

```bash
# stake and create REL markets on a deployed contract
export BREEK_PRIVATE_KEY=0x...
python scripts/net_exercise.py --address <address> stake 1 UP 2
python scripts/net_exercise.py --address <address> create REL_DAILY CRYPTO "" DAILY 2026-09-28
```

---

## Layout

```
contracts/BreekMarket.py     the entire protocol, one file
docs/ARCHITECTURE.md         how it is built and why it needs GenLayer
docs/RESOLUTION.md           the settlement path, step by step
docs/SPEC.md                 spec, deviations, and the evidence for each
docs/source-probe.json       committed live probe output
frontend/                    Vite + React + TypeScript app
scripts/check_sources.py     live feed probe
scripts/demo_markets.py      lifecycle walkthrough against live feeds
scripts/net_exercise.py      drive a deployed contract
tests/direct/                in-process tests through the real runner
tests/consensus/             leader/validator convergence
```

---

## License

MIT. See [`LICENSE`](LICENSE).

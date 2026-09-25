# Breek Market — specification and deviations

This document records what Breek actually does, and every place where the live
world forced a change from the original brief. Each deviation is stated with the
evidence that forced it. Where the brief and the live APIs conflicted, the
**two-source guarantee was kept** and the feature was cut instead.

The raw probe output behind everything below is committed at
[`docs/source-probe.json`](source-probe.json) and can be regenerated with:

```bash
python scripts/check_sources.py --json docs/source-probe.json
```

---

## 1. Constants, as shipped

| Constant | Value | Notes |
|---|---|---|
| `DAY` | `86400` | |
| `HOUR` | `3600` | |
| `WEEK` | `604800` | |
| `GMT_PLUS_ONE` | `3600` | Fixed offset. No DST, no tz database. |
| `GEN` | `10**18` | wei per GEN |
| `MIN_STAKE` | `2 * GEN` | |
| `MAX_STAKE` | `4 * GEN` | |
| `MAX_FORWARD_DAYS` | `366` | |
| `TERMINAL_REFUND_DELAY` | `5 * DAY` | |
| `MAX_PAGE` | `50` | |
| `MAX_SOURCE_BYTES` | `60000` | Largest observed body is 17 676 B (weekly CoinGecko). |
| `PRICE_SCALE` | `10**8` | |
| `BPS_SCALE` | `10000` | |

No constant was changed from the brief.

---

## 2. Deviation: HOURLY is not shipped

**Brief:** hourly is optional, and only allowed if *both* settlement sources can
reconstruct the exact same GMT+1 hour independently with keyless public APIs,
proven by a live script.

**Finding:** not proven, so not shipped.

Gate.io reconstructs a single closed hour fine — one candle, exact open time:

```
=== CRYPTO / HOURLY 1790337600 ===
    window_start 1790337600  (2026-09-25 13:00 GMT+1)
    window_end   1790341200  (2026-09-25 14:00 GMT+1)
  SOL   gate.io    open=120.87  close=120.74  candles=1 bytes=94 bps=-11
  SOL   coingecko  FAILED: HTTP 429
```

Two separate problems stopped hourly:

1. CoinGecko's keyless `market_chart/range` did not return a usable series for a
   one-hour span during the probe.
2. Even when it responds, a one-hour range is inside the granularity band where
   CoinGecko serves 5-minutely data anchored to *request* time rather than to
   fixed instants, so the sample at `window_end` is not reliably present for an
   hour that has only just closed.

`KINDS` therefore contains only `DIR_DAILY`, `DIR_WEEKLY`, `REL_DAILY`,
`REL_WEEKLY`. The UI says why on the Create page. The two-source rule was **not**
weakened to keep hourly.

---

## 3. Deviation: DOMINANCE is a catalog entry only

**Brief:** keep DOMINANCE in the UI as a catalog only unless two working sources
exist; never settle it from one source.

**Finding:** no second source exists, so `create_market` rejects the category
outright with `EXPECTED:CATEGORY_NOT_SETTLABLE`.

Settling `BTC.D` / `ETH.D` / `OTHERS.D` over a past GMT+1 window needs BTC market
cap, ETH market cap **and total crypto market cap** at two past instants, twice
over, from two independent keyless feeds. Every candidate was probed:

| Feed | Result |
|---|---|
| `api.coingecko.com/api/v3/global` | 200, but **current values only** — no history |
| `api.coinpaprika.com/v1/global` | 200, **current only**: `BTC.D=55.95`, `total_mcap=3023580752046` |
| `api.coinlore.net/api/global/` | 200, **current only**: `BTC.D=58.82`, `ETH.D=11.58` |
| `api.coingecko.com/api/v3/global/market_cap_chart` | **HTTP 401** — "limited to PRO API subscribers" |
| `api.coincap.io/v2/assets` | DNS failure — service retired |
| `rest.coincap.io/v3/assets` | **HTTP 401** — key required |

Two independent facts each kill it on their own:

1. **No historical total market cap is available keyless.** Per-coin market cap
   history exists (CoinGecko `market_chart/range` returns `market_caps`, and
   CoinPaprika returns daily `market_cap`), but the denominator does not.
2. **The current-value feeds do not even agree with each other.** CoinPaprika
   reports BTC dominance at `55.95` while CoinLore reports `58.82` for the same
   moment — a ~2.9 point gap, because they aggregate different coin universes.
   There is no shared definition of "total crypto market cap" to reconcile.

Shipping DOMINANCE would have meant settling from one source. Breek refuses the
market instead. The catalog still lists the assets, flagged `settlable: false`
with the reason attached, so the gap is visible rather than hidden.

CoinPaprika's per-coin history is also **UTC-aligned daily** (`2026-09-20T00:00:00Z`),
which cannot express a GMT+1 window in any case.

---

## 4. Source pair, as shipped

Both are compile-time constants in `contracts/BreekMarket.py`. Neither is
caller-supplied and neither carries an API key.

### Source A — Gate.io hourly spot candlesticks

```
https://api.gateio.ws/api/v4/spot/candlesticks
  ?currency_pair={PAIR}&interval=1h&from={window_start}&to={window_end-1}
```

Pairs: `SOL_USDT`, `ETH_USDT`, `NEAR_USDT` (confirmed live).

Row layout, confirmed against live responses:

```
[0] open time (unix s)  [1] quote volume  [2] close  [3] high
[4] low  [5] open  [6] base volume  [7] "true" iff the window has closed
```

The window is reconstructed from **candle open times, never array position**:

* exactly `(window_end - window_start) / 3600` rows must be present
  (24 for a day, 168 for a week);
* every open time must be hour-aligned and every hour in the window present;
* every candle must carry the closed flag `"true"`;
* window open = `open` of the candle at `window_start`;
* window close = `close` of the candle at `window_end - 3600`.

**Why hourly candles and not daily ones:** Gate.io's daily bars are UTC-aligned,
which is exactly one hour off a GMT+1 day. Reconstructing from hourly bars and
asserting the first and last open times is what makes the GMT+1 window exact.
The parser test `test_gate_rejects_wrong_window_offset` pins this: a UTC-day
payload is rejected with `EXTERNAL:GATE_MISSING_HOUR`.

### Source B — CoinGecko market_chart/range

```
https://api.coingecko.com/api/v3/coins/{ID}/market_chart/range
  ?vs_currency=usd&from={window_start-3600}&to={window_end+3600}
```

Ids: `solana`, `ethereum`, `near`.

The range is padded by one hour on each side so both boundary instants are
*interior* points of the returned series, then the two samples are selected **by
timestamp**:

* a sample must exist at exactly `window_start` → window open;
* a sample must exist at exactly `window_end` → window close;
* a missing boundary sample is `EXTERNAL:CG_NO_SAMPLE_AT_START` / `..._AT_END`,
  never a fallback to the nearest point.

This is what forbids comparing a 23-hour sample against a 24-hour close.
`test_coingecko_rejects_a_23_hour_span` pins it.

### Both sources measure the same two instants

Verified live for a completed GMT+1 day:

```
=== CRYPTO / DAILY 2026-09-24 ===
    window_start 1790204400  (2026-09-24 00:00 GMT+1)
    window_end   1790290800  (2026-09-25 00:00 GMT+1)
  SOL   gate.io    open=115.15  close=116.61  candles=24  bps=+126
  SOL   coingecko  open=115.0985948771  close=116.5538319674  samples=27 step=3600s  bps=+126
  ETH   gate.io    open=2690.25 close=2685.52 candles=24  bps=-18
  ETH   coingecko  open=2689.530601953  close=2684.277838013  bps=-20
  NEAR  gate.io    open=4.325   close=4.583   candles=24  bps=+596
  NEAR  coingecko  open=4.328730390582  close=4.581299048751  bps=+583
```

and for a completed GMT+1 week:

```
=== CRYPTO / WEEKLY 2026-09-14 ===
    window_start 1789340400  (2026-09-14 00:00 GMT+1)
    window_end   1789945200  (2026-09-21 00:00 GMT+1)
  SOL   gate.io    open=99.73   close=111.04  candles=168 bytes=15544
  SOL   coingecko  open=99.70045916928  close=110.9555773071  samples=171 bytes=17676
  NEAR  gate.io    open=2.309   close=4.066   bps=+7609
  NEAR  coingecko  open=2.308820401970  close=4.071984670364  bps=+7636
```

The two feeds never produce identical *numbers* — they are independent — and
they are not required to. Only the **verdict** each derives from its own numbers
has to match.

---

## 5. Finding: CoinGecko rate limits, and why Source B was kept

The brief permits swapping Source B if CoinGecko 429s **on studionet validator
IPs**. That was tested directly rather than assumed.

A throwaway contract was deployed to studionet that fetches every candidate feed
inside `gl.eq_principle.strict_eq` and returns the status codes. All five
validators agreed on this result:

```
gate:200:1 | cgko:200:1 | bnce:451:1 | bybt:403:0 | okx_:200:1
krkn:200:1 | kucn:200:1 | bstp:200:1
```

* **CoinGecko returns 200 from studionet validators.** It did not rate-limit.
* The 429s seen locally came from a single laptop IP issuing ~12 requests in
  under a minute — a burst no single `resolve_market` produces. One `DIR_*`
  settle makes 1 CoinGecko request; one `REL_*` settle makes 3.
* **Binance is geo-blocked (451) and Bybit is blocked (403) from validators.**
  Had Source B been swapped on the local evidence alone, the result would have
  been a feed the validators cannot reach at all.

Source B therefore stays CoinGecko, as the brief intended. OKX, Kraken, KuCoin
and Bitstamp are all reachable from validators and are documented here as
drop-in alternates: swapping means changing `COINGECKO_URL`, `COINGECKO_IDS` and
`_fetch_coingecko` in one marked block, plus `SOURCE_B` (which is bound into the
payload, so old evidence stays distinguishable).

A 429 at settle time is not a failure mode that loses money: it reverts with
`TRANSIENT:HTTP_429`, records nothing, and the market stays in the resolve queue.

---

## 6. Consensus payload

One canonical pipe-delimited string, 13 fields:

```
v1|kind|category|asset|timeframe|source_a|source_b|window_id|A_SERIES|a_verdict|B_SERIES|b_verdict|final
```

`SERIES` is comma-joined `SYMBOL:open:close`, in catalog order, with prices
rendered from `PRICE_SCALE` integers. One entry for `DIR_*`, all catalog entries
for `REL_*`. A real example, verbatim from a settled market:

```
v1|DIR_DAILY|CRYPTO|SOL|DAILY|gate.io|coingecko|2026-09-24|SOL:115.15000000:116.61000000|UP|SOL:115.09859487:116.55383196|UP|UP
```

After `strict_eq` returns, `_parse_agreed` re-validates with **no network
access**:

1. field count and version;
2. `kind`, `category`, `asset` bind to this market;
3. `timeframe` and `window_id` bind to this window;
4. `source_a` and `source_b` are the two expected feeds (naming one feed twice
   is rejected);
5. series length and symbols match the catalog in order;
6. every open and close is a positive integer;
7. `a_verdict` recomputed from `A_SERIES` matches;
8. `b_verdict` recomputed from `B_SERIES` matches;
9. `final` recomputed from the two verdicts matches;
10. a settled result is `UP`, `DOWN`, or a catalog symbol.

Any failure raises `INVARIANT:` and reverts. The payload is then persisted as the
market's evidence and surfaced in the UI.

`tests/direct/test_payload.py` attacks each of these in turn — forged verdicts,
forged winners, replayed windows, off-catalog winners, ties promoted to wins.

### Decimal normalisation

Prices are parsed as **strings** and converted with `_dec_to_scaled`, so
`80494.31000000` and `80494.31` land on the same integer. CoinGecko returns JSON
numbers, so its body is decoded with `json.loads(text, parse_float=str)` —
keeping the exact decimal text and ensuring **no IEEE-754 value ever touches a
price**. Excess precision truncates, never rounds, because rounding could flip a
verdict. Exponent notation is rejected outright rather than risking a
mis-scaled price.

---

## 7. Deviation: runner header is a pinned hash, not a floating tag

The `genlayer` CLI project template ships contracts headed:

```python
# { "Depends": "py-genlayer:test" }
```

On studionet this deploys but fails with `contract_error: invalid_contract` — a
minimal two-line contract reproduces it, so it is the header, not the code. The
tag `test` does not resolve to a runner.

Breek pins the runner by content hash instead:

```python
# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }
```

This resolves to `py-lib-genlayer-std:11rhn002yf…`, which is the stdlib the
contract is written against, and deploys successfully (`MAJORITY_AGREE`,
`FINALIZED`).

---

## 8. Known tooling limitations

These affect development, not the deployed contract.

* **`genvm-lint validate` cannot load the SDK.** It resolves runners under
  `runners/…` while the current release relocated them to
  `executor/v0.2.17/legacy-runners/…`, so it reports
  `filename 'runners/py-genlayer/1j/…tar' not found`. `genvm-lint lint` passes
  cleanly and is the check to run; semantic checking is covered instead by 188 tests
  that execute the real contract through the real runner.
* **`genlayer` CLI 0.39.2 has no `--value` flag**, so `take_position` cannot be
  called from it. Use the frontend or `scripts/net_exercise.py`.
* **The CLI cannot encode an empty string**, so `create_market` for the `REL_*`
  kinds is unreachable from it — `""` is coerced to integer `0`, which the
  contract correctly rejects with `EXPECTED:REL_TAKES_NO_ASSET`. Use the frontend
  or `scripts/net_exercise.py`.
* **`gltest`'s `vm.warp()` does not propagate into `gl.message_raw['datetime']`**
  (it refreshes sender, origin and value only). `tests/conftest.py::warp_to`
  sets both; without it every warp silently leaves the contract frozen at deploy
  time and time-dependent tests would pass for the wrong reason.
* **`gltest` direct mode does not implement `gl.vm.spawn_sandbox`**, which
  `strict_eq`'s validator path uses. The consensus tests drive the captured
  leader closure directly and apply `strict_eq`'s own equality rule
  (`tests/conftest.py::strict_eq_agrees`). The closure under test is the
  contract's real settle block; only the sandbox plumbing is bypassed.

---

## 9. Deviation: no `vercel.json` at the repository root

**Brief:** the repo layout lists `vercel.json` at the root, and the frontend
section says "Root = `frontend`".

**Finding:** those two cannot both hold. Shipping a root `vercel.json` alongside
`Root Directory = frontend` breaks the build.

With Root Directory set to `frontend`, Vercel still reads a root-level
`vercel.json`, but executes its commands with the working directory already
inside `frontend/`. A root config saying `npm --prefix frontend install`
therefore resolves to `frontend/frontend`:

```
2026-09-25T14:58:19.180Z  Running "install" command: `npm --prefix frontend install`...
2026-09-25T14:58:20.928Z  npm error code ENOENT
2026-09-25T14:58:20.928Z  npm error path /vercel/path0/frontend/frontend/package.json
2026-09-25T14:58:20.973Z  Error: Command "npm --prefix frontend install" exited with 254
```

One file cannot carry correct paths for two different working directories, so
the root `vercel.json` was removed and the config lives only in
`frontend/vercel.json`.

A second-order effect is worth knowing: the failed import **persisted** the
root config's commands into the Vercel project's stored Build & Output
Settings, so deleting the file is not sufficient on its own. `vercel pull`
showed them still in place afterwards:

```
rootDirectory     'frontend'
installCommand    'npm --prefix frontend install'
buildCommand      'npm --prefix frontend run build'
outputDirectory   'frontend/dist'
```

`frontend/vercel.json` therefore sets `installCommand`, `buildCommand` and
`outputDirectory` explicitly rather than relying on framework defaults, because
a `vercel.json` value overrides a stored project setting while an absent one
does not. Verified by running Vercel's own pipeline against those stored
settings:

```
Running "install" command: `npm install`...      <- overridden, not the stored one
> tsc -b && vite build
Build completed successfully.
```

---

## 10. Deviation: `create_market` cross-checks `timeframe` against `kind`

The brief fixes the signature as
`create_market(kind, category, asset, timeframe, window_id)` while also defining
`kind` as the composite `DIR_DAILY` / `REL_WEEKLY` / …, which makes `timeframe`
redundant.

Rather than ignore the argument, Breek requires it to agree:
`kind.endswith("_" + timeframe)` or `EXPECTED:KIND_TIMEFRAME_MISMATCH`. The
signature is unchanged and a caller who disagrees with themselves is rejected
rather than silently overridden.

---

## 11. Dust

Pro-rata payouts use floor division (`pool * stake // winning_total`). The
remainder — at most a few wei per market — stays in the contract. It is not
claimable and not swept, because a sweep needs a privileged address and Breek
has none. `test_payouts_never_exceed_the_pool` pins that payouts can never
exceed the pool.

## 12. Settled, but nobody won

If a market settles to a side that nobody staked, the pool would have no
claimant. Rather than strand it, `claim` refunds every wallet its own stake
(`REFUND_NO_WINNERS`). This is an addition to the brief; the alternative was
permanently locked GEN.

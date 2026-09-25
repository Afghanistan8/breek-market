# How a Breek market resolves

This is the full path from "the window closed" to "GEN left the contract", in
order, with the exact checks at each step.

`resolve_market(market_id)` takes **one argument**. There is no overload, no
optional price, no URL, no winner, no admin variant. A caller cannot influence
the outcome, only trigger the attempt.

---

## Step 0 — who may call it

Anyone. There is no resolver role, no allowlist, no fee, and no owner. The
caller pays gas and gets nothing for it beyond an unblocked market. The Resolve
queue page lists everything currently settleable.

---

## Step 1 — deterministic pre-checks

Before any network access:

| Check | Failure |
|---|---|
| market exists | `EXPECTED:NO_SUCH_MARKET` |
| not already settled | `EXPECTED:ALREADY_SETTLED` |
| `now >= settles_at` | `EXPECTED:WINDOW_NOT_CLOSED` |

`now` is consensus time, parsed from `gl.message_raw['datetime']`.

---

## Step 2 — the terminal branch

```python
if now >= terminal_refund_at:      # settles_at + 5 days
    settled = True
    outcome = INCONCLUSIVE
    evidence = "v1|TERMINAL_REFUND|<timestamp>"
    return "INCONCLUSIVE:TERMINAL_REFUND"
```

This branch returns **before the equivalence block exists**, so no feed is
contacted. If a market has gone five days without anyone settling it — a feed
permanently broke, an asset delisted, nobody cared — the contract pays everyone
back rather than reaching for a number it cannot verify.

`test_terminal_refund_makes_zero_http_calls` enforces this by running the call
with zero web mocks registered and `strict_mocks` enabled: any outbound request
would raise.

---

## Step 3 — capture, then fetch

Everything the closure needs is read out of storage **first**, because a
non-deterministic block cannot touch storage:

```python
kind, category, asset, timeframe = m.kind, m.category, m.asset, m.timeframe
window_id, window_start, window_end = m.window_id, int(m.window_start), int(m.window_end)
symbols = (asset,) if not relative else catalog(category)
```

Then, inside `gl.eq_principle.strict_eq`, for each symbol:

### Source A — Gate.io

Request `interval=1h` candles from `window_start` to `window_end - 1`, then:

1. the row count must equal `(window_end - window_start) / 3600` exactly —
   24 for a day, 168 for a week (`EXTERNAL:GATE_CANDLE_COUNT`);
2. every open time must be hour-aligned (`EXTERNAL:GATE_TS_UNALIGNED`);
3. every candle must be closed (`EXTERNAL:GATE_CANDLE_OPEN`);
4. every hour in the window must be present (`EXTERNAL:GATE_MISSING_HOUR`);
5. open = field `[5]` of the candle **at `window_start`**;
6. close = field `[2]` of the candle **at `window_end - 3600`**.

Selection is by timestamp, never by array position. Reversing the array does not
change the answer (`test_gate_selects_by_timestamp_not_position`), and a
UTC-aligned day — one hour off a GMT+1 day — is rejected rather than silently
used (`test_gate_rejects_wrong_window_offset`).

### Source B — CoinGecko

Request `market_chart/range` from `window_start - 3600` to `window_end + 3600`,
so both boundaries are interior points, then:

1. a sample must exist at **exactly** `window_start`
   (`EXTERNAL:CG_NO_SAMPLE_AT_START`) → window open;
2. a sample must exist at **exactly** `window_end`
   (`EXTERNAL:CG_NO_SAMPLE_AT_END`) → window close.

There is no nearest-point fallback. A series that stops an hour short fails
rather than substituting its last point — which is precisely the "compare a 23h
sample to a 24h close" bug the two-instant rule exists to prevent.

### Shared handling

* Status 408 / 425 / 429 / 5xx → `TRANSIENT:HTTP_<code>` (retryable).
* Any other non-200 → `EXTERNAL:HTTP_<code>`.
* Body over `MAX_SOURCE_BYTES` (60 000) → `EXTERNAL:BODY_TOO_LARGE`.
* Non-UTF-8 → `EXTERNAL:NOT_UTF8`; unparseable → `EXTERNAL:BAD_JSON`.
* Bodies are decoded with `json.loads(text, parse_float=str)` so every price
  stays exact decimal text and **no float ever touches settlement**.
* Request headers are pinned browser-like constants, identical on every
  validator.

---

## Step 4 — a verdict per source, from that source's own prices

**Direction** (`DIR_DAILY`, `DIR_WEEKLY`):

```
verdict = UP if close > open else DOWN
```

Flat is DOWN, deliberately. A market must resolve to something, and "unchanged"
is not a side anyone can stake.

**Relative return** (`REL_DAILY`, `REL_WEEKLY`), computed per source from that
source's own numbers only:

```
bps    = ((close - open) * 10000) // open
winner = the strictly greatest bps, else TIE
```

A joint best is a `TIE`, including when every asset is flat. Note the winner can
be a *loss*: if everything fell, the asset that fell least wins.

---

## Step 5 — combine

```
final = a_verdict  if  a_verdict == b_verdict and neither is TIE
        else INCONCLUSIVE
```

Which means:

| Source A | Source B | Result |
|---|---|---|
| UP | UP | **UP** |
| DOWN | DOWN | **DOWN** |
| NEAR | NEAR | **NEAR** |
| UP | DOWN | INCONCLUSIVE |
| NEAR | SOL | INCONCLUSIVE |
| TIE | anything | INCONCLUSIVE |
| anything | TIE | INCONCLUSIVE |
| empty | anything | INCONCLUSIVE |

**A single source can never produce a direction or a winner.** This is not a
policy check bolted on top — `_combine` has no branch that returns a result from
one input.

---

## Step 6 — the agreed payload

The block returns one canonical string:

```
v1|kind|category|asset|timeframe|source_a|source_b|window_id|A_SERIES|a_verdict|B_SERIES|b_verdict|final
```

`strict_eq` then requires every validator to have produced this string **byte for
byte**. Each validator fetched both feeds itself. If one saw different data,
there is no agreement and nothing settles.

This is why the payload is a string rather than a structure: serialisation drift
between validators would break consensus for reasons that have nothing to do
with the market.

Prices are rendered from the scaled integers, so a feed respelling `115.15` as
`115.15000000` cannot split consensus
(`test_validator_agrees_across_cosmetic_decimal_differences`).

---

## Step 7 — re-derive it offline

`strict_eq` proves the validators agreed on some bytes. It does not prove those
bytes are true. `_parse_agreed` therefore re-checks everything, with no network
access:

1. 13 fields, version `v1`;
2. `kind`, `category`, `asset` bind to **this** market;
3. `timeframe`, `window_id` bind to **this** window;
4. `source_a` and `source_b` are the two expected feeds — naming one feed twice
   is rejected, because that would not be two sources;
5. series length and symbol order match the catalog;
6. every open and close is positive;
7. `a_verdict` recomputed from `A_SERIES` matches the claim;
8. `b_verdict` recomputed from `B_SERIES` matches the claim;
9. `final` recomputed from the two verdicts matches the claim;
10. a settled result is `UP`, `DOWN`, or a catalog symbol.

Anything else raises `INVARIANT:` and reverts. A leader that asserts a winner
without the prices to back it does not get one.

The verified payload is then stored verbatim as the market's evidence, and shown
on the market page with both series laid out side by side.

---

## Step 8 — settle

```python
m.settled = True
m.outcome = final          # UP | DOWN | <symbol> | INCONCLUSIVE
m.settled_at = now
m.evidence = agreed
```

No funds move here. Settling records the outcome; wallets withdraw themselves.

---

## Step 9 — claim

`claim(market_id)`, by the position owner, idempotent.

| Situation | Payout |
|---|---|
| settled, you hold the winning side | `pool * your_stake // winning_side_total` |
| settled, you hold a losing side | `CLAIMED:0:LOST` |
| settled, **nobody** held the winning side | your own stake back |
| `INCONCLUSIVE` | your own stake back |

Winners split the **entire** pool, including the losers' stakes. Floor division
leaves at most a few wei of dust in the contract; it is not sweepable, because
sweeping would require a privileged address.

Double-claiming is rejected with `EXPECTED:ALREADY_CLAIMED`.

---

## Retrying

Settling is safe to retry. A `TRANSIENT` or `EXTERNAL` failure records nothing —
the market is still unsettled with an empty outcome — and it stays in the resolve
queue until either it settles or the five-day terminal refund takes over.

---

## What the caller controls

Nothing that affects the outcome.

* ✗ prices, URLs, feed names, slugs, winners, directions, results
* ✗ which window — that is fixed at creation
* ✗ when the window opens or closes — derived from the GMT+1 calendar
* ✓ *whether to try now*, and paying the gas for it

That is the entire surface.

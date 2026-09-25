# How a round gets graded

From "the window closed" to "GEN left the contract", in order, with the exact
checks at each step.

`score_round(round_id)` takes **one argument**. There is no overload, no
optional price, no URL, no winner, no admin variant. A caller cannot influence
the result, only trigger the attempt.

---

## Step 0 — who may call it

Anyone. There is no scorer role, no allowlist, no fee, and no owner. The caller
pays gas and gets nothing beyond an unblocked round. The Score queue page lists
everything currently scoreable.

---

## Step 1 — deterministic pre-checks

Before any network access:

| Check | Failure |
|---|---|
| round exists | `EXPECTED:NO_SUCH_ROUND` |
| not already scored | `EXPECTED:ALREADY_SCORED` |
| `now >= scoreable_at` | `EXPECTED:WINDOW_NOT_CLOSED` |

`now` is consensus time, parsed from `gl.message_raw['datetime']`.

---

## Step 2 — the expiry branch

```python
if now >= expires_at:          # scoreable_at + 5 days
    status = VOID_EXPIRED
    evidence = "f1|EXPIRED|<timestamp>"
    return "VOID:EXPIRED"
```

This returns **before the equivalence block exists**, so no feed is contacted. If
a round has gone five days without anyone pricing it — a feed broke, an asset
delisted, nobody cared — the contract returns every entry fee rather than
reaching for a number it cannot verify.

`test_expiry_refunds_with_zero_http` enforces this by running the call with zero
web mocks and `strict_mocks` on, so any outbound request would raise.

---

## Step 3 — capture, then fetch

Everything the closure needs is read out of storage **first**, because a
non-deterministic block cannot touch storage:

```python
asset, category, timeframe = r.asset, r.category, r.timeframe
window_id, window_start, window_end = r.window_id, int(r.window_start), int(r.window_end)
```

Then, inside `gl.eq_principle.strict_eq`, exactly **two** requests — one per
feed. A round asks about a single asset, so this count never grows.

### Feed A — Gate.io

Request `interval=1h` candles from `window_start` to `window_end - 1`, then:

1. the row count must equal `(window_end - window_start) / 3600` exactly — 24
   for a day, 168 for a week (`EXTERNAL:GATE_CANDLE_COUNT`);
2. every open time must be hour-aligned (`EXTERNAL:GATE_TS_UNALIGNED`);
3. every candle must be closed (`EXTERNAL:GATE_CANDLE_OPEN`);
4. every hour in the window must be present (`EXTERNAL:GATE_MISSING_HOUR`);
5. the close is field `[2]` of the candle **at `window_end - 3600`**.

Selection is by timestamp, never array position. Reversing the array does not
change the answer, and a UTC-aligned day — one hour off a GMT+1 day — is
rejected rather than silently used.

### Feed B — CoinGecko

Request `market_chart/range` from `window_start - 3600` to `window_end + 3600`,
so the closing instant is an interior point, then take the sample at **exactly**
`window_end` (`EXTERNAL:CG_NO_SAMPLE_AT_END` if absent).

There is no nearest-point fallback. A series that stops an hour short fails
rather than substituting its last point.

### Shared handling

- Status 408 / 425 / 429 / 5xx → `TRANSIENT:HTTP_<code>` (retryable).
- Any other non-200 → `EXTERNAL:HTTP_<code>`.
- Body over 60 000 bytes → `EXTERNAL:BODY_TOO_LARGE`.
- Non-UTF-8 → `EXTERNAL:NOT_UTF8`; unparseable → `EXTERNAL:BAD_JSON`.
- Bodies decode with `json.loads(text, parse_float=str)`, so every price stays
  exact decimal text and **no float ever touches the grading**.

---

## Step 4 — make the two feeds converge

```
gap = |A − B| ÷ min(A, B)          in basis points

gap ≤ 50 bp  ->  settled = (A + B) ÷ 2
gap >  50 bp ->  VOID_SPREAD
```

This is the part that differs most from a market settlement. The feeds are not
producing verdicts for comparison; they are producing **values that must
converge**. Two sources agreeing that a price "went up" would be useless here — a
forecast has to be graded against an actual number.

If they diverge past the tolerance there is no honest number to grade against,
so the round voids and every entry fee is refundable. A single feed can never
price a round, because the midpoint of one number is not defined.

---

## Step 5 — the agreed payload

The block returns one canonical string, 11 fields:

```
f1|category|asset|timeframe|window_id|source_a|source_b|a_close|b_close|gap_bps|settled
```

`strict_eq` then requires every validator to have produced this string **byte for
byte**. Each fetched both feeds itself. If one saw different data, there is no
agreement and nothing is scored.

Prices render from the scaled integers, so a feed respelling `116.61` as
`116.61000000` cannot split consensus.

---

## Step 6 — re-derive it offline

`strict_eq` proves the validators agreed on some bytes, not that those bytes are
true. `_parse_agreed` re-checks everything, with no network access:

1. 11 fields, version `f1`;
2. `category` and `asset` bind to **this** round;
3. `timeframe` and `window_id` bind to **this** window;
4. `source_a` and `source_b` are the two expected feeds;
5. both closes are positive;
6. the gap recomputed from the two closes matches the claim;
7. if the gap exceeds tolerance, the payload must say `VOID_SPREAD`;
8. otherwise the settled price must equal the recomputed midpoint.

Anything else raises `INVARIANT:` and reverts. A leader that asserts a price
without the two closes to back it does not get one.

---

## Step 7 — grade the field

With the settled price known, the contract walks the roster once — bounded by
`MAX_ENTRIES` = 200 — and sums everyone's accuracy weight:

```
error_i  = |forecast_i − settled| ÷ settled      in basis points
weight_i = 1000 − error_i, or 0 once error_i ≥ 1000
Σweights = sum over all entrants
```

Only the total is stored. Each entrant's own weight is recomputed at collection
time from their stored forecast, so collecting stays O(1) no matter how large
the field.

If entrants existed but **every** weight is zero, nobody's accuracy earned the
pot: the round becomes `VOID_NO_SCORES` and all fees are refundable. An *empty*
round is not that case — it prices normally, there is simply nobody to pay.

---

## Step 8 — collect

`collect(round_id)`, by the entrant, idempotent.

| Situation | Payout |
|---|---|
| scored, weight > 0 | `pot × weight ÷ Σweights` |
| scored, weight = 0 | `COLLECTED:0:OUTSIDE_BAND` |
| any void | your entry fee back |

Floor division leaves at most a few wei of dust per round. It is not sweepable,
because sweeping would need a privileged address.

Double-collecting is rejected with `EXPECTED:ALREADY_COLLECTED`.

---

## Retrying

Scoring is safe to retry. A `TRANSIENT` or `EXTERNAL` failure records nothing —
the round is still unscored with an empty status — and it stays in the queue
until either it prices or the five-day expiry takes over.

---

## What the caller controls

Nothing that affects the result.

- ✗ prices, URLs, feed names, the settled value, anyone's grade
- ✗ which window — fixed when the round opened
- ✗ when the window opens or closes — derived from the GMT+1 calendar
- ✓ *whether to try now*, and paying the gas for it

That is the entire surface.

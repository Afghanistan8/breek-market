# Breek — architecture

## Why this needs GenLayer

Breek's central claim is that no party decides the number everyone is graded
against. That is only possible if the *contract itself* can read the open
internet and still reach consensus.

A conventional chain cannot do this. A contract there has no network access, so
someone must push a price on-chain: an admin, a keeper, an oracle committee. That
someone is then the trust assumption, no matter how the rest is engineered.

GenLayer validators each execute the contract independently, including its
non-deterministic parts, and then vote on whether they agree. Breek puts both
feed fetches inside `gl.eq_principle.strict_eq`, which agrees only when every
validator's result is **byte-identical**. That turns "what did this actually
close at?" into a question the network answers directly, with no privileged
address anywhere in the system.

## Shape of the system

```
                    anyone                anyone               entrant
                      |                     |                      |
                 open_round            score_round             collect
                      |                     |                      |
  +-------------------v---------------------v----------------------v--------+
  |                      contracts/BreekForecast.py                         |
  |                                                                         |
  |  deterministic pre-checks  ->  eq_principle block  ->  deterministic     |
  |  (phase, window, binding)      (the ONLY network        re-derivation    |
  |                                 access in the app)      + grading pass   |
  +-----------------------------------|-------------------------------------+
                                      |
                       +--------------+--------------+
                       |                             |
             Feed A: gate.io                Feed B: coingecko
          last hourly candle close        sample at the closing instant
                       |                             |
                       +--------------+--------------+
                                      |
                   gap <= 50 bp ?  ->  settled = midpoint
                   otherwise       ->  VOID, every fee refunded
                                      |
                        every entrant scored by |forecast - settled|
```

The frontend reads views and sends four write methods. It never supplies a
price, a URL or an outcome; there is no argument through which it could.

## Repository layout

```
contracts/BreekForecast.py   the entire protocol, one file, no imports beyond json
docs/                        this file, SCORING.md, SPEC.md, LIVE.md, source-probe.json
frontend/                    Vite + React + TypeScript app
scripts/check_sources.py     live feed probe; the gate before trusting a parser
scripts/demo_rounds.py       full round walkthrough against LIVE feeds
scripts/net_exercise.py      drive a deployed contract (entering, scoring)
tests/direct/                in-process tests through the real py-genlayer runner
tests/consensus/             leader/validator convergence
```

## Contract internals

### Storage

```python
rounds:        TreeMap[u256, Round]               # the round records
round_order:   DynArray[u256]                     # creation order, for pagination
dedupe:        TreeMap[str, u256]                 # "category|asset|timeframe|window" -> id
entries:       TreeMap[u256, TreeMap[Address, Entry]]
roster:        TreeMap[u256, DynArray[Address]]   # entrants, for the one grading pass
participation: TreeMap[Address, DynArray[u256]]   # a wallet's rounds
```

The grading pass is the one place the contract iterates, and it happens exactly
once per round, at scoring time, bounded by `MAX_ENTRIES` = 200. It computes a
single number: the sum of everyone's accuracy weight.

That is deliberate. A weight depends on the settled price, which is unknown
until the round is scored, so it cannot be accumulated incrementally the way a
side total can. Storing only the sum keeps **collection O(1)** — an entrant's own
weight is recomputed from their stored forecast, so a round with two hundred
entrants costs the same to collect from as one with three.

### Phases are derived, never stored

```
now < locks_at                   -> ACCEPTING
now < scoreable_at               -> LOCKED
otherwise, unscored              -> AWAITING_SCORE
scored                           -> SCORED
any void status                  -> VOID
```

There is no state machine to advance and therefore no way for one to get stuck
mid-transition. A round's phase is a pure function of consensus time and one
stored status string.

### Time

Every lifecycle instant comes from `gl.message_raw['datetime']`, parsed by hand
into Unix seconds. The host clock is never read, and neither is any timezone
database: GMT+1 is applied as a bare `-3600` shift over hand-rolled proleptic
Gregorian date maths (`_days_from_civil` / `_civil_from_days`).

The defining property, pinned by
`test_daily_window_starts_2300_utc_previous_day`:

> A GMT+1 calendar day D starts at `day_index(D) * 86400 - 3600` — that is,
> 23:00 UTC on the day before D.

### The equivalence block

```python
def price_block() -> str:
    a_close = _fetch_gate_close(asset, window_start, window_end)
    b_close = _fetch_coingecko_close(asset, window_start, window_end)
    spread = _spread_bps(a_close, b_close)
    ...
    return "|".join((PAYLOAD_VERSION, category, asset, ...))

agreed = gl.eq_principle.strict_eq(price_block)
```

Three properties matter here:

1. **Everything the closure needs is captured as a plain local first.** A
   non-deterministic block cannot touch storage, so `asset`, `window_start` and
   the rest are read out of the round record *before* the closure is defined.
2. **No web request happens after the block returns.** Every `gl.nondet.web.get`
   call is inside `_fetch_gate_close` / `_fetch_coingecko_close`, which are only
   ever reached from inside the closure.
3. **The block returns one string.** Not a dict, not JSON — a pipe-delimited
   string, because `strict_eq` compares results exactly and any serialisation
   drift between validators would break consensus for no reason.

A round asks about one asset, so this is always **exactly two requests**,
regardless of how many people entered.

### Re-derivation is the security boundary

`strict_eq` guarantees the validators agreed on a string. It does **not**
guarantee the string means what it claims. `_parse_agreed` therefore treats the
payload as untrusted data: it re-binds every field to this round and this
window, recomputes the gap between the two closes, and recomputes the midpoint.
A payload that asserts a settled price its own two closes do not produce is
rejected with `INVARIANT:CONSENSUS`.

That is the difference between "the network agreed on some bytes" and "the round
was priced correctly".

## Money

* 1 GEN = 10<sup>18</sup> wei. Views return wei as decimal strings so nothing is
  lost to a JavaScript number.
* All settlement and payout maths is integer. The only place a decimal exists is
  in the text coming off a feed, and `_dec_to_scaled` converts it directly to a
  scaled integer without an intermediate float.
* Outbound value uses
  `gl.get_contract_at(to).emit_transfer(value=u256(amount), on="finalized")`.

### The stranded-fee bug, and how it is avoided

There is a known failure class in value-bearing contracts: a payable method
takes the value, then reverts, and the fee is credited to the contract with no
path back out.

`submit_forecast` is written so that **it never reverts once value has been
credited**. Every invalid case — unknown round, locked round, wrong fee, already
entered, round full, malformed forecast — refunds the attached value inside the
same call and returns a `REFUNDED:<reason>` string instead of raising. The only
`raise` in the method happens when `gl.message.value == 0`, where there is
nothing to strand.

The frontend surfaces this honestly: a `REFUNDED:` result renders as a warning,
not a success, because the transaction succeeded but the entrant did not get
what they wanted.

Two further paths exist so GEN can never sit unclaimable:

* **Any void status** — every entrant withdraws exactly their own fee.
* **Scored but nobody inside the band** — the pot no accuracy earned is returned
  rather than handed out anyway.

## Failure taxonomy

| Prefix | Meaning | Effect |
|---|---|---|
| `EXPECTED:` | bad input or wrong phase | reverts; nothing changes |
| `TRANSIENT:` | timeout, 429, 5xx | reverts; **market stays resolvable** |
| `EXTERNAL:` | source unusable for this window (missing hour, unclosed candle, bad JSON, oversized body) | reverts; retryable |
| `INVARIANT:` | agreed payload failed re-derivation | reverts; should never happen |

A failed scoring attempt records nothing at all —
`test_failed_round_leaves_nothing_behind` asserts the round is still unscored
with an empty status afterwards, and prices normally once the feed recovers.

### The terminal path

If five days pass after the window closed and nobody has scored it,
`score_round` marks the round `VOID_EXPIRED`, enables full refunds, and **makes
no web request whatsoever**. This is checked, not asserted: the test registers
zero web mocks with `strict_mocks` on, so any outbound request would raise. The
contract would rather pay everyone back than invent a price.

## Frontend

Vite + React + TypeScript + TanStack Query, with `genlayer-js` for chain access.

* `src/lib/env.ts` — chain id, RPC, contract address, explorer. Nothing
  network-dependent is hard-coded in a component.
* `src/lib/breek.ts` — the only module that touches the chain. Views are
  normalised from GenLayer's `Map` decoding into plain objects once, here.
* `src/lib/gmt.ts` — a direct mirror of the contract's calendar maths, so the UI
  and the contract cannot disagree about when a window opens.
* Forecasts are never rendered while a round is accepting; the contract itself
  withholds them from `get_leaderboard` until the round is priced, so the UI
  could not leak them even if it tried.
* `src/lib/wallet.tsx` — MetaMask GenLayer snap. The app never asks for,
  stores, or handles a private key.

Writes run through `preflight()`, which refuses to send if the connected network
has no usable fee/consensus configuration. A doomed transaction costs a
signature and teaches the user nothing, so it fails before send with a message
naming the network.

Prices shown in the interface are display-only and are never sent to the
contract.

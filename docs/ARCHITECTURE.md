# Breek Market — architecture

## Why this needs GenLayer

Breek's central claim is that no party decides an outcome. That is only possible
if the *contract itself* can read the open internet and still reach consensus.

A conventional chain cannot do this. A contract there has no network access, so
someone must push a price on-chain: an admin, a keeper, an oracle committee. That
someone is then the trust assumption, no matter how the rest is engineered.

GenLayer validators each execute the contract independently, including its
non-deterministic parts, and then vote on whether they agree. Breek puts both
feed fetches inside `gl.eq_principle.strict_eq`, which agrees only when every
validator's result is **byte-identical**. That turns "did the market really close
up?" into a question the network answers directly, with no privileged address
anywhere in the system.

## Shape of the system

```
                    anyone                anyone               position owner
                      |                     |                        |
                create_market          resolve_market              claim
                      |                     |                        |
  +-------------------v---------------------v------------------------v-------+
  |                       contracts/BreekMarket.py                            |
  |                                                                           |
  |  deterministic pre-checks  ->  eq_principle block  ->  deterministic       |
  |  (phase, window, binding)      (the ONLY network         re-derivation     |
  |                                 access in the app)       (_parse_agreed)   |
  +-----------------------------------|---------------------------------------+
                                      |
                       +--------------+--------------+
                       |                             |
             Source A: gate.io              Source B: coingecko
          hourly spot candlesticks        market_chart/range samples
                       |                             |
                  a_verdict                     b_verdict
                       +--------------+--------------+
                                      |
                          equal and not TIE ?  ->  settle
                          otherwise            ->  INCONCLUSIVE, refund all
```

The frontend reads views and sends four write methods. It never supplies a
price, a URL or an outcome; there is no argument through which it could.

## Repository layout

```
contracts/BreekMarket.py     the entire protocol, one file, no imports beyond json
docs/                        this file, RESOLUTION.md, SPEC.md, source-probe.json
frontend/                    Vite + React + TypeScript app
scripts/check_sources.py     live feed probe; the gate before trusting a parser
scripts/demo_markets.py      full lifecycle walkthrough against LIVE feeds
scripts/net_exercise.py      drive a deployed contract (staking, REL creation)
tests/direct/                in-process tests through the real py-genlayer runner
tests/consensus/             leader/validator convergence
```

## Contract internals

### Storage

```python
markets:       TreeMap[u256, Market]              # the market records
market_order:  DynArray[u256]                     # creation order, for pagination
dedupe:        TreeMap[str, u256]                 # "kind|category|asset|window" -> id
positions:     TreeMap[u256, TreeMap[Address, Position]]
side_totals:   TreeMap[u256, TreeMap[str, u256]]  # per-side staked totals
participation: TreeMap[Address, DynArray[u256]]   # a wallet's markets, for the portfolio
```

`TreeMap` is an ordered structure, so nothing depends on the iteration order of
an unordered one. More importantly, **payouts never iterate at all**: each wallet
claims its own position, and the only aggregate a payout needs is
`side_totals[market][outcome]`, maintained incrementally at stake time. A market
with ten thousand stakers costs the same to settle as one with three.

### Phases are derived, never stored

```
now < cutoff_at                  -> OPEN
now < settles_at                 -> WINDOW_LIVE
otherwise, unsettled             -> READY_TO_SETTLE
settled                          -> SETTLED_UP | SETTLED_DOWN | SETTLED_WINNER | INCONCLUSIVE
```

There is no state machine to advance and therefore no way for one to get stuck
mid-transition. A market's phase is a pure function of consensus time and one
boolean.

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
def settle_block() -> str:
    a_series = {}; b_series = {}
    for sym in symbols:
        a_series[sym] = _fetch_gate(sym, window_start, window_end)
        b_series[sym] = _fetch_coingecko(sym, window_start, window_end)
    ...
    return "|".join((PAYLOAD_VERSION, kind, category, ...))

agreed = gl.eq_principle.strict_eq(settle_block)
```

Three properties matter here:

1. **Everything the closure needs is captured as a plain local first.** A
   non-deterministic block cannot touch storage, so `window_start`, `symbols`,
   `kind` and the rest are read out of the market record *before* the closure is
   defined.
2. **No web request happens after the block returns.** Every `gl.nondet.web.get`
   call is inside `_fetch_gate` / `_fetch_coingecko`, which are only ever reached
   from inside the closure.
3. **The block returns one string.** Not a dict, not JSON — a pipe-delimited
   string, because `strict_eq` compares results exactly and any serialisation
   drift between validators would break consensus for no reason.

### Re-derivation is the security boundary

`strict_eq` guarantees the validators agreed on a string. It does **not**
guarantee the string means what it claims. `_parse_agreed` therefore treats the
payload as untrusted data: it re-binds every field to this market and this
window, and recomputes both verdicts and the final result from the raw prices.
A payload that asserts `UP` while its own series shows a fall is rejected with
`INVARIANT:A_VERDICT`.

That is the difference between "the network agreed on some bytes" and "the
market settled correctly".

## Money

* 1 GEN = 10<sup>18</sup> wei. Views return wei as decimal strings so nothing is
  lost to a JavaScript number.
* All settlement and payout maths is integer. The only place a decimal exists is
  in the text coming off a feed, and `_dec_to_scaled` converts it directly to a
  scaled integer without an intermediate float.
* Outbound value uses
  `gl.get_contract_at(to).emit_transfer(value=u256(amount), on="finalized")`.

### The stranded-stake bug, and how it is avoided

There is a known failure class in value-bearing contracts: a payable method
takes the value, then reverts, and the stake is credited to the contract with no
path back out.

`take_position` is written so that **it never reverts once value has been
credited**. Every invalid case — unknown market, closed window, wrong side, side
switch, below 2 GEN, above 4 GEN — refunds the attached value inside the same
call and returns a `REFUNDED:<reason>` string instead of raising. The only
`raise` in the method happens when `gl.message.value == 0`, where there is
nothing to strand.

The frontend surfaces this honestly: a `REFUNDED:` result is rendered as a
warning, not a success, because the transaction succeeded but the user did not
get what they wanted.

Two further paths exist so GEN can never sit unclaimable:

* **Inconclusive** — every wallet withdraws exactly its own stake.
* **Settled with no winners** — if nobody backed the winning side, every wallet
  is refunded rather than leaving the pool with no claimant.

## Failure taxonomy

| Prefix | Meaning | Effect |
|---|---|---|
| `EXPECTED:` | bad input or wrong phase | reverts; nothing changes |
| `TRANSIENT:` | timeout, 429, 5xx | reverts; **market stays resolvable** |
| `EXTERNAL:` | source unusable for this window (missing hour, unclosed candle, bad JSON, oversized body) | reverts; retryable |
| `INVARIANT:` | agreed payload failed re-derivation | reverts; should never happen |

A failed settle records nothing at all —
`test_transient_round_leaves_nothing_behind` asserts the market is still
unsettled with an empty outcome afterwards, and settles normally once the feed
recovers.

### The terminal path

If five days pass after the window closed and nobody has settled it,
`resolve_market` marks the market `INCONCLUSIVE`, enables full refunds, and
**makes no web request whatsoever**. This is checked, not asserted: the test
registers zero web mocks with `strict_mocks` on, so any outbound request would
raise. The contract would rather pay everyone back than invent a price.

## Frontend

Vite + React + TypeScript + TanStack Query, with `genlayer-js` for chain access.

* `src/lib/env.ts` — chain id, RPC, contract address, explorer. Nothing
  network-dependent is hard-coded in a component.
* `src/lib/breek.ts` — the only module that touches the chain. Views are
  normalised from GenLayer's `Map` decoding into plain objects once, here.
* `src/lib/gmt.ts` — a direct mirror of the contract's calendar maths, so the UI
  and the contract cannot disagree about when a window opens.
* `src/lib/wallet.tsx` — MetaMask GenLayer snap. The app never asks for,
  stores, or handles a private key.

Writes run through `preflight()`, which refuses to send if the connected network
has no usable fee/consensus configuration. A doomed transaction costs a
signature and teaches the user nothing, so it fails before send with a message
naming the network.

Charts and prices in the interface are display-only and are never sent to the
contract.

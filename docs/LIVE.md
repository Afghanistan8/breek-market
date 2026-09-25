# Breek Market — live deployment status

What is actually deployed, what has actually been executed on it, and what has
not. Anything unverified is marked as such rather than implied.

Last updated: 2026-09-25.

---

## Addresses and versions

| | |
|---|---|
| Network | **studionet** (GenLayer Studio Network) |
| Chain id | `61999` |
| RPC | `https://studio.genlayer.com/api` |
| Contract | [`0xC69eDF8Cd4d723002d1d658CAB3AD616A34532d7`](https://genlayer-explorer.vercel.app/address/0xC69eDF8Cd4d723002d1d658CAB3AD616A34532d7) |
| Runner | `py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6` |
| Frontend | https://breek-market-puce.vercel.app/ |
| `genlayer-js` | **1.1.8** (pinned exactly, no caret) |
| `genlayer` CLI | 0.39.2 |
| `genlayer-test` | 0.29.2 · `genvm-linter` 0.11.0 |

No contract redeploy has been needed. This is the original deployment.

---

## Write status

**Browser writes: available.** Any EIP-1193 wallet can sign.

This was previously documented the wrong way round, so it is worth stating the
mechanism precisely. genlayer-js does **not** sign through the GenLayer MetaMask
snap. When a client is built with a string address plus a `provider`, its
transport delegates these methods straight to that provider:

```
PROVIDER_METHODS = { eth_accounts, eth_requestAccounts, eth_sendTransaction,
                     eth_signTransaction, personal_sign, eth_signTypedData_v4 }
```

and the wallet branch of `_sendTransaction` is a plain `eth_sendTransaction` to
the consensus contract. The snap only gives MetaMask a richer rendering of a
GenLayer transaction. Breek therefore offers it opportunistically and never
requires it — **MetaMask, OKX Wallet, Rabby and any other EIP-1193 wallet can
create, stake, settle and claim.**

What genuinely gates a write is the consensus contract configuration. Without it
`_sendTransaction` throws `Consensus main contract address not found`. The app
runs `initializeConsensusSmartContract()` as a preflight straight after binding
the wallet, and if it fails the exact error is shown in the banner and in place
of every action control. Nothing is sent that cannot succeed.

### Fee flow

`estimateTransactionFeesForWrite` **does not exist in any published
genlayer-js**, including 1.1.8. The `genlayer` CLI feature-detects it
(`typeof client.estimateTransactionFeesForWrite === "function"`) and falls back,
and it writes to studionet successfully on 1.1.8 without any fee object.

`frontend/src/lib/breek.ts` does the same: it uses the fee API when a build
provides one and writes unpriced otherwise. No fee flow is required on
studionet today.

---

## Executed on chain

### Markets created

All three created through `create_market` on the live contract. No admin
involved; `create_market` is permissionless.

| id | kind | asset | GMT+1 window | phase | evidence |
|---|---|---|---|---|---|
| 1 | `DIR_DAILY` | SOL | 2026-09-27 | OPEN | returned `CREATED:1` |
| 2 | `DIR_DAILY` | ETH | 2026-09-26 | OPEN | returned `CREATED:2` |
| 3 | `DIR_WEEKLY` | NEAR | week of 2026-09-28 | OPEN | tx `0x5a19c0337680013555edc7428e14266a5f42067bef41980bd18839aa48b69584`, `MAJORITY_AGREE`, returned `CREATED:3` |

Read back from the contract after creation:

```
get_stats  -> markets: '3', settled: '0', total_staked_wei: '0'

get_market 2 -> kind DIR_DAILY, asset ETH, window_id 2026-09-26,
                cutoff_at 1790377200, settles_at 1790463600, phase OPEN

get_market 3 -> kind DIR_WEEKLY, asset NEAR, window_id 2026-09-28,
                window_start 1790550000, window_end 1791154800, phase OPEN
```

Market 3 spans exactly `1791154800 - 1790550000 = 604800` seconds — one GMT+1
week, Monday to Monday.

### Contract deployment

```
deploy tx 0xf4a7c7032fee3196aa3140c8762538b0685aefa6a861697cd742f3c3c97891b7
          MAJORITY_AGREE, FINALIZED
```

---

## Not yet executed

**No stake has been placed on chain, so there is no stake hash here yet.**

This is a tooling limitation, not a product one:

* `genlayer` CLI 0.39.2 has **no `--value` flag**, so `take_position` (payable)
  cannot be called from it. The three creates above were possible only because
  `create_market` is non-payable.
* `scripts/net_exercise.py` can attach value, but it needs a signing key in
  `BREEK_PRIVATE_KEY`. That key was deliberately not extracted from the
  deployer keystore during this work.

Both paths to a stake are now open and untried:

```bash
# with a key you control
export BREEK_PRIVATE_KEY=0x...
python scripts/net_exercise.py --address 0xC69eDF8Cd4d723002d1d658CAB3AD616A34532d7 stake 2 UP 2
```

or, in the browser, connect OKX (or any wallet) at
https://breek-market-puce.vercel.app/market/2 and stake 2 GEN. This section will
carry the resulting hash once one of those has actually run.

**No market has been settled on chain.** Markets 1–3 have future windows, so
`resolve_market` correctly refuses them with `EXPECTED:WINDOW_NOT_CLOSED` until
the window closes. Settlement is exercised end to end against **live Gate.io and
CoinGecko data** — no mocks — by `scripts/demo_markets.py`, which warps consensus
time in-process:

```
DIR_DAILY SOL 2026-09-24
  -> resolve_market(1) -> SETTLED:UP   [2 live fetches]
     source A (gate.io):   SOL:115.15000000:116.61000000 -> UP
     source B (coingecko): SOL:115.09859487:116.55383196 -> UP
     final: UP

REL_DAILY 2026-09-24
  -> resolve_market(2) -> SETTLED:NEAR [6 live fetches]
     A: SOL +126, ETH -18, NEAR +596 -> NEAR
     B: SOL +126, ETH -20, NEAR +583 -> NEAR
```

---

## Verification status

| Check | Status |
|---|---|
| `python -m pytest tests` | 188 passed |
| `genvm-lint lint contracts/BreekMarket.py` | passed |
| `npx tsc --noEmit` (frontend) | clean |
| `npm run build` (frontend) | clean |
| Live URL reachable | 200, assets 200, SPA rewrite 200 |
| On-chain reads from the live site | working (catalog, stats, markets) |
| Wallet discovery + connect | verified against simulated EIP-6963 wallets |
| Real MetaMask / OKX popup | **not verified by the author** — needs a browser with the extension |
| On-chain stake | **not executed** (see above) |
| On-chain settlement | **not executed** (no window has closed yet) |

---

## Known limitations

* `genlayer` CLI 0.39.2 cannot attach value (`take_position`) and cannot encode
  an empty string, so `REL_*` markets cannot be created from it either — `""`
  is coerced to integer `0` and the contract correctly rejects it with
  `EXPECTED:REL_TAKES_NO_ASSET`. Use the frontend or `scripts/net_exercise.py`.
* `genvm-lint validate` cannot load the SDK on the current release: it looks
  under `runners/…` while the artifacts moved to
  `executor/v0.2.17/legacy-runners/…`. `genvm-lint lint` passes.
* `DOMINANCE` is listed but not settlable, and hourly is not shipped. Both are
  evidence-backed decisions recorded in [`SPEC.md`](SPEC.md); neither weakens
  the two-source rule.

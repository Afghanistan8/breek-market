# Breek — live deployment status

What is actually deployed, what has actually been executed on it, and what has
not. Anything unverified is marked as such rather than implied.

Last updated: 2026-09-26.

---

## Addresses and versions

| | |
|---|---|
| Network | **studionet** (GenLayer Studio Network) |
| Chain id | `61999` |
| RPC | `https://studio.genlayer.com/api` |
| Contract | [`0x4aDb6a8f9D0B920cC5699F75060324575C01E19a`](https://explorer-studio.genlayer.com/address/0x4aDb6a8f9D0B920cC5699F75060324575C01E19a) |
| Runner | `py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6` |
| Frontend | https://breek-market-puce.vercel.app/ |
| `genlayer-js` | **1.1.8** (pinned exactly, no caret) |
| `genlayer` CLI | 0.39.2 |
| `genlayer-test` | 0.29.2 · `genvm-linter` 0.11.0 |

Superseded deployments, kept here so an old link is traceable:

| Address | Why superseded |
|---|---|
| `0xC69eDF8Cd4d723002d1d658CAB3AD616A34532d7` | `BreekMarket` — the prediction-market mechanics, replaced wholesale |
| `0x2b5cF7247380d9B487758f27A2A5e1FFA7d821f7` | `BreekForecast` — carried the stranded-fee bug in SPEC section 14 |

---

## Write status

**Browser writes: executed on chain.** A payable `submit_forecast` from the
deployer wallet is finalized at
[`0x7a920956…cfcfd96f`](https://explorer-studio.genlayer.com/tx/0x7a920956422a32e678a4e57cdcd6a53f0eefcd93a2f62d509796055ecfcfd96f),
GenVM result SUCCESS, consensus Accepted, and the contract balance moved to
**1 GEN** — so the fee genuinely transferred rather than being refunded in
call. This was wallet-signed: the `genlayer` CLI cannot attach value at all,
and `scripts/net_exercise.py` needs `BREEK_PRIVATE_KEY`, which was never
exported. Which wallet brand rendered the prompt is not recorded here, because
it was not observed from this side.

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

### Rounds opened

Both through the permissionless `open_round`. No admin involved.

| id | asset | timeframe | GMT+1 window | phase |
|---|---|---|---|---|
| 1 | SOL | DAILY | 2026-09-27 | ACCEPTING |
| 2 | ETH | WEEKLY | week of 2026-09-28 | ACCEPTING |
| 3 | NEAR | DAILY | 2026-09-27 | ACCEPTING — **1 forecast, 1 GEN pot** |
| 4 | SOL | WEEKLY | week of 2026-09-28 | ACCEPTING |

### Forecasts submitted

| round | asset | entrant | revisions | forecast |
|---|---|---|---|---|
| 3 | NEAR | `0x4184bc…FB0df3` | 0 | **sealed until the round is priced** |

The number is not recorded here because it is not readable: `get_leaderboard`
withholds forecasts while a round is accepting, so nobody — including whoever
writes this file — can copy the field. It becomes visible when `score_round(3)`
runs, which is possible from **28 Sep 2026, 00:00 GMT+1**.

### Contract deployment

```
deploy tx 0x2f84b32f91aef3c05318b72fd367f61e24af65a2a4a9bf12259944af7f325714
          MAJORITY_AGREE, FINALIZED
```

### Transaction hashes, as the Studio explorer shows them

All six FINALIZED with GenVM result SUCCESS and consensus Accepted. This is the
contract's complete transaction history as the explorer lists it:

| Tx | Method |
|---|---|
| [`0x2f84b32f…7f325714`](https://explorer-studio.genlayer.com/tx/0x2f84b32f91aef3c05318b72fd367f61e24af65a2a4a9bf12259944af7f325714) | deploy |
| [`0x4becfd92…079845a1`](https://explorer-studio.genlayer.com/tx/0x4becfd92f229c2aa6fbdc3ea11fffb40484b2d405f72bebfe840565f079845a1) | `open_round` (round 1, SOL) |
| [`0xdc810014…3ad4a8d4`](https://explorer-studio.genlayer.com/tx/0xdc8100142806a843762a2119b9b2f507c2444e33203b32bb929670813ad4a8d4) | `open_round` (round 2, ETH) |
| [`0x22b78cd3…0dd1be74`](https://explorer-studio.genlayer.com/tx/0x22b78cd360fd97ccd747ff90b0172942adf58814fadfd66b727b16f20dd1be74) | `open_round` (round 3, NEAR) |
| [`0xc466681b…c933bfc8`](https://explorer-studio.genlayer.com/tx/0xc466681b48eea5343abbbbeddf4a1e16505dbf57e0e1721f34411b9dc933bfc8) | `open_round` (round 4, SOL weekly) |
| [`0x7a920956…cfcfd96f`](https://explorer-studio.genlayer.com/tx/0x7a920956422a32e678a4e57cdcd6a53f0eefcd93a2f62d509796055ecfcfd96f) | **`submit_forecast` (round 3, payable, 1 GEN)** |

Note the explorer host: `explorer-studio.genlayer.com`. The
`genlayer-explorer.vercel.app` host used earlier in this repo returns **503**
and every link through it was dead.

### Write paths verified on chain

Methods that take no value were exercised directly against the live contract:

```
score_round(1)  ->  EXPECTED:WINDOW_NOT_CLOSED
```

That single call proves rather a lot: `score_round` is callable on chain, the
consensus-time parser works there, the phase pre-checks fire, and
`gl.vm.UserError` propagates back through the receipt intact.

### Views verified on chain

Every view was called against the live contract and its key set compared field
by field against the TypeScript interfaces in `frontend/src/lib/breek.ts`:
`get_catalog`, `get_stats`, `get_round`, `get_phase`, `get_evidence`,
`get_leaderboard`, `get_entry`, `list_rounds`, `list_scoreable`,
`list_entries`. All match exactly. `get_evidence` on an unscored round
correctly omits the optional price fields.

---

## Verification status

| Check | Status |
|---|---|
| `python -m pytest tests` | 124 passed |
| `genvm-lint lint contracts/BreekForecast.py` | passed |
| `npx tsc --noEmit` (frontend) | clean |
| `npm run build` (frontend) | clean |
| Live URL reachable | 200, assets 200, SPA rewrite 200 |
| On-chain reads from the live site | working &mdash; cold cache-busted visit renders all four rounds |
| Client routes `/ /round/3 /open /score /me /how` | all 200; unknown paths 200 and redirect to the board |
| Live display prices from the deployed origin | working &mdash; both feeds fetched cross-origin, no proxy |
| Wallet discovery + connect | verified against simulated EIP-6963 wallets |
| Every view's keys vs its TS interface | verified field by field against the live contract |
| Non-payable write path on chain | verified (`score_round` -> `EXPECTED:WINDOW_NOT_CLOSED`) |
| Hostile inputs (oversized, malformed, wrong fee, cap) | 15 tests, all refund rather than revert |
| Payable write path on chain | verified &mdash; `submit_forecast` FINALIZED, contract balance 1 GEN |
| Wallet-signed write of any kind | verified by elimination (CLI cannot attach value; no key exported) |
| Which wallet rendered the prompt | **not recorded** &mdash; not observed from this side |
| On-chain scoring | **not executed** &mdash; no window has closed yet; round 3 is first, from 28 Sep 2026 00:00 GMT+1 |
| On-chain `collect` | **not executed** &mdash; nothing has been scored |

---

## Known limitations

* `genlayer` CLI 0.39.2 cannot reach `submit_forecast` or `revise_forecast`: it
  has no flag for attaching value, and its argument parser crashes on a decimal
  price (`BigInt("120.50")` throws). `open_round` works from it; everything
  else needs the frontend or `scripts/net_exercise.py`. The round 3 entry
  recorded above went through the wallet path for exactly this reason.
* `genvm-lint validate` cannot load the SDK on the current release: it looks
  under `runners/…` while the artifacts moved to
  `executor/v0.2.17/legacy-runners/…`. `genvm-lint lint` passes.
* `DOMINANCE` is listed but not settlable, and hourly is not shipped. Both are
  evidence-backed decisions recorded in [`SPEC.md`](SPEC.md); neither weakens
  the two-source rule.

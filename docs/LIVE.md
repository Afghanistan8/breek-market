# Breek — live deployment status

What is actually deployed, what has actually been executed on it, and what has
not. Anything unverified is marked as such rather than implied.

Last updated: 2026-09-26 (commit-reveal redeployment).

---

## Addresses and versions

| | |
|---|---|
| Network | **studionet** (GenLayer Studio Network) |
| Chain id | `61999` |
| RPC | `https://studio.genlayer.com/api` |
| Contract | [`0xFB18E78053c22d9e1C7681174f4cCA2a96E0AD18`](https://explorer-studio.genlayer.com/address/0xFB18E78053c22d9e1C7681174f4cCA2a96E0AD18) |
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
| `0x4aDb6a8f9D0B920cC5699F75060324575C01E19a` | `BreekForecast` — stored forecasts in plaintext and disclosed them through `get_entry` and `list_entries` before entries closed. SPEC section 16. There is no upgrade hook, by design, so the fix is a new address. |

---

## Write status

**Browser writes: executed on chain**, on the superseded contract. A payable
`submit_forecast` (the method commit-reveal replaced with `commit_forecast`) from the
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

### Current deployment

```
deploy tx 0x9566c9dd961170ea72d362c3f852bba01debf6cf577f087ce99f32438d81b2c2
          validator votes AGREE x5, ACCEPTED
contract  0xFB18E78053c22d9e1C7681174f4cCA2a96E0AD18
```

Commitment scheme, read back from the live contract through `get_catalog`:

```
commit_version   c1
commit_preimage  c1|<round_id>|<sender_lowercase_hex>|<scaled>|<salt>
commit_hash      sha256-hex
price_scale      100000000
salt_min_len     16
salt_max_len     64
```

`reveal_forecast` was called against the live contract on an open round and
correctly refused:

```
reveal_forecast(1, "120.00", "a1b2c3d4e5f60718")  ->  EXPECTED:REVEAL_NOT_OPEN
```

That confirms on chain what the tests assert in process: the reveal window does
not open while entries are still being taken.

### Rounds opened

Both through the permissionless `open_round`. No admin involved.

Four rounds are open on the current contract, all through the permissionless
`open_round` and all read back from chain:

| id | asset | timeframe | GMT+1 window | phase | entrants | revealed |
|---|---|---|---|---|---|---|
| 1 | SOL | DAILY | 2026-09-28 | ACCEPTING | 0 | 0 |
| 2 | ETH | WEEKLY | week of 2026-09-28 | ACCEPTING | 0 | 0 |
| 3 | NEAR | DAILY | 2026-09-28 | ACCEPTING | 0 | 0 |
| 4 | SOL | WEEKLY | week of 2026-09-28 | ACCEPTING | 0 | 0 |

### Forecasts submitted

**None yet on the current contract.** The one entry made on the superseded
contract — round 3, NEAR, `0x4184bc…FB0df3`, tx `0x7a920956…cfcfd96f` — was
made under the plaintext design. Its forecast (`5.00000000`) is public and
always was; that is the defect. It is not carried forward, because state does
not migrate and because it was never concealed in the first place.

Entering the current contract requires the payable `commit_forecast`, which the
CLI cannot reach: `genlayer write` has no flag for attaching native GEN, only
`--fee-value` for the fee deposit. Entry is therefore through the frontend or
`scripts/net_exercise.py`.

### Contract deployment

```
deploy tx 0x2f84b32f91aef3c05318b72fd367f61e24af65a2a4a9bf12259944af7f325714
          MAJORITY_AGREE, FINALIZED
```

### Transaction hashes, as the Studio explorer shows them

These six ran against the **superseded** contract
`0x4aDb6a8f9D0B920cC5699F75060324575C01E19a` and are kept because they are
still the evidence for the write paths listed below. All FINALIZED with GenVM
result SUCCESS and consensus Accepted:

| Tx | Method |
|---|---|
| [`0x2f84b32f…7f325714`](https://explorer-studio.genlayer.com/tx/0x2f84b32f91aef3c05318b72fd367f61e24af65a2a4a9bf12259944af7f325714) | deploy |
| [`0x4becfd92…079845a1`](https://explorer-studio.genlayer.com/tx/0x4becfd92f229c2aa6fbdc3ea11fffb40484b2d405f72bebfe840565f079845a1) | `open_round` (round 1, SOL) |
| [`0xdc810014…3ad4a8d4`](https://explorer-studio.genlayer.com/tx/0xdc8100142806a843762a2119b9b2f507c2444e33203b32bb929670813ad4a8d4) | `open_round` (round 2, ETH) |
| [`0x22b78cd3…0dd1be74`](https://explorer-studio.genlayer.com/tx/0x22b78cd360fd97ccd747ff90b0172942adf58814fadfd66b727b16f20dd1be74) | `open_round` (round 3, NEAR) |
| [`0xc466681b…c933bfc8`](https://explorer-studio.genlayer.com/tx/0xc466681b48eea5343abbbbeddf4a1e16505dbf57e0e1721f34411b9dc933bfc8) | `open_round` (round 4, SOL weekly) |
| [`0x7a920956…cfcfd96f`](https://explorer-studio.genlayer.com/tx/0x7a920956422a32e678a4e57cdcd6a53f0eefcd93a2f62d509796055ecfcfd96f) | **`submit_forecast` (round 3, payable, 1 GEN) — the plaintext method, now replaced** |

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
| `python -m pytest tests` | 159 passed |
| `node scripts/check_commit_vectors.mjs` | all vectors match; mutation-checked |
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
| Hostile inputs (oversized, malformed, wrong fee, cap) | covered; the payable call now takes only a digest |
| Cross-user concealment | 15 tests from the attacker's side; mutation-checked three ways |
| Reveal window guard on chain | verified &mdash; `EXPECTED:REVEAL_NOT_OPEN` on an open round |
| Payable write path on chain | verified on the superseded contract &mdash; FINALIZED, balance 1 GEN. The mechanism is unchanged; only the argument is now a digest. |
| Wallet-signed write of any kind | verified by elimination (CLI cannot attach value; no key exported) |
| Which wallet rendered the prompt | **not recorded** &mdash; not observed from this side |
| On-chain scoring | **not executed** &mdash; no window has closed yet |
| On-chain `commit_forecast` | **not executed on the current contract** &mdash; needs a wallet; the CLI cannot attach value |
| On-chain `reveal_forecast` success path | **not executed** &mdash; needs a commitment first |
| On-chain `collect` | **not executed** &mdash; nothing has been scored |

---

## Known limitations

* `genlayer` CLI 0.39.2 cannot reach `commit_forecast` (no flag for attaching
  native GEN &mdash; `genlayer write --help` offers only `--fee-value`) or
  `reveal_forecast` (its argument parser crashes on a decimal price, because
  `BigInt("120.50")` throws). `open_round`, `score_round` and `collect` all
  work from it, and `open_round` was used to open the four live rounds.
  Entering and revealing need the frontend or `scripts/net_exercise.py`.
* `genvm-lint validate` cannot load the SDK on the current release: it looks
  under `runners/…` while the artifacts moved to
  `executor/v0.2.17/legacy-runners/…`. `genvm-lint lint` passes.
* `DOMINANCE` is listed but not settlable, and hourly is not shipped. Both are
  evidence-backed decisions recorded in [`SPEC.md`](SPEC.md); neither weakens
  the two-source rule.

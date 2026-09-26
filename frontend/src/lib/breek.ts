/**
 * The only module that talks to the chain.
 *
 * Views are plain reads. Writes go through a preflight that refuses to send a
 * transaction the connected network cannot execute, because a doomed send costs
 * the user a signature and tells them nothing useful.
 */

import { createClient } from "genlayer-js";
import * as chains from "genlayer-js/chains";
import type { GenLayerChain } from "genlayer-js/types";

import { env } from "./env";

export const GEN = 1_000_000_000_000_000_000n;

// ---------------------------------------------------------------------------
// Types mirroring the contract's view payloads. Money always arrives as a
// decimal string so nothing is lost to JavaScript numbers.
// ---------------------------------------------------------------------------

export type Phase = "ACCEPTING" | "REVEALING" | "AWAITING_SCORE" | "SCORED" | "VOID";

export type RoundStatus =
  | ""
  | "SCORED"
  | "VOID_SPREAD"
  | "VOID_EXPIRED"
  | "VOID_NO_SCORES"
  | "VOID_NO_REVEALS";

export interface Round {
  round_id: string;
  category: string;
  asset: string;
  timeframe: "DAILY" | "WEEKLY";
  window_id: string;
  window_start: string;
  window_end: string;
  locks_at: string;
  scoreable_at: string;
  expires_at: string;
  opener: string;
  opened_at: string;
  pot_wei: string;
  entrants: string;
  status: RoundStatus;
  consensus: string;
  total_weight: string;
  scored_at: string;
  phase: Phase;
  /** How many entrants opened their commitment inside the reveal window. */
  revealed: string;
  entry_fee_wei: string;
  seconds_to_lock: string;
  seconds_to_score: string;
}

export interface Entry {
  round_id: string;
  who: string;
  entered: boolean;
  /** The sha256 digest on chain. Public, and says nothing about the price. */
  commitment: string;
  revealed: boolean;
  /** Empty until this entry has been revealed -- for everyone, including you. */
  forecast: string;
  revisions: string;
  collected: boolean;
  error_bps: string;
  weight: string;
  collectable_wei: string;
  outcome: string;
}

export interface LeaderboardRow {
  who: string;
  revisions: string;
  collected: boolean;
  revealed: boolean;
  forecast: string;
  error_bps: string;
  weight: string;
  share_wei: string;
}

export interface Leaderboard {
  round_id: string;
  status: RoundStatus;
  consensus: string;
  entries: LeaderboardRow[];
}

export interface Evidence {
  round_id: string;
  status: RoundStatus;
  scored_at: string;
  payload: string;
  source_a: string;
  source_b: string;
  tolerance_bps: string;
  a_close?: string;
  b_close?: string;
  spread_bps?: string;
  consensus?: string;
}

export interface CategoryInfo {
  key: string;
  assets: string[];
  priceable: boolean;
  basis: string;
  note: string;
}

export interface Catalog {
  timeframes: string[];
  categories: CategoryInfo[];
  entry_fee_wei: string;
  gen_wei: string;
  max_forecast: string;
  commit_version: string;
  commit_preimage: string;
  commit_hash: string;
  salt_min_len: string;
  salt_max_len: string;
  tolerance_bps: string;
  score_cutoff_bps: string;
  max_entries: string;
  sources: { a: string; b: string };
  timezone: string;
  price_scale: string;
  expiry_delay_s: string;
}

export interface Stats {
  rounds: string;
  scored: string;
  void: string;
  entries: string;
  total_paid_wei: string;
  contract_balance_wei: string;
  now: string;
}

// ---------------------------------------------------------------------------
// Client
// ---------------------------------------------------------------------------

/**
 * The chain definition, with the RPC forced to the configured one.
 *
 * The SDK ships its own URL for each named chain. If that diverges from
 * VITE_BREEK_RPC the app would silently read and write against a different node
 * than the one it advertises, so the configured endpoint always wins.
 */
const chainFor = (): GenLayerChain => {
  const table = chains as unknown as Record<string, GenLayerChain>;
  const named = table[env.network];
  const base =
    named && named.id === env.chainId
      ? named
      : Object.values(table).find(
          (c) => c && typeof c === "object" && "id" in c && c.id === env.chainId,
        );
  if (!base) {
    throw new Error(
      `No genlayer-js chain definition for chain id ${env.chainId} (${env.network}).`,
    );
  }
  if (base.rpcUrls?.default?.http?.[0] === env.rpc) return base;
  return {
    ...base,
    rpcUrls: { ...base.rpcUrls, default: { ...base.rpcUrls.default, http: [env.rpc] } },
  } as GenLayerChain;
};

let readClient: ReturnType<typeof createClient> | null = null;

export const getReadClient = () => {
  if (!readClient) readClient = createClient({ chain: chainFor(), endpoint: env.rpc });
  return readClient;
};

/**
 * A client bound to a specific wallet.
 *
 * Both `account` and `provider` matter. genlayer-js delegates
 * `eth_sendTransaction` to the provider, so without it there is no EIP-1193
 * channel and the wallet can never be prompted.
 */
export const makeClient = (account?: string, provider?: unknown) =>
  createClient({
    chain: chainFor(),
    endpoint: env.rpc,
    account: account as never,
    provider: provider as never,
  });

// ---------------------------------------------------------------------------
// Reads
// ---------------------------------------------------------------------------

/**
 * gen_call requires a `from` address even for a read. No view depends on who is
 * asking -- `get_entry` and `list_entries` take the address as an argument -- so
 * reads come from the zero address rather than requiring a wallet to browse.
 */
const READ_FROM = { address: "0x0000000000000000000000000000000000000000" };

/**
 * GenLayer calldata decodes a contract dict into a `Map`, not a plain object.
 * Normalise once, recursively, because views nest dicts inside lists.
 */
const plain = (value: unknown): unknown => {
  if (value instanceof Map) {
    const out: Record<string, unknown> = {};
    for (const [key, inner] of value) out[String(key)] = plain(inner);
    return out;
  }
  if (Array.isArray(value)) return value.map(plain);
  return value;
};

const read = async <T>(functionName: string, args: unknown[] = []): Promise<T> => {
  const client = getReadClient();
  const result = await client.readContract({
    address: env.contract as `0x${string}`,
    functionName,
    args: args as never,
    account: READ_FROM as never,
  });
  return plain(result) as T;
};

export const getCatalog = () => read<Catalog>("get_catalog");
export const getStats = () => read<Stats>("get_stats");
export const getRound = (id: number) => read<Round>("get_round", [id]);
export const getEvidence = (id: number) => read<Evidence>("get_evidence", [id]);
export const getPhase = (id: number) => read<Phase>("get_phase", [id]);

export const getLeaderboard = (id: number, limit = 50) =>
  read<Leaderboard>("get_leaderboard", [id, limit]);

export const listRounds = (offset = 0, limit = 50) =>
  read<{ total: string; offset: string; limit: string; now: string; rounds: Round[] }>(
    "list_rounds",
    [offset, limit],
  );

export const listScoreable = (limit = 50) =>
  read<{ now: string; rounds: Round[] }>("list_scoreable", [limit]);

export const getEntry = (id: number, who: string) => read<Entry>("get_entry", [id, who]);

export const listEntries = (who: string, limit = 50) =>
  read<{ who: string; now: string; entries: { round: Round; entry: Entry }[] }>(
    "list_entries",
    [who, limit],
  );

// ---------------------------------------------------------------------------
// Writes
// ---------------------------------------------------------------------------

export class WriteUnsupportedError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "WriteUnsupportedError";
  }
}

/**
 * Refuse to send a transaction this network cannot execute.
 *
 * Without the consensus contract configuration genlayer-js throws "Consensus
 * main contract address not found" from inside the send, after the wallet has
 * already been prompted. Fail here instead, with something a person can act on.
 */
export const preflight = async (client: ReturnType<typeof createClient>): Promise<void> => {
  try {
    await client.initializeConsensusSmartContract();
  } catch (error) {
    throw new WriteUnsupportedError(
      `${env.network} (chain ${env.chainId}) did not return a usable consensus/fee ` +
        `configuration, so writes cannot be signed against it. ` +
        `Underlying error: ${(error as Error).message}`,
    );
  }
};

export interface WriteResult {
  hash: string;
  status: string;
  returned?: string;
  error?: string;
}

const summarise = (receipt: unknown): { status: string; returned?: string; error?: string } => {
  const tx = receipt as Record<string, unknown>;
  const status = String(tx?.status_name ?? tx?.status ?? "UNKNOWN");
  const consensus = tx?.consensus_data as Record<string, unknown> | undefined;
  const leader = (consensus?.leader_receipt as Record<string, unknown>[] | undefined)?.[0];
  const result = leader?.result as Record<string, unknown> | undefined;
  const payload = result?.payload as Record<string, unknown> | string | undefined;
  const readable =
    typeof payload === "object" && payload !== null
      ? String((payload as Record<string, unknown>).readable ?? "")
      : typeof payload === "string"
        ? payload
        : undefined;
  if (leader?.execution_result === "ERROR") {
    return { status, error: readable || "contract reverted" };
  }
  return { status, returned: readable?.replace(/^"|"$/g, "") };
};

/**
 * Build the fee argument, when this SDK build has a fee API.
 *
 * genlayer-js 1.1.8 -- the version the genlayer CLI bundles and writes to
 * studionet with -- exposes no fee estimation, and writes succeed without one.
 * Feature-detect exactly as the CLI does rather than depending on either shape.
 */
const feesFor = async (
  client: ReturnType<typeof createClient>,
  write: { address: `0x${string}`; functionName: string; args: unknown[]; value: bigint },
): Promise<Record<string, unknown> | null> => {
  const estimate = (client as unknown as Record<string, unknown>)
    .estimateTransactionFeesForWrite;
  if (typeof estimate !== "function") return null;
  try {
    const result = await (estimate as (a: unknown) => Promise<unknown>).call(client, {
      address: write.address,
      functionName: write.functionName,
      args: write.args,
      value: write.value,
    });
    return result ? { fees: result } : null;
  } catch (error) {
    throw new WriteUnsupportedError(
      `${env.network} could not price this transaction: ${(error as Error).message}`,
    );
  }
};

const send = async (
  client: ReturnType<typeof createClient>,
  functionName: string,
  args: unknown[],
  value: bigint,
): Promise<WriteResult> => {
  await preflight(client);
  const write = {
    address: env.contract as `0x${string}`,
    functionName,
    args: args as never,
    value,
  };
  const fees = await feesFor(client, { ...write, args });
  const hash = await client.writeContract({ ...write, ...(fees ?? {}) } as never);
  type WaitArgs = Parameters<typeof client.waitForTransactionReceipt>[0];
  const receipt = await client.waitForTransactionReceipt({
    hash: hash as WaitArgs["hash"],
    status: "FINALIZED" as WaitArgs["status"],
    interval: 4000,
    retries: 150,
  });
  return { hash: String(hash), ...summarise(receipt) };
};

export const openRound = (
  client: ReturnType<typeof createClient>,
  category: string,
  asset: string,
  timeframe: string,
  windowId: string,
) => send(client, "open_round", [category, asset, timeframe, windowId], 0n);

/**
 * Enter a round with a sealed forecast.
 *
 * The argument is a sha256 digest, never a price. Calldata is public the
 * instant it is broadcast, so sending the number here would publish it to
 * everyone still able to enter -- which is exactly what the commitment exists
 * to prevent. Build the digest with `lib/commit.ts`.
 */
export const commitForecast = (
  client: ReturnType<typeof createClient>,
  roundId: number,
  commitment: string,
  feeWei: bigint,
) => send(client, "commit_forecast", [roundId, commitment], feeWei);

/** Replace a sealed forecast. Free, and only while entries are open. */
export const reviseCommitment = (
  client: ReturnType<typeof createClient>,
  roundId: number,
  commitment: string,
) => send(client, "revise_commitment", [roundId, commitment], 0n);

/**
 * Open a commitment, once entries have closed.
 *
 * This is the first and only time the price goes on chain. The contract
 * rebuilds the digest from it and refuses anything that does not match.
 */
export const revealForecast = (
  client: ReturnType<typeof createClient>,
  roundId: number,
  forecast: string,
  salt: string,
) => send(client, "reveal_forecast", [roundId, forecast, salt], 0n);

export const scoreRound = (client: ReturnType<typeof createClient>, roundId: number) =>
  send(client, "score_round", [roundId], 0n);

export const collect = (client: ReturnType<typeof createClient>, roundId: number) =>
  send(client, "collect", [roundId], 0n);

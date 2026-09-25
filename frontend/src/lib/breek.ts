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

export type Phase =
  | "OPEN"
  | "WINDOW_LIVE"
  | "READY_TO_SETTLE"
  | "SETTLED_UP"
  | "SETTLED_DOWN"
  | "SETTLED_WINNER"
  | "INCONCLUSIVE";

export interface Market {
  market_id: string;
  kind: "DIR_DAILY" | "DIR_WEEKLY" | "REL_DAILY" | "REL_WEEKLY";
  category: string;
  asset: string;
  timeframe: "DAILY" | "WEEKLY";
  window_id: string;
  window_start: string;
  window_end: string;
  cutoff_at: string;
  settles_at: string;
  terminal_refund_at: string;
  creator: string;
  created_at: string;
  pool_wei: string;
  stakers: string;
  settled: boolean;
  outcome: string;
  settled_at: string;
  phase: Phase;
  sides: Record<string, string>;
  valid_sides: string[];
  seconds_to_cutoff: string;
  seconds_to_settle: string;
}

export interface Position {
  market_id: string;
  who: string;
  has_position: boolean;
  side: string;
  amount_wei: string;
  claimed: boolean;
  claimable_wei: string;
  claim_kind: "" | "PAYOUT" | "LOST" | "REFUND_INCONCLUSIVE" | "REFUND_NO_WINNERS";
}

export interface Evidence {
  market_id: string;
  settled: boolean;
  outcome: string;
  settled_at: string;
  payload: string;
  source_a: string;
  source_b: string;
  a_series?: string;
  a_verdict?: string;
  b_series?: string;
  b_verdict?: string;
  final?: string;
}

export interface CategoryInfo {
  key: string;
  assets: string[];
  settlable: boolean;
  return_basis: string;
  note: string;
}

export interface Catalog {
  kinds: string[];
  timeframes: string[];
  categories: CategoryInfo[];
  stake: { min_wei: string; max_wei: string; gen_wei: string };
  sources: { a: string; b: string };
  timezone: string;
  price_scale: string;
  terminal_refund_delay_s: string;
}

export interface Stats {
  markets: string;
  settled: string;
  inconclusive: string;
  total_staked_wei: string;
  total_paid_wei: string;
  contract_balance_wei: string;
  now: string;
}

// ---------------------------------------------------------------------------
// Client
// ---------------------------------------------------------------------------

const chainFor = (): GenLayerChain => {
  const table = chains as unknown as Record<string, GenLayerChain>;
  const named = table[env.network];
  if (named && named.id === env.chainId) return named;
  const match = Object.values(table).find(
    (c) => c && typeof c === "object" && "id" in c && c.id === env.chainId,
  );
  if (match) return match;
  throw new Error(
    `No genlayer-js chain definition for chain id ${env.chainId} (${env.network}).`,
  );
};

let readClient: ReturnType<typeof createClient> | null = null;

export const getReadClient = () => {
  if (!readClient) readClient = createClient({ chain: chainFor() });
  return readClient;
};

export const makeClient = (account?: unknown) =>
  createClient({ chain: chainFor(), account: account as never });

// ---------------------------------------------------------------------------
// Reads
// ---------------------------------------------------------------------------

/**
 * gen_call requires a `from` address even for a read. None of Breek's views
 * depend on who is asking -- `get_position` and `list_positions` take the
 * address they are about as an explicit argument -- so reads are made from the
 * zero address rather than requiring a connected wallet to browse the app.
 */
const READ_FROM = { address: "0x0000000000000000000000000000000000000000" };

/**
 * GenLayer calldata decodes a contract dict into a `Map`, not a plain object.
 * Components want plain objects, so normalise once here -- recursively, because
 * views nest dicts inside lists (a market's `sides`, a portfolio row's
 * `market`/`position`).
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
export const getMarket = (id: number) => read<Market>("get_market", [id]);
export const getEvidence = (id: number) => read<Evidence>("get_evidence", [id]);
export const getPhase = (id: number) => read<Phase>("get_phase", [id]);

export const listMarkets = (offset = 0, limit = 50) =>
  read<{ total: string; offset: string; limit: string; now: string; markets: Market[] }>(
    "list_markets",
    [offset, limit],
  );

export const listResolvable = (limit = 50) =>
  read<{ now: string; markets: Market[] }>("list_resolvable", [limit]);

export const getPosition = (id: number, who: string) =>
  read<Position>("get_position", [id, who]);

export const listPositions = (who: string, limit = 50) =>
  read<{ who: string; now: string; positions: { market: Market; position: Position }[] }>(
    "list_positions",
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
 * genlayer-js derives a fee deposit from the network's fee API before it can
 * sign. If that path is missing on the connected network, sending anyway burns a
 * signature and surfaces an opaque RPC error, so fail here with something a
 * person can act on.
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

const send = async (
  client: ReturnType<typeof createClient>,
  functionName: string,
  args: unknown[],
  value: bigint,
): Promise<WriteResult> => {
  await preflight(client);
  const hash = await client.writeContract({
    address: env.contract as `0x${string}`,
    functionName,
    args: args as never,
    value,
  });
  // writeContract hands back the hash already in the branded shape
  // waitForTransactionReceipt wants, so pass it straight through.
  type WaitArgs = Parameters<typeof client.waitForTransactionReceipt>[0];
  const receipt = await client.waitForTransactionReceipt({
    hash: hash as WaitArgs["hash"],
    status: "FINALIZED" as WaitArgs["status"],
    interval: 4000,
    retries: 150,
  });
  return { hash: String(hash), ...summarise(receipt) };
};

export const createMarket = (
  client: ReturnType<typeof createClient>,
  kind: string,
  category: string,
  asset: string,
  timeframe: string,
  windowId: string,
) => send(client, "create_market", [kind, category, asset, timeframe, windowId], 0n);

export const takePosition = (
  client: ReturnType<typeof createClient>,
  marketId: number,
  side: string,
  gen: number,
) => send(client, "take_position", [marketId, side], BigInt(gen) * GEN);

export const resolveMarket = (client: ReturnType<typeof createClient>, marketId: number) =>
  send(client, "resolve_market", [marketId], 0n);

export const claim = (client: ReturnType<typeof createClient>, marketId: number) =>
  send(client, "claim", [marketId], 0n);

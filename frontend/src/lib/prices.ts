/**
 * Live prices, for the screen only.
 *
 * ================== READ THIS BEFORE CHANGING ANYTHING HERE ==================
 *
 * Nothing in this file may ever reach the contract.
 *
 * Breek's whole trust story is that the contract fetches its own prices inside
 * an equivalence-principle block, so that no browser, server or person can put
 * a number in front of it. These fetches happen in the viewer's tab, are
 * unverified, and exist purely so somebody deciding what to forecast can see
 * where the asset is trading right now.
 *
 * Concretely: no value produced here is ever passed to `submit_forecast`,
 * `revise_forecast` or `score_round` as an argument. The only path from this
 * data into a transaction is a human reading a number and choosing to type it.
 *
 * ============================================================================
 *
 * The two feeds shown are deliberately the same two the contract settles
 * against, so the display doubles as a preview of settlement: when they sit
 * close together a round will price cleanly, and when they drift apart it is a
 * live warning that the round could void.
 *
 * Both endpoints are keyless and send permissive CORS headers, verified from
 * the deployed origin, so there is no proxy in the path.
 */

/** CoinGecko ids for the catalog, used for the batched board query. */
export const CG_IDS: Record<string, string> = {
  SOL: "solana",
  ETH: "ethereum",
  NEAR: "near",
};

/** Gate.io spot pairs, matching the ones the contract settles against. */
export const GATE_PAIRS: Record<string, string> = {
  SOL: "SOL_USDT",
  ETH: "ETH_USDT",
  NEAR: "NEAR_USDT",
};

/**
 * Whether a display price can be shown for this asset at all.
 *
 * DOMINANCE assets are listed in the catalog but deliberately unpriceable, so
 * the UI must not promise a live number for them.
 */
export const hasFeeds = (symbol: string): boolean =>
  Boolean(GATE_PAIRS[symbol] && CG_IDS[symbol]);

export interface SpotPrice {
  /** Price as a plain number. Display only -- never sent anywhere. */
  usd: number;
  /** 24h change in percent, when the feed provides it. */
  change24h: number | null;
}

export type PriceMap = Record<string, SpotPrice>;

const CG_SIMPLE = "https://api.coingecko.com/api/v3/simple/price";
const GATE_TICKER = "https://api.gateio.ws/api/v4/spot/tickers";

/**
 * One request for the whole catalog, for the board.
 *
 * Batched deliberately: a per-row request would multiply calls by the number of
 * rounds on screen and trip CoinGecko's keyless rate limit for no benefit.
 */
export const fetchCatalogPrices = async (symbols: string[]): Promise<PriceMap> => {
  const ids = symbols.map((s) => CG_IDS[s]).filter(Boolean);
  if (ids.length === 0) return {};

  const url = `${CG_SIMPLE}?ids=${ids.join(",")}&vs_currencies=usd&include_24hr_change=true`;
  const res = await fetch(url);
  if (!res.ok) throw new Error(`CoinGecko returned ${res.status}`);
  const doc = (await res.json()) as Record<string, { usd?: number; usd_24h_change?: number }>;

  const out: PriceMap = {};
  for (const symbol of symbols) {
    const row = doc[CG_IDS[symbol]];
    if (row?.usd === undefined) continue;
    out[symbol] = {
      usd: row.usd,
      change24h: typeof row.usd_24h_change === "number" ? row.usd_24h_change : null,
    };
  }
  return out;
};

export interface FeedPair {
  /** Gate.io last trade, the quote source A settles from. */
  gate: number | null;
  /** CoinGecko spot, the quote source B settles from. */
  coingecko: number | null;
  /** Midpoint, the same way the contract would compute it. */
  mid: number | null;
  /** Distance between the feeds in basis points, relative to the lower. */
  gapBps: number | null;
  change24h: number | null;
}

/**
 * Both settlement feeds for one asset, side by side.
 *
 * The midpoint and gap are computed here the same way the contract does, but
 * on floats and on live rather than window-boundary data. It is an indication
 * of what settlement would look like, not a prediction of it, and certainly not
 * an input to it.
 */
export const fetchFeedPair = async (symbol: string): Promise<FeedPair> => {
  const pair = GATE_PAIRS[symbol];
  const id = CG_IDS[symbol];
  if (!pair || !id) throw new Error(`No feeds configured for ${symbol}`);

  const [gateRes, cgRes] = await Promise.allSettled([
    fetch(`${GATE_TICKER}?currency_pair=${pair}`).then((r) =>
      r.ok ? r.json() : Promise.reject(new Error(String(r.status))),
    ),
    fetch(`${CG_SIMPLE}?ids=${id}&vs_currencies=usd&include_24hr_change=true`).then((r) =>
      r.ok ? r.json() : Promise.reject(new Error(String(r.status))),
    ),
  ]);

  const gate =
    gateRes.status === "fulfilled" && Array.isArray(gateRes.value) && gateRes.value[0]?.last
      ? Number(gateRes.value[0].last)
      : null;

  const cgRow =
    cgRes.status === "fulfilled"
      ? (cgRes.value as Record<string, { usd?: number; usd_24h_change?: number }>)[id]
      : undefined;
  const coingecko = typeof cgRow?.usd === "number" ? cgRow.usd : null;

  const both = gate !== null && coingecko !== null;
  const low = both ? Math.min(gate as number, coingecko as number) : null;

  return {
    gate,
    coingecko,
    mid: both ? ((gate as number) + (coingecko as number)) / 2 : null,
    gapBps:
      both && low
        ? Math.round((Math.abs((gate as number) - (coingecko as number)) / low) * 10000)
        : null,
    change24h: typeof cgRow?.usd_24h_change === "number" ? cgRow.usd_24h_change : null,
  };
};

/** Render a price with a sensible number of decimals for its magnitude. */
export const fmtPrice = (value: number | null): string => {
  if (value === null || !Number.isFinite(value)) return "—";
  if (value >= 1000) return value.toFixed(2);
  if (value >= 1) return value.toFixed(3);
  return value.toFixed(5);
};

export const fmtChange = (pct: number | null): string =>
  pct === null || !Number.isFinite(pct) ? "" : `${pct >= 0 ? "+" : ""}${pct.toFixed(2)}%`;

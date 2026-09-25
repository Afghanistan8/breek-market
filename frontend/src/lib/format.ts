/** Display helpers. None of this touches the contract; it only renders. */

import { GEN } from "./breek";

/** wei -> "2.5 GEN", never via a JS number. */
export const fmtGen = (wei: string | bigint, decimals = 2): string => {
  const value = typeof wei === "bigint" ? wei : BigInt(wei || "0");
  const whole = value / GEN;
  const frac = value % GEN;
  if (frac === 0n) return `${whole}`;
  const padded = frac.toString().padStart(18, "0").slice(0, decimals).replace(/0+$/, "");
  return padded.length ? `${whole}.${padded}` : `${whole}`;
};

export const shortAddress = (address: string): string =>
  address && address.length > 10 ? `${address.slice(0, 6)}…${address.slice(-4)}` : address;

/** Percentage of a pool held by one side, as an integer 0-100. */
export const sharePct = (part: string, total: string): number => {
  const t = BigInt(total || "0");
  if (t === 0n) return 0;
  return Number((BigInt(part || "0") * 10000n) / t) / 100;
};

export const KIND_LABEL: Record<string, string> = {
  DIR_DAILY: "Direction - daily",
  DIR_WEEKLY: "Direction - weekly",
  REL_DAILY: "Relative return - daily",
  REL_WEEKLY: "Relative return - weekly",
};

export const KIND_SHORT: Record<string, string> = {
  DIR_DAILY: "DIR / D",
  DIR_WEEKLY: "DIR / W",
  REL_DAILY: "REL / D",
  REL_WEEKLY: "REL / W",
};

export const PHASE_LABEL: Record<string, string> = {
  OPEN: "Open for stakes",
  WINDOW_LIVE: "Window running",
  READY_TO_SETTLE: "Ready to settle",
  SETTLED_UP: "Settled UP",
  SETTLED_DOWN: "Settled DOWN",
  SETTLED_WINNER: "Settled",
  INCONCLUSIVE: "Inconclusive - refunded",
};

export const isSettled = (phase: string): boolean => phase.startsWith("SETTLED");

/** Describe a market in one line, without leaning on the raw kind string. */
export const marketTitle = (m: { kind: string; asset: string; category: string }): string => {
  if (m.kind.startsWith("DIR")) return `${m.asset} closes UP or DOWN`;
  return `Strongest ${m.category.toLowerCase()} return`;
};

/** Parse a "SYM:open:close,..." series from the settlement payload. */
export interface SeriesRow {
  symbol: string;
  open: string;
  close: string;
  bps: number;
}

export const parseSeries = (raw?: string): SeriesRow[] => {
  if (!raw) return [];
  return raw
    .split(",")
    .map((entry) => {
      const [symbol, open, close] = entry.split(":");
      if (!symbol || !open || !close) return null;
      const o = Number(open);
      const c = Number(close);
      const bps = o > 0 ? Math.floor(((c - o) / o) * 10000) : 0;
      return { symbol, open, close, bps };
    })
    .filter((row): row is SeriesRow => row !== null);
};

/** Trim a fixed-point price for display without changing its value. */
export const trimPrice = (value: string): string => {
  if (!value.includes(".")) return value;
  const trimmed = value.replace(/0+$/, "").replace(/\.$/, "");
  return trimmed.length ? trimmed : "0";
};

export const fmtBps = (bps: number): string => `${bps >= 0 ? "+" : ""}${bps} bps`;

export const errorText = (error: unknown): string => {
  const message = error instanceof Error ? error.message : String(error);
  const match = message.match(/(EXPECTED|TRANSIENT|EXTERNAL|INVARIANT):([A-Z0-9_]+)/);
  if (!match) return message;
  const [, kind, code] = match;
  const pretty = code.toLowerCase().replace(/_/g, " ");
  const prefix: Record<string, string> = {
    EXPECTED: "Rejected",
    TRANSIENT: "Feed temporarily unavailable",
    EXTERNAL: "Feed unusable for this window",
    INVARIANT: "Settlement evidence failed re-derivation",
  };
  return `${prefix[kind]}: ${pretty}`;
};

/** Display helpers. None of this touches the contract; it only renders. */

import { GEN } from "./breek";

/** wei -> "2.5", never via a JS number. */
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

/** Trim a fixed-point price for display without changing its value. */
export const trimPrice = (value: string): string => {
  if (!value || !value.includes(".")) return value || "";
  const trimmed = value.replace(/0+$/, "").replace(/\.$/, "");
  return trimmed.length ? trimmed : "0";
};

/** Basis points as a percentage, for people who do not think in bps. */
export const bpsAsPct = (bps: string | number, places = 2): string => {
  const n = typeof bps === "number" ? bps : Number(bps || 0);
  return `${(n / 100).toFixed(places)}%`;
};

export const ROUND_STATUS_LABEL: Record<string, string> = {
  "": "in progress",
  SCORED: "scored",
  VOID_SPREAD: "void — feeds diverged",
  VOID_EXPIRED: "void — expired",
  VOID_NO_SCORES: "void — nobody in range",
  VOID_NO_REVEALS: "void — nobody revealed",
};

export const PHASE_LABEL: Record<string, string> = {
  ACCEPTING: "Accepting forecasts",
  REVEALING: "Reveal your forecast",
  AWAITING_SCORE: "Awaiting score",
  SCORED: "Scored",
  VOID: "Void",
};

export const OUTCOME_LABEL: Record<string, string> = {
  SCORED: "scored",
  OUTSIDE_BAND: "outside the band",
  REFUND_VOID_SPREAD: "refund — feeds diverged",
  REFUND_VOID_EXPIRED: "refund — round expired",
  REFUND_VOID_NO_SCORES: "refund — nobody in range",
  REFUND_VOID_NO_REVEALS: "refund — nobody revealed",
  NOT_REVEALED: "not revealed — fee forfeited to the pot",
};

/** A round in one line. */
export const roundTitle = (r: { asset: string; timeframe: string }): string =>
  `${r.asset} close, ${r.timeframe === "WEEKLY" ? "week" : "day"}`;

/** Accuracy weight as a 0-100 bar width. */
export const weightPct = (weight: string, cutoff: string): number => {
  const w = Number(weight || 0);
  const c = Number(cutoff || 1000);
  if (c <= 0) return 0;
  return Math.max(0, Math.min(100, (w / c) * 100));
};

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
    INVARIANT: "Price evidence failed re-derivation",
  };
  return `${prefix[kind]}: ${pretty}`;
};

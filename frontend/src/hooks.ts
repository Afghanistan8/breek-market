/** TanStack Query wrappers around the contract views. */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import {
  collect,
  commitForecast,
  getCatalog,
  getEntry,
  getEvidence,
  getLeaderboard,
  getRound,
  getStats,
  listEntries,
  listRounds,
  listScoreable,
  openRound,
  revealForecast,
  reviseCommitment,
  scoreRound,
  type WriteResult,
} from "./lib/breek";
import { computeCommitment, newSalt, saveRevealKey } from "./lib/commit";
import { contractConfigured, env } from "./lib/env";
import { fetchCatalogPrices, fetchFeedPair } from "./lib/prices";
import { useWallet } from "./lib/wallet";

const enabled = { enabled: contractConfigured };

export const useCatalog = () =>
  useQuery({ queryKey: ["catalog"], queryFn: getCatalog, staleTime: 5 * 60_000, ...enabled });

export const useStats = () =>
  useQuery({ queryKey: ["stats"], queryFn: getStats, refetchInterval: 20_000, ...enabled });

export const useRounds = (offset = 0, limit = 50) =>
  useQuery({
    queryKey: ["rounds", offset, limit],
    queryFn: () => listRounds(offset, limit),
    refetchInterval: 20_000,
    ...enabled,
  });

export const useRound = (id: number) =>
  useQuery({
    queryKey: ["round", id],
    queryFn: () => getRound(id),
    refetchInterval: 15_000,
    enabled: contractConfigured && Number.isFinite(id) && id > 0,
  });

export const useLeaderboard = (id: number) =>
  useQuery({
    queryKey: ["leaderboard", id],
    queryFn: () => getLeaderboard(id, 50),
    refetchInterval: 20_000,
    enabled: contractConfigured && id > 0,
  });

export const useEvidence = (id: number, scored: boolean) =>
  useQuery({
    queryKey: ["evidence", id],
    queryFn: () => getEvidence(id),
    enabled: contractConfigured && scored && id > 0,
  });

export const useScoreable = () =>
  useQuery({
    queryKey: ["scoreable"],
    queryFn: () => listScoreable(50),
    refetchInterval: 15_000,
    ...enabled,
  });

export const useEntry = (id: number) => {
  const { address } = useWallet();
  return useQuery({
    queryKey: ["entry", id, address],
    queryFn: () => getEntry(id, address as string),
    enabled: contractConfigured && Boolean(address) && id > 0,
  });
};

export const useMyEntries = () => {
  const { address } = useWallet();
  return useQuery({
    queryKey: ["myEntries", address],
    queryFn: () => listEntries(address as string, 50),
    refetchInterval: 25_000,
    enabled: contractConfigured && Boolean(address),
  });
};

// ---------------------------------------------------------------------------
// Live prices -- DISPLAY ONLY. See the header of lib/prices.ts: nothing these
// return is ever passed to the contract as an argument.
// ---------------------------------------------------------------------------

/** Spot prices for the whole catalog, batched into one request for the board. */
export const useCatalogPrices = (symbols: string[]) =>
  useQuery({
    queryKey: ["prices", [...symbols].sort().join(",")],
    queryFn: () => fetchCatalogPrices(symbols),
    enabled: symbols.length > 0,
    refetchInterval: 45_000,
    staleTime: 30_000,
    // A missing price must never take the page down with it.
    retry: 1,
  });

/** Both settlement feeds for one asset, so a forecaster can see the spread. */
export const useFeedPair = (symbol: string | undefined) =>
  useQuery({
    queryKey: ["feedPair", symbol],
    queryFn: () => fetchFeedPair(symbol as string),
    enabled: Boolean(symbol),
    refetchInterval: 30_000,
    staleTime: 20_000,
    retry: 1,
  });

/** A ticking clock so countdowns move without refetching the chain. */
export const useNow = (): number => {
  const [now, setNow] = useState(() => Math.floor(Date.now() / 1000));
  useEffect(() => {
    const id = window.setInterval(() => setNow(Math.floor(Date.now() / 1000)), 1000);
    return () => window.clearInterval(id);
  }, []);
  return now;
};

// ---------------------------------------------------------------------------
// Writes
// ---------------------------------------------------------------------------

const useRequireClient = () => {
  const { client } = useWallet();
  return () => {
    if (!client) throw new Error("Connect a wallet first.");
    return client;
  };
};

const invalidateAll = (qc: ReturnType<typeof useQueryClient>) => {
  for (const key of ["rounds", "round", "scoreable", "myEntries", "entry", "stats", "evidence", "leaderboard"]) {
    void qc.invalidateQueries({ queryKey: [key] });
  }
};

export const useOpenRound = () => {
  const requireClient = useRequireClient();
  const qc = useQueryClient();
  return useMutation<WriteResult, Error, {
    category: string;
    asset: string;
    timeframe: string;
    windowId: string;
  }>({
    mutationFn: (i) =>
      openRound(requireClient(), i.category, i.asset, i.timeframe, i.windowId),
    onSuccess: () => invalidateAll(qc),
  });
};

/**
 * Seal a forecast and enter.
 *
 * The salt is generated here and saved before the transaction is sent, not
 * after. If the tab closes mid-signature the entry may still land, and an
 * entry whose salt was never written down cannot be revealed -- which forfeits
 * the fee. Writing first makes the worst case a stored key for a transaction
 * that never happened, which costs nothing.
 */
export const useCommitForecast = () => {
  const requireClient = useRequireClient();
  const { address } = useWallet();
  const qc = useQueryClient();
  return useMutation<
    WriteResult & { salt: string },
    Error,
    { roundId: number; forecast: string; feeWei: bigint }
  >({
    mutationFn: async ({ roundId, forecast, feeWei }) => {
      if (!address) throw new Error("Connect a wallet first.");
      const salt = newSalt();
      const digest = await computeCommitment(roundId, address, forecast, salt);
      saveRevealKey({
        contract: env.contract,
        roundId,
        address,
        forecast,
        salt,
        committedAt: Date.now(),
      });
      const res = await commitForecast(requireClient(), roundId, digest, feeWei);
      return { ...res, salt };
    },
    onSuccess: () => invalidateAll(qc),
  });
};

export const useReviseCommitment = () => {
  const requireClient = useRequireClient();
  const { address } = useWallet();
  const qc = useQueryClient();
  return useMutation<
    WriteResult & { salt: string },
    Error,
    { roundId: number; forecast: string }
  >({
    mutationFn: async ({ roundId, forecast }) => {
      if (!address) throw new Error("Connect a wallet first.");
      const salt = newSalt();
      const digest = await computeCommitment(roundId, address, forecast, salt);
      saveRevealKey({
        contract: env.contract,
        roundId,
        address,
        forecast,
        salt,
        committedAt: Date.now(),
      });
      const res = await reviseCommitment(requireClient(), roundId, digest);
      return { ...res, salt };
    },
    onSuccess: () => invalidateAll(qc),
  });
};

/** Open a commitment. The price reaches the chain here and nowhere earlier. */
export const useRevealForecast = () => {
  const requireClient = useRequireClient();
  const qc = useQueryClient();
  return useMutation<WriteResult, Error, {
    roundId: number;
    forecast: string;
    salt: string;
  }>({
    mutationFn: ({ roundId, forecast, salt }) =>
      revealForecast(requireClient(), roundId, forecast, salt),
    onSuccess: () => invalidateAll(qc),
  });
};

export const useScoreRound = () => {
  const requireClient = useRequireClient();
  const qc = useQueryClient();
  return useMutation<WriteResult, Error, number>({
    mutationFn: (roundId) => scoreRound(requireClient(), roundId),
    onSuccess: () => invalidateAll(qc),
  });
};

export const useCollect = () => {
  const requireClient = useRequireClient();
  const qc = useQueryClient();
  return useMutation<WriteResult, Error, number>({
    mutationFn: (roundId) => collect(requireClient(), roundId),
    onSuccess: () => invalidateAll(qc),
  });
};

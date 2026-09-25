/** TanStack Query wrappers around the contract views. */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import {
  collect,
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
  reviseForecast,
  scoreRound,
  submitForecast,
  type WriteResult,
} from "./lib/breek";
import { contractConfigured } from "./lib/env";
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

export const useSubmitForecast = () => {
  const requireClient = useRequireClient();
  const qc = useQueryClient();
  return useMutation<WriteResult, Error, {
    roundId: number;
    forecast: string;
    feeWei: bigint;
  }>({
    mutationFn: ({ roundId, forecast, feeWei }) =>
      submitForecast(requireClient(), roundId, forecast, feeWei),
    onSuccess: () => invalidateAll(qc),
  });
};

export const useReviseForecast = () => {
  const requireClient = useRequireClient();
  const qc = useQueryClient();
  return useMutation<WriteResult, Error, { roundId: number; forecast: string }>({
    mutationFn: ({ roundId, forecast }) =>
      reviseForecast(requireClient(), roundId, forecast),
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

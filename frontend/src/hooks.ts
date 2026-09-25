/** TanStack Query wrappers around the contract views. */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import {
  claim,
  createMarket,
  getCatalog,
  getEvidence,
  getMarket,
  getPosition,
  getStats,
  listMarkets,
  listPositions,
  listResolvable,
  resolveMarket,
  takePosition,
  type WriteResult,
} from "./lib/breek";
import { contractConfigured } from "./lib/env";
import { useWallet } from "./lib/wallet";

const enabled = { enabled: contractConfigured };

export const useCatalog = () =>
  useQuery({ queryKey: ["catalog"], queryFn: getCatalog, staleTime: 5 * 60_000, ...enabled });

export const useStats = () =>
  useQuery({ queryKey: ["stats"], queryFn: getStats, refetchInterval: 20_000, ...enabled });

export const useMarkets = (offset = 0, limit = 50) =>
  useQuery({
    queryKey: ["markets", offset, limit],
    queryFn: () => listMarkets(offset, limit),
    refetchInterval: 20_000,
    ...enabled,
  });

export const useMarket = (id: number) =>
  useQuery({
    queryKey: ["market", id],
    queryFn: () => getMarket(id),
    refetchInterval: 15_000,
    enabled: contractConfigured && Number.isFinite(id) && id > 0,
  });

export const useEvidence = (id: number, settled: boolean) =>
  useQuery({
    queryKey: ["evidence", id],
    queryFn: () => getEvidence(id),
    enabled: contractConfigured && settled && id > 0,
  });

export const useResolvable = () =>
  useQuery({
    queryKey: ["resolvable"],
    queryFn: () => listResolvable(50),
    refetchInterval: 15_000,
    ...enabled,
  });

export const usePosition = (id: number) => {
  const { address } = useWallet();
  return useQuery({
    queryKey: ["position", id, address],
    queryFn: () => getPosition(id, address as string),
    enabled: contractConfigured && Boolean(address) && id > 0,
  });
};

export const usePortfolio = () => {
  const { address } = useWallet();
  return useQuery({
    queryKey: ["portfolio", address],
    queryFn: () => listPositions(address as string, 50),
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
  void qc.invalidateQueries({ queryKey: ["markets"] });
  void qc.invalidateQueries({ queryKey: ["market"] });
  void qc.invalidateQueries({ queryKey: ["resolvable"] });
  void qc.invalidateQueries({ queryKey: ["portfolio"] });
  void qc.invalidateQueries({ queryKey: ["position"] });
  void qc.invalidateQueries({ queryKey: ["stats"] });
  void qc.invalidateQueries({ queryKey: ["evidence"] });
};

export const useCreateMarket = () => {
  const requireClient = useRequireClient();
  const qc = useQueryClient();
  return useMutation<WriteResult, Error, {
    kind: string;
    category: string;
    asset: string;
    timeframe: string;
    windowId: string;
  }>({
    mutationFn: (input) =>
      createMarket(
        requireClient(),
        input.kind,
        input.category,
        input.asset,
        input.timeframe,
        input.windowId,
      ),
    onSuccess: () => invalidateAll(qc),
  });
};

export const useTakePosition = () => {
  const requireClient = useRequireClient();
  const qc = useQueryClient();
  return useMutation<WriteResult, Error, { marketId: number; side: string; gen: number }>({
    mutationFn: ({ marketId, side, gen }) =>
      takePosition(requireClient(), marketId, side, gen),
    onSuccess: () => invalidateAll(qc),
  });
};

export const useResolveMarket = () => {
  const requireClient = useRequireClient();
  const qc = useQueryClient();
  return useMutation<WriteResult, Error, number>({
    mutationFn: (marketId) => resolveMarket(requireClient(), marketId),
    onSuccess: () => invalidateAll(qc),
  });
};

export const useClaim = () => {
  const requireClient = useRequireClient();
  const qc = useQueryClient();
  return useMutation<WriteResult, Error, number>({
    mutationFn: (marketId) => claim(requireClient(), marketId),
    onSuccess: () => invalidateAll(qc),
  });
};

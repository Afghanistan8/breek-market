/**
 * Wallet connection.
 *
 * Breek talks to GenLayer through the MetaMask GenLayer snap. The app never
 * asks for, stores, or handles a private key -- signing happens inside the
 * wallet, and this module only ever holds an address and a client bound to it.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import { makeClient, preflight } from "./breek";
import { env } from "./env";

type Client = ReturnType<typeof makeClient>;

interface WalletState {
  address: string | null;
  client: Client | null;
  connecting: boolean;
  error: string | null;
  /** True once a write has been proven possible against this network. */
  writesReady: boolean;
  connect: () => Promise<void>;
  disconnect: () => void;
}

const WalletContext = createContext<WalletState | null>(null);

const STORAGE_KEY = "breek.wallet.connected";

const hasEthereum = (): boolean =>
  typeof window !== "undefined" && Boolean((window as { ethereum?: unknown }).ethereum);

export const WalletProvider = ({ children }: { children: ReactNode }) => {
  const [address, setAddress] = useState<string | null>(null);
  const [client, setClient] = useState<Client | null>(null);
  const [connecting, setConnecting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [writesReady, setWritesReady] = useState(false);

  const connect = useCallback(async () => {
    setError(null);
    if (!hasEthereum()) {
      setError(
        "No wallet detected. Breek signs through the GenLayer MetaMask snap, so " +
          "install MetaMask and reload this page.",
      );
      return;
    }
    setConnecting(true);
    try {
      const next = makeClient();
      await next.connect(env.network as never);
      const accounts = await next.requestAddresses();
      const first = accounts?.[0];
      if (!first) throw new Error("The wallet returned no account.");

      // Prove a write is actually possible before the UI offers one.
      try {
        await preflight(next);
        setWritesReady(true);
      } catch (preflightError) {
        setWritesReady(false);
        setError((preflightError as Error).message);
      }

      setClient(next);
      setAddress(String(first).toLowerCase());
      window.localStorage.setItem(STORAGE_KEY, "1");
    } catch (err) {
      setError(
        `Could not connect to ${env.network}: ${(err as Error).message}. ` +
          "The GenLayer snap must be installed and permitted for this site.",
      );
      setClient(null);
      setAddress(null);
    } finally {
      setConnecting(false);
    }
  }, []);

  const disconnect = useCallback(() => {
    setClient(null);
    setAddress(null);
    setWritesReady(false);
    setError(null);
    window.localStorage.removeItem(STORAGE_KEY);
  }, []);

  // Reconnect silently if the user connected before and the wallet is present.
  useEffect(() => {
    if (window.localStorage.getItem(STORAGE_KEY) === "1" && hasEthereum()) {
      void connect();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const value = useMemo<WalletState>(
    () => ({ address, client, connecting, error, writesReady, connect, disconnect }),
    [address, client, connecting, error, writesReady, connect, disconnect],
  );

  return <WalletContext.Provider value={value}>{children}</WalletContext.Provider>;
};

export const useWallet = (): WalletState => {
  const ctx = useContext(WalletContext);
  if (!ctx) throw new Error("useWallet must be used inside a WalletProvider");
  return ctx;
};

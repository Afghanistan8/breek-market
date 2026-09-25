/**
 * Wallet discovery and connection.
 *
 * Breek never asks for, stores or handles a private key. Everything here is an
 * address and an EIP-1193 provider handed over by the wallet itself.
 *
 * Wallets are discovered with **EIP-6963**. The older `window.ethereum`
 * single-slot convention breaks as soon as two wallet extensions are installed:
 * they race for the slot and whoever loses becomes invisible. Discovering every
 * announced provider and letting the person choose fixes that.
 *
 * **Any EIP-1193 wallet can sign a Breek transaction.** genlayer-js sends a
 * plain `eth_sendTransaction` to the consensus contract and delegates it to
 * whichever provider the client was built with:
 *
 *     PROVIDER_METHODS = { eth_accounts, eth_requestAccounts,
 *                          eth_sendTransaction, eth_signTransaction,
 *                          personal_sign, eth_signTypedData_v4 }
 *
 * The GenLayer MetaMask snap is an optional convenience that gives MetaMask a
 * richer view of a GenLayer transaction. It is **not** a signing requirement,
 * so it is offered opportunistically when the wallet supports snaps and never
 * blocks anything when it does not.
 *
 * What genuinely gates writing is the consensus contract configuration: without
 * it `_sendTransaction` throws "Consensus main contract address not found".
 * That is what `writesReady` reflects.
 *
 * The SDK's own `client.connect()` is deliberately not used: it reads
 * `window.ethereum` directly, which would defeat the picker, it hard-requires
 * snaps, and it sources the RPC from the SDK's baked-in chain table rather than
 * ours. The same steps run here against the chosen provider instead.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import { makeClient, preflight } from "./breek";
import { env } from "./env";

type Client = ReturnType<typeof makeClient>;

export interface Eip1193Provider {
  request: (args: { method: string; params?: unknown[] | object }) => Promise<unknown>;
  on?: (event: string, handler: (...args: never[]) => void) => void;
  removeListener?: (event: string, handler: (...args: never[]) => void) => void;
}

export interface DiscoveredWallet {
  uuid: string;
  name: string;
  icon: string | null;
  rdns: string;
  provider: Eip1193Provider;
  /** Supports MetaMask Snaps, so the optional GenLayer snap can be added. */
  hasSnaps: boolean;
}

/** Optional MetaMask plugin that renders GenLayer transactions nicely. */
const SNAP_ID = "npm:genlayer-wallet-plugin";

const STORAGE_KEY = "breek.wallet.rdns";

export const SNAP_DOCS =
  "https://docs.genlayer.com/developers/intelligent-contracts/tools/genlayer-wallet";
export const METAMASK_INSTALL = "https://metamask.io/download/";

interface WalletState {
  wallets: DiscoveredWallet[];
  discovering: boolean;
  address: string | null;
  client: Client | null;
  connectedTo: DiscoveredWallet | null;
  connecting: boolean;
  error: string | null;
  /** True once this wallet is able to sign a Breek write. */
  writesReady: boolean;
  /** The exact reason writes are unavailable, when they are. */
  writeBlocker: string | null;
  pickerOpen: boolean;
  rescan: () => void;
  openPicker: () => void;
  closePicker: () => void;
  connect: (wallet: DiscoveredWallet) => Promise<void>;
  disconnect: () => void;
}

const WalletContext = createContext<WalletState | null>(null);

// ---------------------------------------------------------------------------
// Discovery
// ---------------------------------------------------------------------------

interface Eip6963Detail {
  info: { uuid: string; name: string; icon: string; rdns: string };
  provider: Eip1193Provider;
}

const probeSnaps = async (provider: Eip1193Provider): Promise<boolean> => {
  try {
    await provider.request({ method: "wallet_getSnaps" });
    return true;
  } catch {
    return false;
  }
};

const discoverWallets = (): Promise<DiscoveredWallet[]> =>
  new Promise((resolve) => {
    const found = new Map<string, DiscoveredWallet>();

    const onAnnounce = (event: Event) => {
      const detail = (event as CustomEvent<Eip6963Detail>).detail;
      if (!detail?.info?.rdns || found.has(detail.info.rdns)) return;
      found.set(detail.info.rdns, {
        uuid: detail.info.uuid,
        name: detail.info.name,
        icon: detail.info.icon ?? null,
        rdns: detail.info.rdns,
        provider: detail.provider,
        hasSnaps: false,
      });
    };

    window.addEventListener("eip6963:announceProvider", onAnnounce);
    window.dispatchEvent(new Event("eip6963:requestProvider"));

    window.setTimeout(async () => {
      window.removeEventListener("eip6963:announceProvider", onAnnounce);

      // Legacy fallback: a wallet predating EIP-6963 only sets window.ethereum.
      const legacy = (window as { ethereum?: Eip1193Provider & { isMetaMask?: boolean } })
        .ethereum;
      if (found.size === 0 && legacy) {
        found.set("legacy", {
          uuid: "legacy",
          name: legacy.isMetaMask ? "MetaMask" : "Browser wallet",
          icon: null,
          rdns: "legacy",
          provider: legacy,
          hasSnaps: false,
        });
      }

      const list = [...found.values()];
      await Promise.all(
        list.map(async (w) => {
          w.hasSnaps = await probeSnaps(w.provider);
        }),
      );
      list.sort((a, b) => a.name.localeCompare(b.name));
      resolve(list);
    }, 350);
  });

// ---------------------------------------------------------------------------
// Connection steps, run against the chosen provider
// ---------------------------------------------------------------------------

const asString = (value: unknown): string =>
  value instanceof Error
    ? value.message
    : String((value as { message?: string })?.message ?? value);

const requestAccounts = async (provider: Eip1193Provider): Promise<string> => {
  const accounts = (await provider.request({ method: "eth_requestAccounts" })) as string[];
  const first = accounts?.[0];
  if (!first) throw new Error("The wallet returned no account.");
  return first.toLowerCase();
};

/** Add and switch to the configured network, using OUR rpc rather than the SDK's. */
const ensureChain = async (provider: Eip1193Provider): Promise<void> => {
  const wanted = `0x${env.chainId.toString(16)}`;
  const current = (await provider.request({ method: "eth_chainId" })) as string;
  if (current?.toLowerCase() === wanted) return;

  const params = {
    chainId: wanted,
    chainName: env.chainName,
    rpcUrls: [env.rpc],
    nativeCurrency: { name: "GEN", symbol: "GEN", decimals: 18 },
    blockExplorerUrls: [env.explorer],
  };
  try {
    await provider.request({ method: "wallet_addEthereumChain", params: [params] });
  } catch (error) {
    if ((error as { code?: number })?.code === 4001) {
      throw new Error("You declined adding the network.");
    }
    throw new Error(`Could not add ${env.network} to the wallet: ${asString(error)}`);
  }
  try {
    await provider.request({
      method: "wallet_switchEthereumChain",
      params: [{ chainId: wanted }],
    });
  } catch (error) {
    if ((error as { code?: number })?.code === 4001) {
      throw new Error(`You declined switching to ${env.network}.`);
    }
    throw new Error(`Could not switch to ${env.network}: ${asString(error)}`);
  }
};

/**
 * Add the optional GenLayer snap. Best-effort only: signing does not need it,
 * so a wallet without snap support, or a declined prompt, changes nothing.
 */
const tryInstallSnap = async (wallet: DiscoveredWallet): Promise<void> => {
  if (!wallet.hasSnaps) return;
  try {
    const installed = (await wallet.provider.request({
      method: "wallet_getSnaps",
    })) as Record<string, { id: string }>;
    if (Object.values(installed ?? {}).some((snap) => snap.id === SNAP_ID)) return;
    await wallet.provider.request({
      method: "wallet_requestSnaps",
      params: { [SNAP_ID]: {} },
    });
  } catch {
    /* optional convenience; never a blocker */
  }
};

// ---------------------------------------------------------------------------
// Provider
// ---------------------------------------------------------------------------

export const WalletProvider = ({ children }: { children: ReactNode }) => {
  const [wallets, setWallets] = useState<DiscoveredWallet[]>([]);
  const [discovering, setDiscovering] = useState(true);
  const [address, setAddress] = useState<string | null>(null);
  const [client, setClient] = useState<Client | null>(null);
  const [connectedTo, setConnectedTo] = useState<DiscoveredWallet | null>(null);
  const [connecting, setConnecting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [writesReady, setWritesReady] = useState(false);
  const [writeBlocker, setWriteBlocker] = useState<string | null>(null);
  const [pickerOpen, setPickerOpen] = useState(false);
  const attemptedResume = useRef(false);

  const rescan = useCallback(() => {
    setDiscovering(true);
    void discoverWallets().then((found) => {
      setWallets(found);
      setDiscovering(false);
    });
  }, []);

  useEffect(() => {
    let alive = true;
    void discoverWallets().then((found) => {
      if (!alive) return;
      setWallets(found);
      setDiscovering(false);
    });
    return () => {
      alive = false;
    };
  }, []);

  const disconnect = useCallback(() => {
    setClient(null);
    setAddress(null);
    setConnectedTo(null);
    setWritesReady(false);
    setWriteBlocker(null);
    setError(null);
    window.localStorage.removeItem(STORAGE_KEY);
  }, []);

  const connect = useCallback(async (wallet: DiscoveredWallet) => {
    setError(null);
    setConnecting(true);
    setWritesReady(false);
    setWriteBlocker(null);
    try {
      const account = await requestAccounts(wallet.provider);
      await ensureChain(wallet.provider);

      const next = makeClient(account, wallet.provider);
      setClient(next);
      setAddress(account);
      setConnectedTo(wallet);
      window.localStorage.setItem(STORAGE_KEY, wallet.rdns);
      setPickerOpen(false);

      // Nice-to-have for MetaMask, never required to sign.
      await tryInstallSnap(wallet);

      // The real gate: writes need the consensus contract configuration.
      try {
        await preflight(next);
        setWritesReady(true);
      } catch (preflightError) {
        setWriteBlocker(asString(preflightError));
      }
    } catch (err) {
      setError(
        (err as { code?: number })?.code === 4001
          ? `${wallet.name} rejected the connection request.`
          : `Could not connect ${wallet.name}: ${asString(err)}`,
      );
      setClient(null);
      setAddress(null);
      setConnectedTo(null);
    } finally {
      setConnecting(false);
    }
  }, []);

  // Silently resume the wallet used last time, if it is still authorised.
  // eth_accounts never raises a dialog.
  useEffect(() => {
    if (attemptedResume.current || discovering || wallets.length === 0) return;
    attemptedResume.current = true;
    const remembered = window.localStorage.getItem(STORAGE_KEY);
    if (!remembered) return;
    const wallet = wallets.find((w) => w.rdns === remembered);
    if (!wallet) return;
    void (async () => {
      try {
        const accounts = (await wallet.provider.request({
          method: "eth_accounts",
        })) as string[];
        if (accounts?.length) await connect(wallet);
      } catch {
        /* no longer authorised; wait for an explicit click */
      }
    })();
  }, [discovering, wallets, connect]);

  // Follow account and chain changes rather than going stale.
  useEffect(() => {
    const provider = connectedTo?.provider;
    if (!provider?.on) return;
    const onAccountsChanged = (...args: never[]) => {
      const accounts = args[0] as unknown as string[];
      if (!accounts?.length) {
        disconnect();
      } else if (connectedTo) {
        void connect(connectedTo);
      }
    };
    const onChainChanged = () => {
      if (connectedTo) void connect(connectedTo);
    };
    provider.on("accountsChanged", onAccountsChanged);
    provider.on("chainChanged", onChainChanged);
    return () => {
      provider.removeListener?.("accountsChanged", onAccountsChanged);
      provider.removeListener?.("chainChanged", onChainChanged);
    };
  }, [connectedTo, connect, disconnect]);

  const value = useMemo<WalletState>(
    () => ({
      wallets,
      discovering,
      address,
      client,
      connectedTo,
      connecting,
      error,
      writesReady,
      writeBlocker,
      pickerOpen,
      rescan,
      openPicker: () => setPickerOpen(true),
      closePicker: () => setPickerOpen(false),
      connect,
      disconnect,
    }),
    [
      wallets,
      discovering,
      address,
      client,
      connectedTo,
      connecting,
      error,
      writesReady,
      writeBlocker,
      pickerOpen,
      rescan,
      connect,
      disconnect,
    ],
  );

  return <WalletContext.Provider value={value}>{children}</WalletContext.Provider>;
};

export const useWallet = (): WalletState => {
  const ctx = useContext(WalletContext);
  if (!ctx) throw new Error("useWallet must be used inside a WalletProvider");
  return ctx;
};

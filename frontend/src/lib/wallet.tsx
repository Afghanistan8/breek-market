/**
 * Wallet discovery and connection.
 *
 * Breek never asks for, stores or handles a private key. Everything here is an
 * address and an EIP-1193 provider handed over by the wallet itself.
 *
 * Wallets are discovered with **EIP-6963**, which is the reason this file exists
 * in its current shape. The older `window.ethereum` single-slot convention
 * breaks as soon as more than one wallet extension is installed: they race to
 * own the slot, and whoever loses is invisible. Worse for Breek, if a
 * non-MetaMask wallet wins the slot then `wallet_getSnaps` fails and signing is
 * impossible even though MetaMask is sitting right there. Discovering every
 * announced provider and letting the person pick fixes both problems.
 *
 * Signing on GenLayer goes through the **GenLayer MetaMask Snap**. Snaps are a
 * MetaMask feature, so a wallet that cannot install snaps cannot sign a Breek
 * transaction. Such wallets are still listed, clearly marked, rather than
 * hidden — being told why a wallet will not work beats it silently missing.
 *
 * The SDK's own `client.connect()` is deliberately not used: it reads
 * `window.ethereum` directly, which would defeat the picker, and it sources the
 * RPC from the SDK's baked-in chain rather than our configured one. The same
 * steps are performed here against the chosen provider instead.
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

import { makeClient } from "./breek";
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
  /** Whether this wallet can install the GenLayer snap, i.e. can sign here. */
  canSign: boolean | null;
}

/** The GenLayer MetaMask snap that signs Breek transactions. */
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
  /** True only once this wallet is proven able to sign a Breek write. */
  writesReady: boolean;
  /** Why writes are unavailable, when they are. */
  writeBlocker: string | null;
  pickerOpen: boolean;
  /** Re-run discovery, for when a wallet is installed with the page open. */
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

const probeCanSign = async (provider: Eip1193Provider): Promise<boolean> => {
  // wallet_getSnaps exists only on MetaMask-family wallets. A rejection here is
  // the cleanest signal that this wallet cannot host the GenLayer snap.
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
        canSign: null,
      });
    };

    window.addEventListener("eip6963:announceProvider", onAnnounce);
    window.dispatchEvent(new Event("eip6963:requestProvider"));

    // Announcements are synchronous in practice, but give slow extensions a
    // moment before falling back.
    window.setTimeout(async () => {
      window.removeEventListener("eip6963:announceProvider", onAnnounce);

      // Legacy fallback: a wallet that predates EIP-6963 only ever sets
      // window.ethereum and never announces itself.
      const legacy = (window as { ethereum?: Eip1193Provider & { isMetaMask?: boolean } })
        .ethereum;
      if (found.size === 0 && legacy) {
        found.set("legacy", {
          uuid: "legacy",
          name: legacy.isMetaMask ? "MetaMask" : "Browser wallet",
          icon: null,
          rdns: "legacy",
          provider: legacy,
          canSign: null,
        });
      }

      const list = [...found.values()];
      await Promise.all(
        list.map(async (w) => {
          w.canSign = await probeCanSign(w.provider);
        }),
      );
      // Signing-capable wallets first; they are the ones that actually work.
      list.sort((a, b) => Number(b.canSign) - Number(a.canSign) || a.name.localeCompare(b.name));
      resolve(list);
    }, 350);
  });

// ---------------------------------------------------------------------------
// Connection steps, run against the chosen provider
// ---------------------------------------------------------------------------

const asString = (value: unknown): string =>
  value instanceof Error ? value.message : String((value as { message?: string })?.message ?? value);

const requestAccounts = async (provider: Eip1193Provider): Promise<string> => {
  const accounts = (await provider.request({ method: "eth_requestAccounts" })) as string[];
  const first = accounts?.[0];
  if (!first) throw new Error("The wallet returned no account.");
  return first.toLowerCase();
};

/** Add and switch to the configured GenLayer network, using OUR rpc, not the SDK's. */
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
    // 4001 is the user rejecting; anything else is worth reporting verbatim.
    if ((error as { code?: number })?.code === 4001) {
      throw new Error("You declined adding the network.");
    }
    throw new Error(`Could not add ${env.network} to the wallet: ${asString(error)}`);
  }
  await provider.request({
    method: "wallet_switchEthereumChain",
    params: [{ chainId: wanted }],
  });
};

/** Install the GenLayer snap if it is not already present. */
const ensureSnap = async (provider: Eip1193Provider): Promise<void> => {
  const installed = (await provider.request({ method: "wallet_getSnaps" })) as Record<
    string,
    { id: string }
  >;
  if (Object.values(installed ?? {}).some((snap) => snap.id === SNAP_ID)) return;
  await provider.request({ method: "wallet_requestSnaps", params: { [SNAP_ID]: {} } });
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

      // The client can read and hold an address regardless; only signing needs
      // the snap, so a snap failure downgrades rather than aborts.
      const next = makeClient(account, wallet.provider);
      setClient(next);
      setAddress(account);
      setConnectedTo(wallet);
      window.localStorage.setItem(STORAGE_KEY, wallet.rdns);
      setPickerOpen(false);

      if (!wallet.canSign) {
        setWriteBlocker(
          `${wallet.name} cannot install the GenLayer snap, so it cannot sign ` +
            `Breek transactions. Connect MetaMask to create, stake, settle or claim.`,
        );
        return;
      }
      try {
        await ensureSnap(wallet.provider);
        setWritesReady(true);
      } catch (snapError) {
        setWriteBlocker(
          `The GenLayer snap was not installed, so transactions cannot be ` +
            `signed: ${asString(snapError)}`,
        );
      }
    } catch (err) {
      const message = asString(err);
      setError(
        (err as { code?: number })?.code === 4001
          ? `${wallet.name} rejected the connection request.`
          : `Could not connect ${wallet.name}: ${message}`,
      );
      setClient(null);
      setAddress(null);
      setConnectedTo(null);
    } finally {
      setConnecting(false);
    }
  }, []);

  // Reconnect silently to the wallet used last time, if it is still there and
  // already authorised. Never prompts: eth_accounts does not raise a dialog.
  useEffect(() => {
    if (attemptedResume.current || discovering || wallets.length === 0) return;
    attemptedResume.current = true;
    const remembered = window.localStorage.getItem(STORAGE_KEY);
    if (!remembered) return;
    const wallet = wallets.find((w) => w.rdns === remembered);
    if (!wallet) return;
    void (async () => {
      try {
        const accounts = (await wallet.provider.request({ method: "eth_accounts" })) as string[];
        if (accounts?.length) await connect(wallet);
      } catch {
        /* not authorised any more; wait for an explicit click */
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
      } else {
        setAddress(accounts[0].toLowerCase());
        setClient(makeClient(accounts[0].toLowerCase(), provider));
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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [connectedTo]);

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

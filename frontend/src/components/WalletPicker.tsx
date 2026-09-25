import { useEffect, useRef } from "react";

import { env } from "../lib/env";
import {
  METAMASK_INSTALL,
  SNAP_DOCS,
  useWallet,
  type DiscoveredWallet,
} from "../lib/wallet";

/**
 * Wallet chooser.
 *
 * Every wallet the browser announces is listed, and any of them can sign:
 * genlayer-js delegates `eth_sendTransaction` to whichever provider is chosen.
 * The GenLayer MetaMask snap is flagged where available purely as a nicety --
 * it renders GenLayer transactions in more detail -- and is never required.
 */
export const WalletPicker = () => {
  const {
    wallets,
    discovering,
    pickerOpen,
    closePicker,
    connect,
    connecting,
    error,
    connectedTo,
    rescan,
  } = useWallet();
  const panelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!pickerOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") closePicker();
    };
    window.addEventListener("keydown", onKey);
    panelRef.current?.focus();
    return () => window.removeEventListener("keydown", onKey);
  }, [pickerOpen, closePicker]);

  if (!pickerOpen) return null;

  return (
    <div className="modal-scrim" onClick={closePicker} role="presentation">
      <div
        className="modal"
        ref={panelRef}
        tabIndex={-1}
        role="dialog"
        aria-modal="true"
        aria-labelledby="wallet-picker-title"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="spread" style={{ marginBottom: 4 }}>
          <h2 id="wallet-picker-title" style={{ fontSize: 16 }}>
            Choose a wallet
          </h2>
          <div className="row" style={{ gap: 6 }}>
            <button className="btn btn-sm" onClick={rescan} title="Re-scan for wallets">
              Re-scan
            </button>
            <button className="btn btn-sm" onClick={closePicker} aria-label="Close">
              Esc
            </button>
          </div>
        </div>

        <p className="dim" style={{ fontSize: 12, marginTop: 0 }}>
          Any of these can sign on {env.network}. Breek sends a normal
          transaction to the consensus contract, so no special plugin is needed.
        </p>

        {error && (
          <div className="notice notice-bad" style={{ marginBottom: 12 }}>
            {error}
          </div>
        )}

        {discovering && <div className="skeleton" style={{ height: 64, marginBottom: 10 }} />}

        {!discovering && wallets.length === 0 && (
          <div className="stack" style={{ gap: 10 }}>
            <div className="notice notice-warn">
              No wallet extension detected in this browser. Breek works with any
              EIP-1193 wallet &mdash; MetaMask, OKX, Rabby and others.
            </div>
            <a className="btn btn-primary" href={METAMASK_INSTALL} target="_blank" rel="noreferrer">
              Install MetaMask
            </a>
            <a className="btn" href={SNAP_DOCS} target="_blank" rel="noreferrer">
              About the GenLayer wallet snap
            </a>
            <button className="btn" onClick={rescan}>
              Re-scan for wallets
            </button>
          </div>
        )}

        {wallets.length > 0 && (
          <div className="wallet-list">
            {wallets.map((w) => (
              <WalletRow
                key={w.rdns}
                wallet={w}
                busy={connecting}
                connected={connectedTo?.rdns === w.rdns}
                onPick={() => void connect(w)}
              />
            ))}
          </div>
        )}

      </div>
    </div>
  );
};

const WalletRow = ({
  wallet,
  busy,
  connected,
  onPick,
}: {
  wallet: DiscoveredWallet;
  busy: boolean;
  connected: boolean;
  onPick: () => void;
}) => (
  <button className="wallet-row focus-ring" onClick={onPick} disabled={busy}>
    {wallet.icon ? (
      <img src={wallet.icon} alt="" width={26} height={26} />
    ) : (
      <span className="wallet-fallback" aria-hidden="true">
        {wallet.name.slice(0, 1)}
      </span>
    )}
    <span style={{ flex: 1, textAlign: "left" }}>
      <strong style={{ display: "block", fontSize: 13 }}>{wallet.name}</strong>
      <span className="dim" style={{ fontSize: 11 }}>
        {wallet.hasSnaps ? "Supports the optional GenLayer snap" : "Ready to sign"}
      </span>
    </span>
    {connected ? (
      <span className="tag tag-up">connected</span>
    ) : busy ? (
      <span className="dim" style={{ fontSize: 11 }}>
        …
      </span>
    ) : null}
  </button>
);

import { useEffect, useRef } from "react";

import {
  METAMASK_INSTALL,
  SNAP_DOCS,
  useWallet,
  type DiscoveredWallet,
} from "../lib/wallet";

/**
 * Wallet chooser.
 *
 * Every wallet the browser announces is listed, including ones that cannot sign
 * a Breek transaction. Hiding them would be worse: someone with Rabby installed
 * and MetaMask disabled deserves to be told why, not to find an empty list.
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

  const signable = wallets.filter((w) => w.canSign);
  const unsignable = wallets.filter((w) => !w.canSign);

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
          Breek signs through the GenLayer MetaMask snap. Wallets without snap
          support can connect and browse, but cannot sign transactions.
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
              No wallet extension detected in this browser. Breek needs MetaMask
              plus the GenLayer snap to sign transactions.
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

        {signable.length > 0 && (
          <div className="wallet-list">
            {signable.map((w) => (
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

        {unsignable.length > 0 && (
          <>
            <div className="eyebrow" style={{ margin: "16px 0 8px" }}>
              Cannot sign on GenLayer
            </div>
            <div className="wallet-list">
              {unsignable.map((w) => (
                <WalletRow
                  key={w.rdns}
                  wallet={w}
                  busy={connecting}
                  connected={connectedTo?.rdns === w.rdns}
                  onPick={() => void connect(w)}
                />
              ))}
            </div>
            <p className="dim" style={{ fontSize: 11, marginTop: 8 }}>
              These wallets do not support MetaMask Snaps, so they cannot install
              the GenLayer signing plugin.{" "}
              <a href={SNAP_DOCS} target="_blank" rel="noreferrer" style={{ textDecoration: "underline" }}>
                Why?
              </a>
            </p>
          </>
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
        {wallet.canSign ? "Can sign GenLayer transactions" : "No Snaps support"}
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

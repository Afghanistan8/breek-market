import type { ReactNode } from "react";

import { env } from "../lib/env";
import { useWallet } from "../lib/wallet";

/**
 * Tells the truth about whether this browser can sign a Breek transaction.
 *
 * Reads work for everyone, so the app stays browsable. Any EIP-1193 wallet can
 * write; what can stop a write is the network failing to supply its consensus
 * contract configuration. When that happens, report the exact error once at the
 * top of the page and again beside the control, instead of letting someone
 * click into a dead end.
 */
export const WalletBanner = () => {
  const { address, writeBlocker, error } = useWallet();

  if (error && !address) {
    return (
      <div className="notice notice-bad" style={{ marginBottom: 16 }}>
        {error}
      </div>
    );
  }
  if (!address || !writeBlocker) return null;

  return (
    <div className="notice notice-warn" style={{ marginBottom: 16 }}>
      <strong>Connected, but writes are unavailable on {env.network}.</strong>{" "}
      {writeBlocker} Reads still work, so you can browse every market.
    </div>
  );
};

/**
 * Wraps an action so it is only offered when it can actually succeed.
 *
 * Renders the reason in place of the control rather than disabling it silently.
 */
export const WriteGate = ({
  children,
  action,
}: {
  children: ReactNode;
  action: string;
}) => {
  const { address, writesReady, writeBlocker, openPicker, connecting } = useWallet();

  if (!address) {
    return (
      <div className="stack" style={{ gap: 8 }}>
        <button className="btn btn-primary" onClick={openPicker} disabled={connecting}>
          {connecting ? "Connecting…" : `Connect a wallet to ${action}`}
        </button>
      </div>
    );
  }

  if (!writesReady) {
    return (
      <div className="notice notice-warn">
        Cannot {action} right now: {writeBlocker ?? "the network did not return a usable fee/consensus configuration."}
      </div>
    );
  }

  return <>{children}</>;
};

/** True when a write can be attempted right now. */
export const useCanWrite = (): boolean => {
  const { address, writesReady } = useWallet();
  return Boolean(address) && writesReady;
};

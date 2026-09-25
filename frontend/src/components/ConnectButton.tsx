import { shortAddress } from "../lib/format";
import { useWallet } from "../lib/wallet";

export const ConnectButton = () => {
  const { address, connectedTo, openPicker, disconnect, connecting, writesReady } = useWallet();

  if (address) {
    return (
      <button
        className="btn btn-sm mono"
        onClick={disconnect}
        title={`${connectedTo?.name ?? "Wallet"} — ${address}${
          writesReady ? "" : " (cannot sign)"
        }. Click to disconnect.`}
      >
        {!writesReady && (
          <span aria-hidden="true" style={{ color: "var(--breek)" }}>
            !
          </span>
        )}
        {shortAddress(address)}
      </button>
    );
  }

  return (
    <button className="btn btn-primary btn-sm" onClick={openPicker} disabled={connecting}>
      {connecting ? "Connecting…" : "Connect wallet"}
    </button>
  );
};

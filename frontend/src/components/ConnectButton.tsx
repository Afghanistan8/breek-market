import { shortAddress } from "../lib/format";
import { useWallet } from "../lib/wallet";

export const ConnectButton = () => {
  const { address, connect, disconnect, connecting } = useWallet();

  if (address) {
    return (
      <button className="btn btn-sm mono" onClick={disconnect} title="Disconnect">
        {shortAddress(address)}
      </button>
    );
  }

  return (
    <button className="btn btn-primary btn-sm" onClick={() => void connect()} disabled={connecting}>
      {connecting ? "Connecting…" : "Connect wallet"}
    </button>
  );
};

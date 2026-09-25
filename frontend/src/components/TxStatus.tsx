import type { WriteResult } from "../lib/breek";
import { explorerTx } from "../lib/env";
import { errorText } from "../lib/format";

/**
 * One place to render the outcome of a write.
 *
 * ``take_position`` deliberately returns a ``REFUNDED:`` string instead of
 * reverting, so a transaction can succeed and still not be what the user wanted.
 * That case is surfaced as a warning, not a success.
 */
export const TxStatus = ({
  pending,
  error,
  result,
}: {
  pending?: boolean;
  error?: Error | null;
  result?: WriteResult | null;
}) => {
  if (pending) {
    return (
      <div className="notice" style={{ marginTop: 12 }}>
        Waiting for consensus… validators are fetching and voting. This takes a few blocks.
      </div>
    );
  }

  if (error) {
    return (
      <div className="notice notice-bad" style={{ marginTop: 12 }}>
        {errorText(error)}
      </div>
    );
  }

  if (!result) return null;

  if (result.error) {
    return (
      <div className="notice notice-bad" style={{ marginTop: 12 }}>
        {errorText(new Error(result.error))}
        <TxLink hash={result.hash} />
      </div>
    );
  }

  const returned = result.returned ?? "";
  const refunded = returned.startsWith("REFUNDED:");

  return (
    <div
      className={`notice ${refunded ? "notice-warn" : "notice-good"}`}
      style={{ marginTop: 12 }}
    >
      {refunded ? (
        <>
          <strong>Stake refunded in the same transaction.</strong>{" "}
          {REFUND_REASON[returned.slice("REFUNDED:".length)] ?? returned}
        </>
      ) : (
        <>
          <strong>{result.status}</strong>
          {returned ? ` — ${returned}` : ""}
        </>
      )}
      <TxLink hash={result.hash} />
    </div>
  );
};

const TxLink = ({ hash }: { hash: string }) => (
  <div style={{ marginTop: 6 }}>
    <a
      className="mono dim"
      style={{ fontSize: 11, textDecoration: "underline" }}
      href={explorerTx(hash)}
      target="_blank"
      rel="noreferrer"
    >
      {hash}
    </a>
  </div>
);

const REFUND_REASON: Record<string, string> = {
  NO_SUCH_MARKET: "That market does not exist.",
  WINDOW_ALREADY_OPEN: "The window has already opened, so staking is closed.",
  INVALID_SIDE: "That is not a valid side for this market.",
  SIDE_SWITCH_FORBIDDEN: "You already hold the other side. Breek does not allow switching.",
  BELOW_MIN_STAKE: "Your total stake would be under 2 GEN.",
  ABOVE_MAX_STAKE: "Your total stake would be over 4 GEN.",
};

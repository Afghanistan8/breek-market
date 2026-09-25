import type { Evidence as EvidenceData } from "../lib/breek";
import { bpsAsPct, trimPrice } from "../lib/format";
import { fmtGmt1Long } from "../lib/gmt";

/**
 * How the round got its number.
 *
 * Both feeds side by side with the gap between them in the middle. There is no
 * verdict to show here -- the two sources are not voting, they are being asked
 * to converge on a price, and the midpoint is what everyone was graded against.
 */
export const PriceEvidence = ({ evidence }: { evidence: EvidenceData }) => {
  if (!evidence.payload) {
    return <p className="muted">This round has not been priced yet.</p>;
  }

  if (evidence.payload.startsWith("f1|EXPIRED")) {
    return (
      <>
        <div className="note note-warn">
          Nobody scored this round within five days of its window closing. At that
          point the contract stops querying the web entirely and returns every
          entry fee, rather than inventing a price. <strong>No feed was
          contacted.</strong>
        </div>
        <div className="payload">{evidence.payload}</div>
      </>
    );
  }

  const voided = evidence.status !== "SCORED";
  const spread = Number(evidence.spread_bps ?? 0);
  const tolerance = Number(evidence.tolerance_bps ?? 50);

  return (
    <>
      <div className="feeds">
        <div className="feed a">
          <h4>A · {evidence.source_a}</h4>
          <div className="px">{trimPrice(evidence.a_close ?? "")}</div>
          <div className="dim" style={{ fontSize: 11, marginTop: 4 }}>
            last hourly candle close
          </div>
        </div>

        <div className="feed-join">
          <span>gap</span>
          <b style={{ color: voided ? "var(--drift)" : "var(--signal)" }}>
            {spread} bp
          </b>
          <span style={{ textTransform: "none", letterSpacing: 0 }}>
            {voided ? `over ${tolerance} bp` : `within ${tolerance} bp`}
          </span>
        </div>

        <div className="feed b">
          <h4>B · {evidence.source_b}</h4>
          <div className="px">{trimPrice(evidence.b_close ?? "")}</div>
          <div className="dim" style={{ fontSize: 11, marginTop: 4 }}>
            sample at the closing instant
          </div>
        </div>
      </div>

      {voided ? (
        <div className="note note-warn" style={{ marginTop: 12 }}>
          The two feeds were {bpsAsPct(spread)} apart, wider than the{" "}
          {bpsAsPct(tolerance)} tolerance. There is no single honest number to
          grade against, so the round is void and every entry fee is refundable.
        </div>
      ) : (
        <div className="note note-good" style={{ marginTop: 12 }}>
          The feeds converged to within {bpsAsPct(spread)}, so the round was
          graded against their midpoint:{" "}
          <strong className="mono">{trimPrice(evidence.consensus ?? "")}</strong>.
        </div>
      )}

      <p className="dim" style={{ fontSize: 11, marginTop: 14, marginBottom: 4 }}>
        Agreed payload, priced {fmtGmt1Long(Number(evidence.scored_at))}. Every
        validator fetched both feeds independently and produced this exact string.
      </p>
      <div className="payload">{evidence.payload}</div>
    </>
  );
};

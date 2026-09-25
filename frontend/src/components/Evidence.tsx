import type { Evidence as EvidenceData, Market } from "../lib/breek";
import { fmtBps, parseSeries, trimPrice } from "../lib/format";
import { fmtGmt1Long } from "../lib/gmt";

/**
 * The settlement receipt.
 *
 * Both feeds are shown side by side with the verdict each one produced on its
 * own, then how those two combined. The raw agreed payload is printed verbatim
 * underneath so anyone can recompute the result by hand.
 */
export const Evidence = ({ market, evidence }: { market: Market; evidence: EvidenceData }) => {
  const a = parseSeries(evidence.a_series);
  const b = parseSeries(evidence.b_series);
  const relative = market.kind.startsWith("REL");
  const inconclusive = evidence.final === "INCONCLUSIVE";

  if (!evidence.payload) {
    return <p className="muted">No settlement evidence recorded yet.</p>;
  }

  if (evidence.payload.startsWith("v1|TERMINAL_REFUND")) {
    return (
      <>
        <div className="notice notice-warn">
          This market went five days past its window without anyone settling it. At that point
          the contract stops querying the web entirely and refunds every stake, rather than
          inventing a price. <strong>No feed was contacted.</strong>
        </div>
        <div className="payload">{evidence.payload}</div>
      </>
    );
  }

  return (
    <>
      <div className="sources">
        <SourcePanel
          side="a"
          name={evidence.source_a}
          verdict={evidence.a_verdict}
          rows={a}
          relative={relative}
        />
        <SourcePanel
          side="b"
          name={evidence.source_b}
          verdict={evidence.b_verdict}
          rows={b}
          relative={relative}
        />
      </div>

      <div className="verdict-join">
        <span className="mono" style={{ color: "var(--src-a)" }}>
          {evidence.a_verdict}
        </span>
        <span className="dim">{inconclusive ? "does not match" : "matches"}</span>
        <span className="mono" style={{ color: "var(--src-b)" }}>
          {evidence.b_verdict}
        </span>
        <span className="dim">&rarr;</span>
        <strong
          className="mono"
          style={{ color: inconclusive ? "var(--void)" : "var(--up)", fontSize: 15 }}
        >
          {evidence.final}
        </strong>
      </div>

      {inconclusive ? (
        <div className="notice notice-warn" style={{ marginTop: 12 }}>
          The two feeds did not agree, so Breek refuses to pick a winner. Every stake is
          refundable in full from the Portfolio page.
        </div>
      ) : (
        <div className="notice notice-good" style={{ marginTop: 12 }}>
          Both feeds independently produced <strong>{evidence.final}</strong>, so the market
          settled and holders of that side split the pool pro-rata.
        </div>
      )}

      <p className="dim" style={{ fontSize: 12, marginTop: 14, marginBottom: 4 }}>
        Agreed consensus payload, settled {fmtGmt1Long(Number(evidence.settled_at))}. Every
        validator independently fetched both feeds and produced this exact string.
      </p>
      <div className="payload">{evidence.payload}</div>
    </>
  );
};

const SourcePanel = ({
  side,
  name,
  verdict,
  rows,
  relative,
}: {
  side: "a" | "b";
  name: string;
  verdict?: string;
  rows: ReturnType<typeof parseSeries>;
  relative: boolean;
}) => (
  <div className={`source ${side}`}>
    <h4>
      Source {side.toUpperCase()} &middot; {name}
    </h4>
    <table className="data">
      <thead>
        <tr>
          <th>Asset</th>
          <th>Open</th>
          <th>Close</th>
          <th style={{ textAlign: "right" }}>Return</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr key={row.symbol}>
            <td style={{ color: row.symbol === verdict ? "var(--breek)" : undefined }}>
              {row.symbol}
            </td>
            <td>{trimPrice(row.open)}</td>
            <td>{trimPrice(row.close)}</td>
            <td
              style={{
                textAlign: "right",
                color: row.bps >= 0 ? "var(--up)" : "var(--down)",
              }}
            >
              {fmtBps(row.bps)}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
    <div className="spread" style={{ marginTop: 10, fontSize: 12 }}>
      <span className="dim">{relative ? "Strongest return" : "Direction"}</span>
      <strong className="mono">{verdict}</strong>
    </div>
  </div>
);

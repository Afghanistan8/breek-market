import type { Leaderboard as Board } from "../lib/breek";
import { bpsAsPct, fmtGen, shortAddress, trimPrice, weightPct } from "../lib/format";

/**
 * Who called it closest.
 *
 * A number appears here only once its owner has revealed it, which cannot
 * happen while entries are open. Publishing live forecasts would let a late
 * entrant copy the crowd, turning a skill contest into a herding exercise.
 * The concealment is enforced by the contract, not by this component -- the
 * field simply comes back empty.
 */
export const Leaderboard = ({
  board,
  cutoffBps,
  me,
}: {
  board: Board;
  cutoffBps: string;
  me: string | null;
}) => {
  if (board.entries.length === 0) {
    return <p className="muted">Nobody has entered this round yet.</p>;
  }

  const scored = board.status === "SCORED";
  const opened = board.entries.filter((row) => row.revealed).length;

  if (!scored) {
    return (
      <>
        <p className="dim" style={{ fontSize: 12, marginTop: 0 }}>
          {board.entries.length}{" "}
          {board.entries.length === 1 ? "forecast is" : "forecasts are"} in,{" "}
          {opened} revealed so far. A sealed number is a sha256 hash and cannot
          be read by anyone until its owner opens it.
        </p>
        <table className="grid">
          <thead>
            <tr>
              <th>Entrant</th>
              <th>Forecast</th>
              <th style={{ textAlign: "right" }}>Revisions</th>
            </tr>
          </thead>
          <tbody>
            {board.entries.map((row) => (
              <tr key={row.who} className={row.who === me ? "is-me" : undefined}>
                <td>
                  {shortAddress(row.who)}
                  {row.who === me && <span className="chip" style={{ marginLeft: 8 }}>you</span>}
                </td>
                <td>
                  {row.revealed ? (
                    trimPrice(row.forecast)
                  ) : (
                    <span className="dim" title="sha256, salted -- not derivable">
                      sealed
                    </span>
                  )}
                </td>
                <td style={{ textAlign: "right" }}>{row.revisions}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </>
    );
  }

  return (
    <table className="grid">
      <thead>
        <tr>
          <th style={{ width: 34 }}>#</th>
          <th>Entrant</th>
          <th>Called</th>
          <th>Off by</th>
          <th style={{ width: 110 }}>Accuracy</th>
          <th style={{ textAlign: "right" }}>Share</th>
        </tr>
      </thead>
      <tbody>
        {board.entries.map((row, i) => {
          const pct = row.revealed ? weightPct(row.weight, cutoffBps) : 0;
          const zero = !row.revealed || Number(row.weight) === 0;
          return (
            <tr key={row.who} className={row.who === me ? "is-me" : undefined}>
              <td className="dim">{i + 1}</td>
              <td>
                {shortAddress(row.who)}
                {row.who === me && <span className="chip" style={{ marginLeft: 8 }}>you</span>}
              </td>
              <td>
                {row.revealed ? (
                  trimPrice(row.forecast)
                ) : (
                  <span className="dim">never revealed</span>
                )}
              </td>
              <td style={{ color: zero ? "var(--drift)" : undefined }}>
                {row.revealed ? bpsAsPct(row.error_bps) : <span className="dim">—</span>}
              </td>
              <td>
                <div className="acc" title={`weight ${row.weight}`}>
                  <span
                    style={{
                      width: `${pct}%`,
                      background: zero ? "var(--drift)" : "var(--signal)",
                    }}
                  />
                </div>
              </td>
              <td style={{ textAlign: "right" }}>
                {zero ? <span className="dim">—</span> : `${fmtGen(row.share_wei)} GEN`}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
};

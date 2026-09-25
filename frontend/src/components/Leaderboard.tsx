import type { Leaderboard as Board } from "../lib/breek";
import { bpsAsPct, fmtGen, shortAddress, trimPrice, weightPct } from "../lib/format";

/**
 * Who called it closest.
 *
 * Before a round is priced this shows who entered but not what they said --
 * publishing live forecasts would let a late entrant simply copy the crowd,
 * which would turn a skill contest into a herding exercise.
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

  if (!scored) {
    return (
      <>
        <p className="dim" style={{ fontSize: 12, marginTop: 0 }}>
          {board.entries.length}{" "}
          {board.entries.length === 1 ? "forecast is" : "forecasts are"} in.
          Numbers stay sealed until the round is priced, so nobody can copy the
          crowd.
        </p>
        <table className="grid">
          <thead>
            <tr>
              <th>Entrant</th>
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
          const pct = weightPct(row.weight, cutoffBps);
          const zero = Number(row.weight) === 0;
          return (
            <tr key={row.who} className={row.who === me ? "is-me" : undefined}>
              <td className="dim">{i + 1}</td>
              <td>
                {shortAddress(row.who)}
                {row.who === me && <span className="chip" style={{ marginLeft: 8 }}>you</span>}
              </td>
              <td>{trimPrice(row.forecast)}</td>
              <td style={{ color: zero ? "var(--drift)" : undefined }}>
                {bpsAsPct(row.error_bps)}
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

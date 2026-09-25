import { Link } from "react-router-dom";

import type { Round } from "../lib/breek";
import { fmtGen, trimPrice } from "../lib/format";
import { fmtCountdown, fmtGmt1 } from "../lib/gmt";

/** One line on the board. Rounds are a list, not a deck of cards. */
export const RoundRow = ({ round, now }: { round: Round; now: number }) => {
  const locks = Number(round.locks_at);
  const scoreable = Number(round.scoreable_at);

  return (
    <Link to={`/round/${round.round_id}`} className="board-row focus-ring">
      <span className="mono dim">{String(round.round_id).padStart(3, "0")}</span>

      <span>
        <span className="board-asset">{round.asset}</span>{" "}
        <span className="dim mono" style={{ fontSize: 11 }}>
          {round.timeframe === "WEEKLY" ? "7d" : "24h"}
        </span>
        <div className="board-sub">
          {round.timeframe === "WEEKLY" ? "week of " : ""}
          {round.window_id} · closes {fmtGmt1(Number(round.window_end))}
        </div>
      </span>

      <span className="board-hide mono muted">
        {round.status === "SCORED" ? (
          <>
            <span className="dim" style={{ fontSize: 10 }}>
              settled at
            </span>
            <br />
            {trimPrice(round.consensus)}
          </>
        ) : (
          <>
            <span className="dim" style={{ fontSize: 10 }}>
              {round.phase === "ACCEPTING" ? "locks in" : "scoreable in"}
            </span>
            <br />
            {round.phase === "ACCEPTING"
              ? fmtCountdown(locks - now)
              : round.phase === "LOCKED"
                ? fmtCountdown(scoreable - now)
                : "now"}
          </>
        )}
      </span>

      <span className="board-hide mono muted">
        {round.entrants} {round.entrants === "1" ? "entry" : "entries"}
        <div className="board-sub">{fmtGen(round.pot_wei)} GEN pot</div>
      </span>

      <span className="board-hide">
        <StatusChip round={round} />
      </span>

      <span className="board-compact" style={{ textAlign: "right" }}>
        <StatusChip round={round} compact />
      </span>
    </Link>
  );
};

export const StatusChip = ({ round, compact }: { round: Round; compact?: boolean }) => {
  switch (round.phase) {
    case "ACCEPTING":
      return <span className="chip chip-live">open</span>;
    case "LOCKED":
      return <span className="chip">locked</span>;
    case "AWAITING_SCORE":
      return <span className="chip chip-warn">score me</span>;
    case "SCORED":
      return <span className="chip chip-live">{compact ? "done" : "scored"}</span>;
    case "VOID":
      return <span className="chip chip-void">void</span>;
    default:
      return <span className="chip">{round.phase}</span>;
  }
};

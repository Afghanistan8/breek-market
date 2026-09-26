import { Link } from "react-router-dom";

import type { Round } from "../lib/breek";
import { fmtGen, trimPrice } from "../lib/format";
import { fmtCountdown, fmtGmt1 } from "../lib/gmt";
import { fmtChange, fmtPrice, type SpotPrice } from "../lib/prices";

/** One line on the board. Rounds are a list, not a deck of cards. */
export const RoundRow = ({
  round,
  now,
  price,
}: {
  round: Round;
  now: number;
  /** Where the asset is trading right now. Display only -- see lib/prices.ts. */
  price?: SpotPrice;
}) => {
  const locks = Number(round.locks_at);
  const scoreable = Number(round.scoreable_at);
  const up = (price?.change24h ?? 0) >= 0;

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

      {/* Spot price, so the list can be read for context and not just state. */}
      <span className="board-hide mono">
        {price ? (
          <>
            <span className="board-spot">{fmtPrice(price.usd)}</span>
            {price.change24h !== null && (
              <div
                className="board-sub mono"
                style={{ color: up ? "var(--signal)" : "var(--drift)" }}
              >
                {fmtChange(price.change24h)} 24h
              </div>
            )}
          </>
        ) : (
          <span className="dim">—</span>
        )}
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
              : round.phase === "REVEALING"
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
        {/* On a narrow screen the price rides along with the status chip, since
            it is the one column worth keeping when the rest collapses. */}
        {price && (
          <div className="board-sub mono" style={{ marginBottom: 4 }}>
            {fmtPrice(price.usd)}
          </div>
        )}
        <StatusChip round={round} compact />
      </span>
    </Link>
  );
};

export const StatusChip = ({ round, compact }: { round: Round; compact?: boolean }) => {
  switch (round.phase) {
    case "ACCEPTING":
      return <span className="chip chip-live">open</span>;
    case "REVEALING":
      return <span className="chip chip-warn">reveal now</span>;
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

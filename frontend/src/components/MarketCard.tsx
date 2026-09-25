import { Link } from "react-router-dom";

import type { Market } from "../lib/breek";
import { KIND_SHORT, fmtGen, marketTitle, sharePct } from "../lib/format";
import { fmtCountdown, fmtGmt1 } from "../lib/gmt";
import { PhaseTag } from "./PhaseTag";

const SIDE_COLOR: Record<string, string> = {
  UP: "var(--up)",
  DOWN: "var(--down)",
  SOL: "var(--src-a)",
  ETH: "var(--src-b)",
  NEAR: "var(--breek)",
};

const colorFor = (side: string, index: number): string =>
  SIDE_COLOR[side] ?? ["var(--src-a)", "var(--src-b)", "var(--breek)"][index % 3];

export const MarketCard = ({ market, now }: { market: Market; now: number }) => {
  const pool = market.pool_wei;
  const cutoff = Number(market.cutoff_at);
  const settles = Number(market.settles_at);

  const timing =
    market.phase === "OPEN"
      ? `Staking closes in ${fmtCountdown(cutoff - now)}`
      : market.phase === "WINDOW_LIVE"
        ? `Window closes in ${fmtCountdown(settles - now)}`
        : market.phase === "READY_TO_SETTLE"
          ? "Anyone can settle this now"
          : `Settled ${fmtGmt1(Number(market.settled_at))}`;

  return (
    <Link to={`/market/${market.market_id}`} className="market-card focus-ring">
      <div className="spread">
        <span className="tag">{KIND_SHORT[market.kind] ?? market.kind}</span>
        <PhaseTag market={market} />
      </div>

      <div>
        <h3>{marketTitle(market)}</h3>
        <div className="muted" style={{ fontSize: 12, marginTop: 3 }}>
          {market.timeframe === "WEEKLY" ? "Week of " : ""}
          {market.window_id} &middot; {fmtGmt1(Number(market.window_start))}
        </div>
      </div>

      <div className="bar" aria-hidden="true">
        {market.valid_sides.map((side, index) => {
          const pct = sharePct(market.sides[side] ?? "0", pool);
          return (
            <span
              key={side}
              style={{ width: `${pct}%`, background: colorFor(side, index) }}
            />
          );
        })}
      </div>

      <div className="side-list">
        {market.valid_sides.map((side, index) => (
          <div className="side-line" key={side}>
            <span style={{ color: colorFor(side, index), fontWeight: 600 }}>{side}</span>
            <span className="mono muted">{fmtGen(market.sides[side] ?? "0")} GEN</span>
            <span className="mono dim" style={{ minWidth: 44, textAlign: "right" }}>
              {sharePct(market.sides[side] ?? "0", pool).toFixed(0)}%
            </span>
          </div>
        ))}
      </div>

      <div className="spread" style={{ fontSize: 12 }}>
        <span className="dim">{timing}</span>
        <span className="mono muted">
          {fmtGen(pool)} GEN &middot; {market.stakers}{" "}
          {market.stakers === "1" ? "staker" : "stakers"}
        </span>
      </div>
    </Link>
  );
};

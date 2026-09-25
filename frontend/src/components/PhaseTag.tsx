import type { Market } from "../lib/breek";

/** One glance at where a market is in its life. */
export const PhaseTag = ({ market }: { market: Market }) => {
  switch (market.phase) {
    case "OPEN":
      return <span className="tag tag-live">Open</span>;
    case "WINDOW_LIVE":
      return <span className="tag">Window running</span>;
    case "READY_TO_SETTLE":
      return <span className="tag tag-live">Ready to settle</span>;
    case "SETTLED_UP":
      return <span className="tag tag-up">UP</span>;
    case "SETTLED_DOWN":
      return <span className="tag tag-down">DOWN</span>;
    case "SETTLED_WINNER":
      return <span className="tag tag-up">{market.outcome}</span>;
    case "INCONCLUSIVE":
      return <span className="tag tag-void">Inconclusive</span>;
    default:
      return <span className="tag">{market.phase}</span>;
  }
};

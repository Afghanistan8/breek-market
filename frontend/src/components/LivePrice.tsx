import { useFeedPair } from "../hooks";
import { fmtChange, fmtPrice } from "../lib/prices";

/**
 * What the asset is doing right now, from the same two feeds that will settle
 * the round.
 *
 * This is reference material for whoever is deciding what to type, and nothing
 * more. It is fetched in the browser, unverified, and never handed to the
 * contract — the contract fetches its own prices inside consensus, which is the
 * entire point of the design.
 *
 * Showing both feeds rather than one number is deliberate. It previews exactly
 * what scoring will do: when they sit close the round will price cleanly, and
 * when they drift past the tolerance it is a live warning that the round could
 * void and refund everyone.
 */
export const LivePrice = ({
  symbol,
  toleranceBps,
  onUse,
}: {
  symbol: string;
  toleranceBps: number;
  onUse?: (price: string) => void;
}) => {
  const feeds = useFeedPair(symbol);

  if (feeds.isLoading) {
    return <div className="skeleton" style={{ height: 96 }} />;
  }

  const gate = feeds.data?.gate ?? null;
  const coingecko = feeds.data?.coingecko ?? null;
  // Prefer the midpoint, but a single surviving feed is still worth far more
  // than nothing -- rate limits hit one endpoint at a time.
  const headline = feeds.data?.mid ?? gate ?? coingecko;

  // A failed refresh is not the same as having nothing: TanStack keeps the last
  // good payload, and a slightly stale price still beats an empty box. Only
  // give up when there is genuinely no number to show.
  if (headline === null) {
    // A dead price feed is an inconvenience, never a blocker: the round works
    // regardless, so say so quietly and move on.
    return (
      <div className="note" style={{ fontSize: 12 }}>
        Live price unavailable right now. It is only a reference — you can still
        enter a forecast, and scoring is unaffected because the contract fetches
        its own prices.
      </div>
    );
  }

  const gapBps = feeds.data?.gapBps ?? null;
  const change24h = feeds.data?.change24h ?? null;
  const stale = feeds.isError;
  const onlyOne = gate === null || coingecko === null;
  const wide = gapBps !== null && gapBps > toleranceBps;
  const up = (change24h ?? 0) >= 0;

  return (
    <div className="livebox">
      <div className="livebox-main">
        <div>
          <span className="livebox-label">{symbol} right now</span>
          <div className="livebox-price mono">{fmtPrice(headline)}</div>
          {change24h !== null && (
            <span
              className="mono"
              style={{ fontSize: 11.5, color: up ? "var(--signal)" : "var(--drift)" }}
            >
              {fmtChange(change24h)} 24h
            </span>
          )}
        </div>
        {onUse && (
          <button
            className="btn btn-sm"
            onClick={() => onUse(fmtPrice(headline))}
            title="Copy this into the forecast box. You can edit it afterwards."
          >
            Use as starting point
          </button>
        )}
      </div>

      <div className="livebox-feeds">
        <span>
          <em style={{ color: "var(--feed-a)" }}>A</em> gate.io
          <b className="mono">{fmtPrice(gate)}</b>
        </span>
        <span>
          <em style={{ color: "var(--feed-b)" }}>B</em> coingecko
          <b className="mono">{fmtPrice(coingecko)}</b>
        </span>
        <span>
          <em className="dim">gap</em>
          <b className="mono" style={{ color: wide ? "var(--drift)" : "var(--signal)" }}>
            {gapBps === null ? "—" : `${gapBps} bp`}
          </b>
        </span>
      </div>

      {onlyOne && (
        <div className="note" style={{ marginTop: 8, fontSize: 11.5 }}>
          Only one of the two feeds is responding, so there is no gap to show.
          This says nothing about the round &mdash; the contract fetches both
          itself when the window closes.
        </div>
      )}

      {wide && (
        <div className="note note-warn" style={{ marginTop: 8, fontSize: 11.5 }}>
          The feeds are currently further apart than the {toleranceBps} bp
          tolerance. If they are still this far apart when the window closes, the
          round voids and every entry fee is refunded.
        </div>
      )}

      {stale && (
        <div className="note" style={{ marginTop: 8, fontSize: 11.5 }}>
          The last refresh failed, so this is the most recent price that came
          through rather than the current one.
        </div>
      )}

      <p className="dim" style={{ fontSize: 10.5, margin: "8px 0 0" }}>
        Reference only, fetched by your browser. The contract fetches its own
        prices at the window boundary — this number is not an input to scoring.
      </p>
    </div>
  );
};

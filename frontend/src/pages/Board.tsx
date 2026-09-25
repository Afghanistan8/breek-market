import { useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { RoundRow } from "../components/RoundRow";
import { useCatalog, useCatalogPrices, useNow, useRounds, useStats } from "../hooks";
import { bpsAsPct, fmtGen } from "../lib/format";

type Filter = "open" | "scoreable" | "scored" | "all";

const FILTERS: { key: Filter; label: string }[] = [
  { key: "open", label: "Accepting" },
  { key: "scoreable", label: "Awaiting score" },
  { key: "scored", label: "Scored" },
  { key: "all", label: "All" },
];

const PAGE = 50;

export default function Board() {
  const now = useNow();
  const [filter, setFilter] = useState<Filter>("all");
  const [offset, setOffset] = useState(0);
  const rounds = useRounds(offset, PAGE);
  const stats = useStats();
  const catalog = useCatalog();

  const all = rounds.data?.rounds ?? [];
  const total = Number(rounds.data?.total ?? 0);

  const shown = useMemo(() => {
    switch (filter) {
      case "open":
        return all.filter((r) => r.phase === "ACCEPTING");
      case "scoreable":
        return all.filter((r) => r.phase === "AWAITING_SCORE");
      case "scored":
        return all.filter((r) => r.phase === "SCORED" || r.phase === "VOID");
      default:
        return all;
    }
  }, [all, filter]);

  // One request covers the whole board: the distinct assets on screen, not one
  // lookup per row. Display only -- nothing here reaches the contract.
  const symbols = useMemo(
    () => Array.from(new Set(shown.map((r) => r.asset))),
    [shown],
  );
  const prices = useCatalogPrices(symbols);

  const fee = catalog.data ? fmtGen(catalog.data.entry_fee_wei) : "1";
  const cutoff = catalog.data ? bpsAsPct(catalog.data.score_cutoff_bps, 0) : "10%";
  const tolerance = catalog.data ? bpsAsPct(catalog.data.tolerance_bps) : "0.50%";

  return (
    <div>
      <header className="masthead">
        <h1>Name the number. Get graded on how close you were.</h1>
        <p>
          Each round asks what one asset will be worth at the end of a GMT+1
          window. You pay a flat {fee} GEN, submit a price, and revise it free
          until the window opens. When it closes, the contract fetches two
          independent feeds itself and grades everyone against the price they
          agree on. There is no side to pick and no pool to win &mdash; the pot is
          divided in proportion to accuracy, and anything more than {cutoff} off
          scores nothing.
        </p>

        {stats.data && (
          <div className="ticker">
            <div>
              <b>{stats.data.rounds}</b>
              <span>rounds</span>
            </div>
            <div>
              <b style={{ color: "var(--signal)" }}>{stats.data.scored}</b>
              <span>priced &amp; graded</span>
            </div>
            <div>
              <b>{stats.data.entries}</b>
              <span>forecasts made</span>
            </div>
            <div>
              <b>{fmtGen(stats.data.total_paid_wei)}</b>
              <span>GEN paid out</span>
            </div>
            <div>
              <b className="mono" style={{ fontSize: 14 }}>
                {tolerance}
              </b>
              <span>feed tolerance</span>
            </div>
          </div>
        )}
      </header>

      <div className="spread wrap" style={{ marginBottom: 12 }}>
        <div className="row" style={{ gap: 14 }}>
          {FILTERS.map((f) => (
            <button
              key={f.key}
              className="btn btn-sm"
              aria-pressed={filter === f.key}
              style={
                filter === f.key
                  ? { borderColor: "var(--signal-dim)", color: "var(--signal)" }
                  : undefined
              }
              onClick={() => setFilter(f.key)}
            >
              {f.label}
            </button>
          ))}
        </div>
        <span className="dim mono" style={{ fontSize: 11 }}>
          {total} total
        </span>
      </div>

      {rounds.isLoading && <div className="skeleton" style={{ height: 220 }} />}

      {rounds.isError && (
        <div className="note note-bad">
          Could not read rounds from the contract: {(rounds.error as Error).message}
        </div>
      )}

      {rounds.isSuccess && shown.length === 0 && (
        <div className="panel panel-pad muted">
          Nothing here.{" "}
          <Link to="/open" style={{ color: "var(--signal)" }}>
            Open the first round
          </Link>{" "}
          &mdash; no permission needed.
        </div>
      )}

      {shown.length > 0 && (
        <div className="board">
          <div className="board-head">
            <span>#</span>
            <span>Asset / window</span>
            <span>Live now</span>
            <span>Timing</span>
            <span>Field</span>
            <span>State</span>
            <span />
          </div>
          {shown.map((r) => (
            <RoundRow
              key={r.round_id}
              round={r}
              now={now}
              price={prices.data?.[r.asset]}
            />
          ))}
        </div>
      )}

      {total > PAGE && (
        <div className="row" style={{ marginTop: 14, gap: 8 }}>
          <button
            className="btn btn-sm"
            disabled={offset === 0}
            onClick={() => setOffset(Math.max(0, offset - PAGE))}
          >
            Newer
          </button>
          <span className="dim mono" style={{ fontSize: 11 }}>
            {offset + 1}&ndash;{Math.min(offset + PAGE, total)} of {total}
          </span>
          <button
            className="btn btn-sm"
            disabled={offset + PAGE >= total}
            onClick={() => setOffset(offset + PAGE)}
          >
            Older
          </button>
        </div>
      )}
    </div>
  );
}

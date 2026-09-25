import { useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { MarketCard } from "../components/MarketCard";
import { useMarkets, useNow, useStats } from "../hooks";
import { fmtGen } from "../lib/format";

type Filter = "live" | "open" | "settling" | "settled" | "all";

const FILTERS: { key: Filter; label: string }[] = [
  { key: "live", label: "Live" },
  { key: "open", label: "Open" },
  { key: "settling", label: "Ready to settle" },
  { key: "settled", label: "Settled" },
  { key: "all", label: "All" },
];

export default function Home() {
  const now = useNow();
  const [filter, setFilter] = useState<Filter>("live");
  const markets = useMarkets(0, 50);
  const stats = useStats();

  const rows = markets.data?.markets ?? [];

  const shown = useMemo(() => {
    switch (filter) {
      case "open":
        return rows.filter((m) => m.phase === "OPEN");
      case "settling":
        return rows.filter((m) => m.phase === "READY_TO_SETTLE");
      case "settled":
        return rows.filter((m) => m.settled);
      case "live":
        return rows.filter((m) => !m.settled);
      default:
        return rows;
    }
  }, [rows, filter]);

  return (
    <div className="stack" style={{ gap: 22 }}>
      <section className="hero">
        <h1>Prediction markets that settle themselves.</h1>
        <p>
          Stake GEN on whether a listed asset&rsquo;s GMT+1 candle closes up or down, or on which
          asset in a category posts the strongest return. When the window closes,{" "}
          <strong>anyone</strong> can settle the market &mdash; and the contract goes and fetches
          the prices itself, from two independent public feeds, inside GenLayer&rsquo;s
          equivalence-principle consensus.
        </p>

        <div className="rule-strip">
          <div className="rule">
            <b style={{ color: "var(--up)" }}>Both feeds agree</b>
            <span>The market settles and winners split the pool pro-rata.</span>
          </div>
          <div className="rule">
            <b style={{ color: "var(--void)" }}>They disagree</b>
            <span>Inconclusive. Every stake is refunded in full.</span>
          </div>
          <div className="rule">
            <b style={{ color: "var(--breek)" }}>No admin, ever</b>
            <span>
              <code style={{ fontSize: 11 }}>resolve_market(id)</code> takes an id and nothing
              else.
            </span>
          </div>
          <div className="rule">
            <b>Stake 2&ndash;4 GEN</b>
            <span>Per wallet, per market. Top up your side; never switch it.</span>
          </div>
        </div>
      </section>

      {stats.data && (
        <section className="card card-pad">
          <div className="stat-row">
            <div className="stat">
              <b>{stats.data.markets}</b>
              <span className="dim" style={{ fontSize: 12 }}>
                markets created
              </span>
            </div>
            <div className="stat">
              <b style={{ color: "var(--up)" }}>{stats.data.settled}</b>
              <span className="dim" style={{ fontSize: 12 }}>
                settled on two feeds
              </span>
            </div>
            <div className="stat">
              <b style={{ color: "var(--void)" }}>{stats.data.inconclusive}</b>
              <span className="dim" style={{ fontSize: 12 }}>
                inconclusive &rarr; refunded
              </span>
            </div>
            <div className="stat">
              <b>{fmtGen(stats.data.total_staked_wei)}</b>
              <span className="dim" style={{ fontSize: 12 }}>
                GEN staked all-time
              </span>
            </div>
          </div>
        </section>
      )}

      <section>
        <div className="spread wrap" style={{ marginBottom: 12 }}>
          <h2 style={{ fontSize: 17 }}>Markets</h2>
          <div className="row wrap" style={{ gap: 6 }}>
            {FILTERS.map((f) => (
              <button
                key={f.key}
                className="btn btn-sm"
                aria-pressed={filter === f.key}
                style={
                  filter === f.key
                    ? { borderColor: "var(--breek)", color: "var(--breek)" }
                    : undefined
                }
                onClick={() => setFilter(f.key)}
              >
                {f.label}
              </button>
            ))}
          </div>
        </div>

        {markets.isLoading && (
          <div className="market-grid">
            {[0, 1, 2].map((i) => (
              <div key={i} className="skeleton" style={{ height: 196 }} />
            ))}
          </div>
        )}

        {markets.isError && (
          <div className="notice notice-bad">
            Could not read markets from the contract: {(markets.error as Error).message}
          </div>
        )}

        {markets.isSuccess && shown.length === 0 && (
          <div className="card card-pad muted">
            Nothing here yet.{" "}
            <Link to="/create" style={{ color: "var(--breek)" }}>
              Create the first market
            </Link>{" "}
            &mdash; no permission needed.
          </div>
        )}

        <div className="market-grid">
          {shown.map((m) => (
            <MarketCard key={m.market_id} market={m} now={now} />
          ))}
        </div>
      </section>
    </div>
  );
}

import { Link } from "react-router-dom";

import { StatusChip } from "../components/RoundRow";
import { TxStatus } from "../components/TxStatus";
import { useCanWrite } from "../components/WriteGate";
import { useCollect, useMyEntries, useNow } from "../hooks";
import { OUTCOME_LABEL, bpsAsPct, fmtGen, shortAddress, trimPrice } from "../lib/format";
import { fmtCountdown } from "../lib/gmt";
import { useWallet } from "../lib/wallet";

export default function MyForecasts() {
  const { address, openPicker, writeBlocker } = useWallet();
  const canWrite = useCanWrite();
  const mine = useMyEntries();
  const collectIt = useCollect();
  const now = useNow();

  if (!address) {
    return (
      <div className="panel panel-pad stack" style={{ maxWidth: 480 }}>
        <h1 style={{ fontSize: 19 }}>Your forecasts</h1>
        <p className="muted" style={{ margin: 0 }}>
          Connect a wallet to see your calls, your accuracy and anything you can
          collect.
        </p>
        <button className="btn btn-primary" onClick={openPicker}>
          Connect wallet
        </button>
      </div>
    );
  }

  const rows = mine.data?.entries ?? [];
  const collectable = rows.reduce(
    (sum, r) => (r.entry.collected ? sum : sum + BigInt(r.entry.collectable_wei || "0")),
    0n,
  );
  // Rounds where entries have closed, this wallet is in, and the commitment is
  // still sealed. Missing the window forfeits the fee, so this is the single
  // most urgent thing this page can tell someone -- it goes above everything.
  const awaitingReveal = rows.filter(
    (r) => r.round.phase === "REVEALING" && r.entry.entered && !r.entry.revealed,
  );

  const graded = rows.filter((r) => r.entry.error_bps !== "");
  const bestError = graded.length
    ? Math.min(...graded.map((r) => Number(r.entry.error_bps)))
    : null;

  return (
    <div className="stack" style={{ gap: 18 }}>
      <header className="masthead" style={{ marginBottom: 0 }}>
        <div className="spread wrap">
          <div>
            <h1 style={{ fontSize: 22 }}>Your forecasts</h1>
            <p className="mono dim" style={{ margin: 0, fontSize: 12 }}>
              {shortAddress(address)}
            </p>
          </div>
        </div>
        <div className="ticker">
          <div>
            <b>{rows.length}</b>
            <span>rounds entered</span>
          </div>
          <div>
            <b style={{ color: "var(--signal)" }}>
              {bestError === null ? "—" : bpsAsPct(bestError)}
            </b>
            <span>best call</span>
          </div>
          <div>
            <b style={{ color: collectable > 0n ? "var(--signal)" : undefined }}>
              {fmtGen(collectable)}
            </b>
            <span>GEN to collect</span>
          </div>
        </div>
      </header>

      {awaitingReveal.length > 0 && (
        <div className="note note-warn">
          <strong>
            {awaitingReveal.length === 1
              ? "One forecast still needs revealing."
              : `${awaitingReveal.length} forecasts still need revealing.`}
          </strong>{" "}
          A sealed entry that is never opened scores nothing and its fee stays
          in the pot for the entrants who did reveal.
          <ul style={{ margin: "8px 0 0", paddingLeft: 18 }}>
            {awaitingReveal.map(({ round }) => (
              <li key={round.round_id} style={{ marginBottom: 4 }}>
                <Link to={`/round/${round.round_id}`} style={{ color: "var(--signal)" }}>
                  Round {String(round.round_id).padStart(3, "0")} · {round.asset}
                </Link>{" "}
                <span className="dim">
                  closes in {fmtCountdown(Number(round.scoreable_at) - now)}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {mine.isLoading && <div className="skeleton" style={{ height: 140 }} />}

      {mine.isSuccess && rows.length === 0 && (
        <div className="panel panel-pad muted">
          No forecasts yet.{" "}
          <Link to="/" style={{ color: "var(--signal)" }}>
            Find a round
          </Link>
          .
        </div>
      )}

      {rows.length > 0 && (
        <section className="panel" style={{ overflowX: "auto" }}>
          <table className="grid" style={{ minWidth: 680 }}>
            <thead>
              <tr>
                <th>#</th>
                <th>Round</th>
                <th>State</th>
                <th>You called</th>
                <th>Settled at</th>
                <th>Off by</th>
                <th style={{ textAlign: "right" }}>Collect</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {rows.map(({ round, entry }) => {
                const can = !entry.collected && BigInt(entry.collectable_wei || "0") > 0n;
                const zero = entry.weight === "0";
                return (
                  <tr key={round.round_id}>
                    <td className="dim">{round.round_id}</td>
                    <td style={{ fontFamily: "var(--sans)" }}>
                      <Link to={`/round/${round.round_id}`} style={{ color: "var(--signal)" }}>
                        {round.asset} · {round.window_id}
                      </Link>
                      <div className="dim" style={{ fontSize: 10.5 }}>
                        {entry.outcome ? OUTCOME_LABEL[entry.outcome] ?? entry.outcome : ""}
                      </div>
                    </td>
                    <td>
                      <StatusChip round={round} />
                    </td>
                    <td>
                      {entry.revealed ? (
                        trimPrice(entry.forecast)
                      ) : entry.entered ? (
                        <span className="dim">sealed</span>
                      ) : (
                        <span className="dim">—</span>
                      )}
                    </td>
                    <td>{round.consensus ? trimPrice(round.consensus) : <span className="dim">—</span>}</td>
                    <td style={{ color: zero ? "var(--drift)" : undefined }}>
                      {entry.error_bps ? bpsAsPct(entry.error_bps) : <span className="dim">—</span>}
                    </td>
                    <td style={{ textAlign: "right" }}>
                      {can ? `${fmtGen(entry.collectable_wei)} GEN` : <span className="dim">—</span>}
                    </td>
                    <td style={{ textAlign: "right" }}>
                      {can && (
                        <button
                          className="btn btn-sm btn-primary"
                          disabled={!canWrite || collectIt.isPending}
                          onClick={() => collectIt.mutate(Number(round.round_id))}
                        >
                          Collect
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </section>
      )}

      {address && !canWrite && rows.length > 0 && (
        <div className="note note-warn">
          This wallet cannot sign right now, so collecting is unavailable.{" "}
          {writeBlocker ?? ""}
        </div>
      )}

      <TxStatus pending={collectIt.isPending} error={collectIt.error} result={collectIt.data} />
    </div>
  );
}

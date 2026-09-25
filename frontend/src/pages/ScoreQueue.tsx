import { Link } from "react-router-dom";

import { TxStatus } from "../components/TxStatus";
import { useCanWrite } from "../components/WriteGate";
import { useNow, useScoreRound, useScoreable } from "../hooks";
import { fmtGen } from "../lib/format";
import { fmtCountdown, fmtGmt1 } from "../lib/gmt";
import { useWallet } from "../lib/wallet";

export default function ScoreQueue() {
  const { address, openPicker, writeBlocker } = useWallet();
  const canWrite = useCanWrite();
  const now = useNow();
  const queue = useScoreable();
  const scoreIt = useScoreRound();

  const rows = queue.data?.rounds ?? [];

  return (
    <div className="stack" style={{ gap: 18 }}>
      <header className="masthead" style={{ marginBottom: 0 }}>
        <h1 style={{ fontSize: 22 }}>Score queue</h1>
        <p>
          Rounds whose GMT+1 window has closed but which nobody has priced yet.
          Anyone can clear these &mdash; you supply nothing but the round id, and
          the contract fetches both feeds itself inside consensus.
        </p>
      </header>

      <div className="note">
        A scoring attempt can fail with <code>TRANSIENT</code> if a feed is
        briefly unavailable. Nothing is recorded and the round stays in this
        queue for the next attempt. If nobody scores it within five days of the
        window closing, every entry fee is refunded and the contract stops
        querying the web entirely.
      </div>

      {queue.isLoading && <div className="skeleton" style={{ height: 120 }} />}

      {queue.isSuccess && rows.length === 0 && (
        <div className="panel panel-pad muted">
          Queue is empty. Every closed window has been priced.
        </div>
      )}

      {rows.length > 0 && (
        <section className="panel" style={{ overflowX: "auto" }}>
          <table className="grid" style={{ minWidth: 640 }}>
            <thead>
              <tr>
                <th>#</th>
                <th>Round</th>
                <th>Window closed</th>
                <th>Field</th>
                <th>Refunds in</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.round_id}>
                  <td className="dim">{r.round_id}</td>
                  <td style={{ fontFamily: "var(--sans)" }}>
                    <Link to={`/round/${r.round_id}`} style={{ color: "var(--signal)" }}>
                      {r.asset} · {r.window_id}
                    </Link>
                  </td>
                  <td className="muted">{fmtGmt1(Number(r.scoreable_at))}</td>
                  <td>
                    {r.entrants} · {fmtGen(r.pot_wei)} GEN
                  </td>
                  <td className="muted">{fmtCountdown(Number(r.expires_at) - now)}</td>
                  <td style={{ textAlign: "right" }}>
                    <button
                      className="btn btn-sm btn-primary"
                      disabled={!canWrite || scoreIt.isPending}
                      onClick={() => scoreIt.mutate(Number(r.round_id))}
                    >
                      Price it
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      <TxStatus pending={scoreIt.isPending} error={scoreIt.error} result={scoreIt.data} />

      {!address && rows.length > 0 && (
        <div className="note note-warn">
          <button className="btn btn-sm btn-primary" onClick={openPicker}>
            Connect a wallet
          </button>{" "}
          to price a round.
        </div>
      )}

      {address && !canWrite && rows.length > 0 && (
        <div className="note note-warn">
          This wallet cannot sign right now. {writeBlocker ?? ""}
        </div>
      )}
    </div>
  );
}

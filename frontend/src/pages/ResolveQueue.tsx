import { Link } from "react-router-dom";

import { PhaseTag } from "../components/PhaseTag";
import { TxStatus } from "../components/TxStatus";
import { useNow, useResolvable, useResolveMarket } from "../hooks";
import { KIND_SHORT, fmtGen, marketTitle } from "../lib/format";
import { fmtCountdown, fmtGmt1 } from "../lib/gmt";
import { useWallet } from "../lib/wallet";

export default function ResolveQueue() {
  const { address } = useWallet();
  const now = useNow();
  const queue = useResolvable();
  const resolve = useResolveMarket();

  const rows = queue.data?.markets ?? [];

  return (
    <div className="stack" style={{ gap: 18 }}>
      <div>
        <h1 style={{ fontSize: 22 }}>Resolve queue</h1>
        <p className="muted" style={{ maxWidth: "66ch" }}>
          Every market whose GMT+1 window has closed but which nobody has settled yet. Anyone can
          clear these &mdash; settling is permissionless and you supply nothing but the market id.
          The contract fetches both feeds itself inside consensus.
        </p>
      </div>

      <div className="notice">
        A settle can fail with <code>TRANSIENT</code> if a feed is briefly unavailable. That is
        not a dead end: nothing is recorded and the market stays in this queue for the next
        attempt. If no one settles within five days of the window closing, the market pays
        everyone back in full and stops querying the web altogether.
      </div>

      {queue.isLoading && <div className="skeleton" style={{ height: 120 }} />}

      {queue.isSuccess && rows.length === 0 && (
        <div className="card card-pad muted">
          Queue is empty. Every closed window has been settled.
        </div>
      )}

      {rows.length > 0 && (
        <section className="card" style={{ overflowX: "auto" }}>
          <table className="data" style={{ minWidth: 640 }}>
            <thead>
              <tr>
                <th>#</th>
                <th>Kind</th>
                <th>Market</th>
                <th>Window closed</th>
                <th>Pool</th>
                <th>Refund-all in</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {rows.map((m) => (
                <tr key={m.market_id}>
                  <td>{m.market_id}</td>
                  <td>
                    <span className="tag">{KIND_SHORT[m.kind] ?? m.kind}</span>
                  </td>
                  <td style={{ fontFamily: "var(--sans)" }}>
                    <Link to={`/market/${m.market_id}`} style={{ color: "var(--breek)" }}>
                      {marketTitle(m)}
                    </Link>
                    <div className="dim" style={{ fontSize: 11 }}>
                      {m.window_id}
                    </div>
                  </td>
                  <td className="muted">{fmtGmt1(Number(m.settles_at))}</td>
                  <td>{fmtGen(m.pool_wei)} GEN</td>
                  <td className="muted">
                    {fmtCountdown(Number(m.terminal_refund_at) - now)}
                  </td>
                  <td style={{ textAlign: "right" }}>
                    <button
                      className="btn btn-sm btn-primary"
                      disabled={!address || resolve.isPending}
                      onClick={() => resolve.mutate(Number(m.market_id))}
                    >
                      Settle
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      <TxStatus pending={resolve.isPending} error={resolve.error} result={resolve.data} />

      {!address && rows.length > 0 && (
        <div className="notice notice-warn">Connect a wallet to settle a market.</div>
      )}

      {rows.length > 0 && (
        <div className="row wrap dim" style={{ fontSize: 12, gap: 8 }}>
          {rows.map((m) => (
            <span key={m.market_id} className="row" style={{ gap: 6 }}>
              <span className="mono">#{m.market_id}</span>
              <PhaseTag market={m} />
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

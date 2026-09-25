import { Link } from "react-router-dom";

import { PhaseTag } from "../components/PhaseTag";
import { TxStatus } from "../components/TxStatus";
import { useClaim, usePortfolio } from "../hooks";
import { fmtGen, marketTitle, shortAddress } from "../lib/format";
import { useWallet } from "../lib/wallet";

const CLAIM_LABEL: Record<string, string> = {
  PAYOUT: "won",
  LOST: "lost",
  REFUND_INCONCLUSIVE: "refund (feeds disagreed)",
  REFUND_NO_WINNERS: "refund (no winners)",
};

export default function Portfolio() {
  const { address, connect } = useWallet();
  const portfolio = usePortfolio();
  const claimIt = useClaim();

  if (!address) {
    return (
      <div className="card card-pad stack" style={{ maxWidth: 520 }}>
        <h1 style={{ fontSize: 20 }}>Portfolio</h1>
        <p className="muted" style={{ margin: 0 }}>
          Connect a wallet to see your positions, payouts and refunds.
        </p>
        <button className="btn btn-primary" onClick={() => void connect()}>
          Connect wallet
        </button>
      </div>
    );
  }

  const rows = portfolio.data?.positions ?? [];
  const claimableTotal = rows.reduce(
    (sum, r) => (r.position.claimed ? sum : sum + BigInt(r.position.claimable_wei || "0")),
    0n,
  );
  const stakedTotal = rows.reduce((sum, r) => sum + BigInt(r.position.amount_wei || "0"), 0n);

  return (
    <div className="stack" style={{ gap: 18 }}>
      <div className="spread wrap">
        <div>
          <h1 style={{ fontSize: 22 }}>Portfolio</h1>
          <p className="muted" style={{ margin: 0 }}>
            {shortAddress(address)}
          </p>
        </div>
        <div className="row" style={{ gap: 22 }}>
          <div className="stat">
            <b>{fmtGen(stakedTotal)}</b>
            <span className="dim" style={{ fontSize: 12 }}>
              GEN staked
            </span>
          </div>
          <div className="stat">
            <b style={{ color: claimableTotal > 0n ? "var(--up)" : undefined }}>
              {fmtGen(claimableTotal)}
            </b>
            <span className="dim" style={{ fontSize: 12 }}>
              GEN claimable
            </span>
          </div>
        </div>
      </div>

      {portfolio.isLoading && <div className="skeleton" style={{ height: 140 }} />}

      {portfolio.isSuccess && rows.length === 0 && (
        <div className="card card-pad muted">
          No positions yet.{" "}
          <Link to="/" style={{ color: "var(--breek)" }}>
            Find a market
          </Link>
          .
        </div>
      )}

      {rows.length > 0 && (
        <section className="card" style={{ overflowX: "auto" }}>
          <table className="data" style={{ minWidth: 700 }}>
            <thead>
              <tr>
                <th>#</th>
                <th>Market</th>
                <th>Phase</th>
                <th>Side</th>
                <th>Staked</th>
                <th>Outcome</th>
                <th style={{ textAlign: "right" }}>Claimable</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {rows.map(({ market, position }) => {
                const claimable = !position.claimed && BigInt(position.claimable_wei || "0") > 0n;
                return (
                  <tr key={market.market_id}>
                    <td>{market.market_id}</td>
                    <td style={{ fontFamily: "var(--sans)" }}>
                      <Link to={`/market/${market.market_id}`} style={{ color: "var(--breek)" }}>
                        {marketTitle(market)}
                      </Link>
                      <div className="dim" style={{ fontSize: 11 }}>
                        {market.window_id}
                      </div>
                    </td>
                    <td>
                      <PhaseTag market={market} />
                    </td>
                    <td style={{ fontWeight: 600 }}>{position.side}</td>
                    <td>{fmtGen(position.amount_wei)} GEN</td>
                    <td className="muted" style={{ fontFamily: "var(--sans)" }}>
                      {position.claimed
                        ? "claimed"
                        : (CLAIM_LABEL[position.claim_kind] ?? "—")}
                    </td>
                    <td style={{ textAlign: "right" }}>
                      {claimable ? `${fmtGen(position.claimable_wei)} GEN` : "—"}
                    </td>
                    <td style={{ textAlign: "right" }}>
                      {claimable && (
                        <button
                          className="btn btn-sm btn-primary"
                          disabled={claimIt.isPending}
                          onClick={() => claimIt.mutate(Number(market.market_id))}
                        >
                          Claim
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

      <TxStatus pending={claimIt.isPending} error={claimIt.error} result={claimIt.data} />
    </div>
  );
}

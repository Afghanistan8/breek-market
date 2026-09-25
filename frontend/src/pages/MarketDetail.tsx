import { useState } from "react";
import { Link, useParams } from "react-router-dom";

import { Evidence } from "../components/Evidence";
import { PhaseTag } from "../components/PhaseTag";
import { TxStatus } from "../components/TxStatus";
import { WriteGate } from "../components/WriteGate";
import {
  useClaim,
  useEvidence,
  useMarket,
  useNow,
  usePosition,
  useResolveMarket,
  useTakePosition,
} from "../hooks";
import { KIND_LABEL, fmtGen, marketTitle, sharePct, shortAddress } from "../lib/format";
import { explorerAddress } from "../lib/env";
import { fmtCountdown, fmtGmt1Long } from "../lib/gmt";

const STAKES = [2, 3, 4];

export default function MarketDetail() {
  const { id } = useParams();
  const marketId = Number(id);
  const now = useNow();

  const market = useMarket(marketId);
  const position = usePosition(marketId);
  const evidence = useEvidence(marketId, Boolean(market.data?.settled));

  const stake = useTakePosition();
  const resolve = useResolveMarket();
  const claimIt = useClaim();

  const [side, setSide] = useState<string | null>(null);
  const [amount, setAmount] = useState(2);

  if (market.isLoading) return <div className="skeleton" style={{ height: 320 }} />;
  if (market.isError || !market.data) {
    return (
      <div className="notice notice-bad">
        Market {id} could not be loaded: {(market.error as Error)?.message ?? "not found"}
      </div>
    );
  }

  const m = market.data;
  const pos = position.data;
  const lockedSide = pos?.has_position ? pos.side : null;
  const chosen = side ?? lockedSide;
  const canStake = m.phase === "OPEN";
  const canResolve = m.phase === "READY_TO_SETTLE";
  const claimable = pos && BigInt(pos.claimable_wei || "0") > 0n && !pos.claimed;

  return (
    <div className="stack" style={{ gap: 18 }}>
      <div>
        <Link to="/" className="dim" style={{ fontSize: 12 }}>
          &larr; All markets
        </Link>
      </div>

      <section className="card card-pad">
        <div className="spread wrap" style={{ marginBottom: 10 }}>
          <div>
            <div className="eyebrow">{KIND_LABEL[m.kind] ?? m.kind}</div>
            <h1 style={{ fontSize: 23, marginTop: 4 }}>{marketTitle(m)}</h1>
          </div>
          <PhaseTag market={m} />
        </div>

        <p className="muted" style={{ margin: "0 0 16px", maxWidth: "62ch" }}>
          {m.kind.startsWith("DIR") ? (
            <>
              Settles <strong>UP</strong> if {m.asset} closes above where it opened over the{" "}
              GMT+1 {m.timeframe.toLowerCase()} window below, and <strong>DOWN</strong> otherwise.
              An exactly flat close counts as DOWN.
            </>
          ) : (
            <>
              Settles to whichever {m.category.toLowerCase()} asset posts the{" "}
              <strong>strictly greatest</strong> percentage return over the GMT+1{" "}
              {m.timeframe.toLowerCase()} window below. An exact tie settles nothing and refunds
              everyone.
            </>
          )}
        </p>

        <dl className="kv">
          <dt>Window</dt>
          <dd>
            {fmtGmt1Long(Number(m.window_start))} &rarr; {fmtGmt1Long(Number(m.window_end))}
          </dd>
          <dt>Staking closes</dt>
          <dd>
            {fmtGmt1Long(Number(m.cutoff_at))}
            {m.phase === "OPEN" && (
              <span style={{ color: "var(--breek)" }}>
                {" "}
                &middot; in {fmtCountdown(Number(m.cutoff_at) - now)}
              </span>
            )}
          </dd>
          <dt>Settleable from</dt>
          <dd>
            {fmtGmt1Long(Number(m.settles_at))}
            {m.phase === "WINDOW_LIVE" && (
              <span className="muted">
                {" "}
                &middot; in {fmtCountdown(Number(m.settles_at) - now)}
              </span>
            )}
          </dd>
          <dt>Full refund after</dt>
          <dd className="muted">
            {fmtGmt1Long(Number(m.terminal_refund_at))} if still unsettled
          </dd>
          <dt>Pool</dt>
          <dd>
            {fmtGen(m.pool_wei)} GEN across {m.stakers}{" "}
            {m.stakers === "1" ? "staker" : "stakers"}
          </dd>
          <dt>Created by</dt>
          <dd>
            <a
              href={explorerAddress(m.creator)}
              target="_blank"
              rel="noreferrer"
              className="muted"
            >
              {shortAddress(m.creator)}
            </a>
          </dd>
        </dl>
      </section>

      <section className="card card-pad">
        <h2 style={{ fontSize: 15, marginBottom: 12 }}>Sides</h2>
        <table className="data">
          <thead>
            <tr>
              <th>Side</th>
              <th>Staked</th>
              <th>Share</th>
              <th style={{ textAlign: "right" }}>Result</th>
            </tr>
          </thead>
          <tbody>
            {m.valid_sides.map((s) => (
              <tr key={s}>
                <td style={{ fontWeight: 600 }}>{s}</td>
                <td>{fmtGen(m.sides[s] ?? "0")} GEN</td>
                <td>{sharePct(m.sides[s] ?? "0", m.pool_wei).toFixed(1)}%</td>
                <td style={{ textAlign: "right" }}>
                  {m.settled && m.outcome === s ? (
                    <span className="tag tag-up">won</span>
                  ) : m.settled && m.outcome !== "INCONCLUSIVE" ? (
                    <span className="dim">&mdash;</span>
                  ) : (
                    ""
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      {canStake && (
        <section className="card card-pad">
          <h2 style={{ fontSize: 15, marginBottom: 4 }}>Take a position</h2>
          <p className="dim" style={{ fontSize: 12, marginTop: 0 }}>
            2 to 4 GEN per wallet. You may top up the same side; you may never switch sides. An
            invalid stake is refunded inside the same transaction rather than reverting.
          </p>

          {lockedSide && (
            <div className="notice" style={{ marginBottom: 12 }}>
              You hold <strong>{lockedSide}</strong> with {fmtGen(pos!.amount_wei)} GEN. Any
              top-up must stay on {lockedSide} and keep your total at or under 4 GEN.
            </div>
          )}

          <div className="choice-row" style={{ marginBottom: 12 }}>
            {m.valid_sides.map((s) => (
              <button
                key={s}
                className={`choice ${s === "UP" ? "up" : s === "DOWN" ? "down" : ""}`}
                aria-pressed={chosen === s}
                disabled={Boolean(lockedSide) && lockedSide !== s}
                onClick={() => setSide(s)}
              >
                {s}
              </button>
            ))}
          </div>

          <div className="choice-row" style={{ marginBottom: 14 }}>
            {STAKES.map((g) => (
              <button
                key={g}
                className="choice"
                aria-pressed={amount === g}
                onClick={() => setAmount(g)}
              >
                {g} GEN
              </button>
            ))}
          </div>

          <WriteGate action="stake">
            <button
              className="btn btn-primary"
              disabled={!chosen || stake.isPending}
              onClick={() => chosen && stake.mutate({ marketId, side: chosen, gen: amount })}
            >
              {chosen ? `Stake ${amount} GEN on ${chosen}` : "Pick a side first"}
            </button>
          </WriteGate>

          <TxStatus pending={stake.isPending} error={stake.error} result={stake.data} />
        </section>
      )}

      {canResolve && (
        <section className="card card-pad">
          <h2 style={{ fontSize: 15, marginBottom: 4 }}>Settle this market</h2>
          <p className="dim" style={{ fontSize: 12, marginTop: 0 }}>
            The window has closed. Anyone may settle it &mdash; there is no privileged resolver.
            You are not submitting a price; the contract fetches both feeds itself and every
            validator checks the result independently.
          </p>
          <WriteGate action="settle">
            <button
              className="btn btn-primary"
              disabled={resolve.isPending}
              onClick={() => resolve.mutate(marketId)}
            >
              Settle from two feeds
            </button>
          </WriteGate>
          <TxStatus pending={resolve.isPending} error={resolve.error} result={resolve.data} />
        </section>
      )}

      {pos?.has_position && (
        <section className="card card-pad">
          <h2 style={{ fontSize: 15, marginBottom: 12 }}>Your position</h2>
          <dl className="kv">
            <dt>Side</dt>
            <dd>{pos.side}</dd>
            <dt>Staked</dt>
            <dd>{fmtGen(pos.amount_wei)} GEN</dd>
            <dt>Status</dt>
            <dd>
              {pos.claimed
                ? "claimed"
                : pos.claim_kind === "PAYOUT"
                  ? `${fmtGen(pos.claimable_wei)} GEN to claim`
                  : pos.claim_kind === "REFUND_INCONCLUSIVE"
                    ? `${fmtGen(pos.claimable_wei)} GEN refundable`
                    : pos.claim_kind === "REFUND_NO_WINNERS"
                      ? `${fmtGen(pos.claimable_wei)} GEN refundable (no winners)`
                      : pos.claim_kind === "LOST"
                        ? "lost"
                        : "open"}
            </dd>
          </dl>
          {claimable && (
            <>
              <div style={{ marginTop: 12 }}>
                <WriteGate action="claim">
                  <button
                    className="btn btn-primary"
                    disabled={claimIt.isPending}
                    onClick={() => claimIt.mutate(marketId)}
                  >
                    Claim {fmtGen(pos.claimable_wei)} GEN
                  </button>
                </WriteGate>
              </div>
              <TxStatus pending={claimIt.isPending} error={claimIt.error} result={claimIt.data} />
            </>
          )}
        </section>
      )}

      {m.settled && (
        <section className="card card-pad">
          <h2 style={{ fontSize: 15, marginBottom: 4 }}>Settlement evidence</h2>
          <p className="dim" style={{ fontSize: 12, marginTop: 0, marginBottom: 14 }}>
            What each feed reported, and how the two combined.
          </p>
          {evidence.isLoading && <div className="skeleton" style={{ height: 180 }} />}
          {evidence.data && <Evidence market={m} evidence={evidence.data} />}
        </section>
      )}
    </div>
  );
}

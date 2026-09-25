import { useCatalog } from "../hooks";
import { env, explorerAddress } from "../lib/env";
import { bpsAsPct, fmtGen } from "../lib/format";

export default function HowItWorks() {
  const catalog = useCatalog();
  const c = catalog.data;

  return (
    <div className="stack prose" style={{ gap: 18, maxWidth: 800 }}>
      <header className="masthead" style={{ marginBottom: 0 }}>
        <h1 style={{ fontSize: 22 }}>How a round gets its number</h1>
        <p>
          Breek is a forecasting contest, not a betting market. You are not
          taking a position against a counterparty and there is no side to be on.
          You name a price, and you are graded on the distance between your
          number and the one the world actually produced.
        </p>
      </header>

      <section className="panel panel-pad">
        <div className="section-rule">
          <span>The scoring rule</span>
        </div>
        <p style={{ marginTop: 0 }}>
          When the window closes the contract fetches two independent feeds and
          takes their midpoint as the settled price. Your <em>error</em> is how
          far your forecast sat from it, in basis points. Your{" "}
          <em>accuracy weight</em> falls linearly from a perfect call down to
          zero at the cutoff:
        </p>
        <pre className="payload" style={{ marginTop: 8 }}>
{`error   = |forecast − settled| ÷ settled
weight  = cutoff − error        (zero once error ≥ cutoff)
payout  = pot × weight ÷ Σ weights`}
        </pre>
        <ul>
          <li>
            <strong>Everyone inside the band is paid.</strong> There is no
            winning side taking the pot; each entrant earns a share proportional
            to how close they were.
          </li>
          <li>
            <strong>Closer always pays more.</strong> Being nearer than someone
            else strictly beats them, with no threshold to scrape over.
          </li>
          <li>
            <strong>A wild guess earns nothing</strong> and adds nothing to the
            denominator, so it cannot dilute people who did the work.
          </li>
          <li>
            <strong>If nobody lands inside the band</strong>, no accuracy earned
            the pot, so every fee is refunded instead.
          </li>
        </ul>
      </section>

      <section className="panel panel-pad">
        <div className="section-rule">
          <span>Two feeds, converging on a price</span>
        </div>
        <div className="feeds" style={{ marginBottom: 12 }}>
          <div className="feed a">
            <h4>A · {c?.sources.a ?? "gate.io"}</h4>
            <p className="muted" style={{ margin: 0, fontSize: 12.5 }}>
              Hourly spot candles. The GMT+1 window is rebuilt from candle{" "}
              <em>open times</em> &mdash; 24 of them for a day, 168 for a week
              &mdash; and the final candle&rsquo;s close is taken.
            </p>
          </div>
          <div className="feed-join">
            <span>must agree within</span>
            <b>{c ? bpsAsPct(c.tolerance_bps) : "0.50%"}</b>
            <span>or the round voids</span>
          </div>
          <div className="feed b">
            <h4>B · {c?.sources.b ?? "coingecko"}</h4>
            <p className="muted" style={{ margin: 0, fontSize: 12.5 }}>
              An independent price series. The sample at <em>exactly</em> the
              closing instant is selected by timestamp, never the nearest
              available point.
            </p>
          </div>
        </div>
        <p>
          Note what the two feeds are for. They are not voting on an outcome
          &mdash; a forecast needs an actual number, so they have to{" "}
          <em>converge numerically</em>. If they sit further apart than the
          tolerance there is no single honest price to grade against, the round
          is void, and every entry fee comes back.
        </p>
      </section>

      <section className="panel panel-pad">
        <div className="section-rule">
          <span>Why this needs GenLayer</span>
        </div>
        <p style={{ marginTop: 0 }}>
          A normal smart contract cannot make an HTTP request, so someone has to
          push the price on chain &mdash; and that someone becomes the trust
          assumption. Breek&rsquo;s contract fetches both feeds itself, inside a
          GenLayer <code>eq_principle.strict_eq</code> block. Every validator
          independently fetches, derives the same midpoint, and builds one
          canonical string. Consensus passes only if those strings match{" "}
          <em>byte for byte</em>.
        </p>
        <p>
          Once the block returns, the contract re-derives the whole result with
          no network access: it re-binds the payload to this round and this
          window, recomputes the gap between the feeds, and recomputes the
          midpoint. A payload that simply asserts a price is rejected.
        </p>
      </section>

      <section className="panel panel-pad">
        <div className="section-rule">
          <span>Entering</span>
        </div>
        <ul>
          <li>
            One flat fee of {c ? fmtGen(c.entry_fee_wei) : "1"} GEN, one entry
            per wallet. Everyone buys in at the same price.
          </li>
          <li>
            <strong>Revise as often as you like, free</strong>, until the window
            opens. Only your last number is graded. Sharpening your estimate is
            the point, so there is nothing to punish.
          </li>
          <li>
            Anything invalid &mdash; wrong fee, malformed number, too late,
            already entered &mdash; is refunded inside the same transaction
            rather than reverting, so a fee can never be stranded.
          </li>
          <li>
            Forecasts stay sealed until the round is priced, so a late entrant
            cannot copy the field.
          </li>
          <li>Up to {c?.max_entries ?? 200} entrants per round.</li>
        </ul>
      </section>

      <section className="panel panel-pad">
        <div className="section-rule">
          <span>GMT+1, precisely</span>
        </div>
        <p style={{ marginTop: 0 }}>
          Every window is a GMT+1 calendar day or week, and GMT+1 here is a fixed{" "}
          <code>+3600</code> second offset &mdash; no daylight saving, no timezone
          database. Midnight GMT+1 is{" "}
          <strong>23:00 UTC on the previous day</strong>. A weekly window runs
          Monday 00:00 GMT+1 to the following Monday 00:00 GMT+1. Every time in
          this interface is labelled GMT+1 for that reason.
        </p>
      </section>

      <section className="panel panel-pad">
        <div className="section-rule">
          <span>What is listed</span>
        </div>
        {c?.categories.map((cat) => (
          <div key={cat.key} style={{ marginBottom: 14 }}>
            <div className="row" style={{ gap: 8 }}>
              <strong className="mono">{cat.key}</strong>
              {cat.priceable ? (
                <span className="chip chip-live">priceable</span>
              ) : (
                <span className="chip chip-void">not priceable</span>
              )}
            </div>
            <div className="muted" style={{ fontSize: 12.5 }}>
              {cat.assets.join(", ")} &mdash; {cat.basis}
            </div>
            {cat.note && (
              <div className="note note-warn" style={{ marginTop: 8, fontSize: 11.5 }}>
                {cat.note}
              </div>
            )}
          </div>
        ))}
        <p className="dim" style={{ fontSize: 11.5 }}>
          Hourly rounds are not offered: two independent keyless feeds could not
          be shown to reconstruct the same exact GMT+1 hour, and a round that
          cannot be priced twice does not open.
        </p>
      </section>

      <section className="panel panel-pad">
        <div className="section-rule">
          <span>This deployment</span>
        </div>
        <dl className="kv">
          <dt>Network</dt>
          <dd>
            {env.network} · chain {env.chainId}
          </dd>
          <dt>RPC</dt>
          <dd>{env.rpc}</dd>
          <dt>Contract</dt>
          <dd>
            <a
              href={explorerAddress(env.contract)}
              target="_blank"
              rel="noreferrer"
              style={{ textDecoration: "underline" }}
            >
              {env.contract}
            </a>
          </dd>
          {c && (
            <>
              <dt>Entry fee</dt>
              <dd>{fmtGen(c.entry_fee_wei)} GEN</dd>
              <dt>Feed tolerance</dt>
              <dd>{bpsAsPct(c.tolerance_bps)}</dd>
              <dt>Scoring cutoff</dt>
              <dd>{bpsAsPct(c.score_cutoff_bps, 0)}</dd>
              <dt>Refund if unscored</dt>
              <dd>{Number(c.expiry_delay_s) / 86400} days after the window closes</dd>
              <dt>Price scale</dt>
              <dd>{c.price_scale} (integers only, no floats)</dd>
            </>
          )}
        </dl>
        <p className="dim" style={{ fontSize: 11.5, marginTop: 12 }}>
          There is no owner, no pause, no admin scorer and no upgrade hook.{" "}
          <code>score_round</code> takes a round id and nothing else.
        </p>
      </section>
    </div>
  );
}

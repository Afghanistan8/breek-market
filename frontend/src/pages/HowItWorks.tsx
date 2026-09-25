import { useCatalog } from "../hooks";
import { env, explorerAddress } from "../lib/env";

export default function HowItWorks() {
  const catalog = useCatalog();
  const sources = catalog.data?.sources;

  return (
    <div className="stack prose" style={{ gap: 18, maxWidth: 820 }}>
      <div>
        <h1 style={{ fontSize: 22 }}>How Breek settles a market</h1>
        <p>
          Almost every prediction market has a trusted party somewhere: an admin key, a
          multisig, a single oracle feed. Breek removes that party. Nobody &mdash; including
          whoever deployed the contract &mdash; can decide an outcome.
        </p>
      </div>

      <section className="card card-pad">
        <div className="eyebrow">The rule the whole thing rests on</div>
        <div className="sources" style={{ marginTop: 12 }}>
          <div className="source a">
            <h4>Source A &middot; {sources?.a ?? "gate.io"}</h4>
            <p className="muted" style={{ margin: 0, fontSize: 13 }}>
              Hourly spot candlesticks. The contract rebuilds the GMT+1 window from candle{" "}
              <em>open times</em> &mdash; 24 of them for a day, 168 for a week &mdash; and takes
              the first candle&rsquo;s open and the last candle&rsquo;s close.
            </p>
          </div>
          <div className="source b">
            <h4>Source B &middot; {sources?.b ?? "coingecko"}</h4>
            <p className="muted" style={{ margin: 0, fontSize: 13 }}>
              An independent price series. The contract selects the samples at{" "}
              <em>exactly</em> the two window instants, so it can never compare a 23-hour sample
              against a 24-hour close.
            </p>
          </div>
        </div>

        <div className="verdict-join" style={{ marginTop: 14 }}>
          <span className="mono" style={{ color: "var(--src-a)" }}>
            A&rsquo;s verdict
          </span>
          <span className="dim">must equal</span>
          <span className="mono" style={{ color: "var(--src-b)" }}>
            B&rsquo;s verdict
          </span>
          <span className="dim">or nobody wins</span>
        </div>

        <ul style={{ marginTop: 14 }}>
          <li>
            <strong>UP + UP</strong> settles UP. <strong>DOWN + DOWN</strong> settles DOWN.
          </li>
          <li>
            <strong>Same winner twice</strong> settles that winner.
          </li>
          <li>
            <strong>Any disagreement, any tie, any missing verdict</strong> is{" "}
            <em>inconclusive</em>: every stake is refunded in full.
          </li>
          <li>
            A single source can <em>never</em> produce a direction or a winner. Not as a policy
            &mdash; the code cannot express it.
          </li>
        </ul>
      </section>

      <section className="card card-pad">
        <h3 style={{ marginTop: 0 }}>Why this needs GenLayer</h3>
        <p>
          A normal smart contract cannot make an HTTP request. Breek&rsquo;s contract does,
          inside a GenLayer <code>eq_principle.strict_eq</code> block: every validator
          independently fetches both feeds, derives the verdicts, and builds one canonical
          string. Consensus passes only if those strings match <em>byte for byte</em>. If one
          validator saw different data, there is no agreement and nothing settles.
        </p>
        <p>
          Once the block returns, the contract re-derives the entire result from the agreed
          string with no network access at all: it re-checks that the payload belongs to{" "}
          <em>this</em> market and <em>this</em> window, recomputes both verdicts from the raw
          prices, and recomputes how they combine. A payload that simply asserts a winner is
          rejected. That agreed string is then stored as the market&rsquo;s evidence, which you
          can read on any settled market&rsquo;s page.
        </p>
      </section>

      <section className="card card-pad">
        <h3 style={{ marginTop: 0 }}>GMT+1, precisely</h3>
        <p>
          Every window is a GMT+1 calendar day or week, and GMT+1 here is a fixed{" "}
          <code>+3600</code> second offset &mdash; no daylight saving, no timezone database.
          Midnight GMT+1 is <strong>23:00 UTC on the previous day</strong>. A weekly window runs
          Monday 00:00 GMT+1 to the following Monday 00:00 GMT+1.
        </p>
        <p>
          Every time in this interface is labelled GMT+1 for that reason. Staking closes the
          instant the candle opens; settling opens the instant it closes.
        </p>
      </section>

      <section className="card card-pad">
        <h3 style={{ marginTop: 0 }}>Staking and payouts</h3>
        <ul>
          <li>2 to 4 GEN per wallet per market. Top up your side freely inside that band.</li>
          <li>
            You can never switch sides. A stake on the other side is refunded inside the same
            transaction.
          </li>
          <li>
            Anything invalid &mdash; too small, too large, too late, wrong side &mdash; is
            refunded in that same call rather than reverting, so a stake can never get stranded
            in the contract with no way out.
          </li>
          <li>Winners split the entire pool pro-rata by stake. Losers get nothing.</li>
          <li>
            If nobody happened to back the winning side, everyone is refunded instead of the pool
            sitting unclaimable.
          </li>
        </ul>
      </section>

      <section className="card card-pad">
        <h3 style={{ marginTop: 0 }}>When a feed is down</h3>
        <p>
          Settling is retryable. A timeout or a rate limit produces a{" "}
          <code>TRANSIENT</code> error, records nothing, and leaves the market in the resolve
          queue. A malformed or incomplete window produces <code>EXTERNAL</code>. Either way the
          contract never guesses.
        </p>
        <p>
          If five days pass after the window closed and still nobody has settled it, the market
          becomes inconclusive and refunds everyone &mdash; and on that path it makes{" "}
          <strong>no web request at all</strong>. The contract would rather pay everybody back
          than invent a price.
        </p>
      </section>

      <section className="card card-pad">
        <h3 style={{ marginTop: 0 }}>What is listed</h3>
        {catalog.data?.categories.map((c) => (
          <div key={c.key} style={{ marginBottom: 14 }}>
            <div className="row" style={{ gap: 8 }}>
              <strong>{c.key}</strong>
              {c.settlable ? (
                <span className="tag tag-up">settlable</span>
              ) : (
                <span className="tag tag-void">catalog only</span>
              )}
            </div>
            <div className="muted" style={{ fontSize: 13 }}>
              {c.assets.join(", ")} &mdash; {c.return_basis}
            </div>
            {c.note && (
              <div className="notice notice-warn" style={{ marginTop: 8, fontSize: 12 }}>
                {c.note}
              </div>
            )}
          </div>
        ))}
        <p className="dim" style={{ fontSize: 12 }}>
          Hourly markets are not offered. Two independent keyless feeds could not be shown to
          reconstruct the same exact GMT+1 hour, and the two-source rule is not negotiable.
        </p>
      </section>

      <section className="card card-pad">
        <h3 style={{ marginTop: 0 }}>This deployment</h3>
        <dl className="kv">
          <dt>Network</dt>
          <dd>
            {env.network} &middot; chain {env.chainId}
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
          {catalog.data && (
            <>
              <dt>Stake band</dt>
              <dd>
                {Number(BigInt(catalog.data.stake.min_wei) / BigInt(catalog.data.stake.gen_wei))}
                {" – "}
                {Number(BigInt(catalog.data.stake.max_wei) / BigInt(catalog.data.stake.gen_wei))}{" "}
                GEN
              </dd>
              <dt>Refund-all delay</dt>
              <dd>
                {Number(catalog.data.terminal_refund_delay_s) / 86400} days after the window
                closes
              </dd>
              <dt>Price scale</dt>
              <dd>{catalog.data.price_scale} (integers only, no floats)</dd>
            </>
          )}
        </dl>
        <p className="dim" style={{ fontSize: 12, marginTop: 12 }}>
          The price charts and figures in this interface are display-only. They are never sent to
          the contract and play no part in settlement.
        </p>
      </section>
    </div>
  );
}

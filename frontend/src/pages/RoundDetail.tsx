import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { Leaderboard } from "../components/Leaderboard";
import { LivePrice } from "../components/LivePrice";
import { PriceEvidence } from "../components/PriceEvidence";
import { StatusChip } from "../components/RoundRow";
import { TxStatus } from "../components/TxStatus";
import { WriteGate } from "../components/WriteGate";
import {
  useCatalog,
  useCollect,
  useEntry,
  useEvidence,
  useLeaderboard,
  useNow,
  useReviseForecast,
  useRound,
  useScoreRound,
  useSubmitForecast,
} from "../hooks";
import { explorerAddress } from "../lib/env";
import {
  OUTCOME_LABEL,
  bpsAsPct,
  fmtGen,
  shortAddress,
  trimPrice,
} from "../lib/format";
import { fmtCountdown, fmtGmt1Long } from "../lib/gmt";
import { hasFeeds } from "../lib/prices";
import { useWallet } from "../lib/wallet";

export default function RoundDetail() {
  const { id } = useParams();
  const roundId = Number(id);
  const now = useNow();
  const { address } = useWallet();

  const round = useRound(roundId);
  const entry = useEntry(roundId);
  const catalog = useCatalog();
  const board = useLeaderboard(roundId);
  const evidence = useEvidence(roundId, Boolean(round.data?.status));

  const submit = useSubmitForecast();
  const revise = useReviseForecast();
  const scoreIt = useScoreRound();
  const collectIt = useCollect();

  const [draft, setDraft] = useState("");

  const mine = entry.data;
  useEffect(() => {
    if (mine?.entered && draft === "") setDraft(trimPrice(mine.forecast));
  }, [mine, draft]);

  if (round.isLoading) return <div className="skeleton" style={{ height: 320 }} />;
  if (round.isError || !round.data) {
    return (
      <div className="note note-bad">
        Round {id} could not be loaded: {(round.error as Error)?.message ?? "not found"}
      </div>
    );
  }

  const r = round.data;
  const fee = BigInt(r.entry_fee_wei);
  const accepting = r.phase === "ACCEPTING";
  const scoreable = r.phase === "AWAITING_SCORE";
  const collectable = mine && !mine.collected && BigInt(mine.collectable_wei || "0") > 0n;

  // Live context is worth showing while the outcome is still unknown. Once a
  // round is scored the settled price is the number that matters, and a spot
  // quote next to it would only invite confusion.
  const showLive = hasFeeds(r.asset) && (accepting || r.phase === "LOCKED");
  const toleranceBps = Number(catalog.data?.tolerance_bps ?? 50);

  // Mirror the contract's own acceptance rules so a doomed entry is caught
  // before it costs a signature. The bound comes from the catalog rather than
  // a constant here, so the two can never drift apart.
  const trimmed = draft.trim();
  const wellFormed = /^\d+(\.\d+)?$/.test(trimmed);
  const maxForecast = catalog.data ? Number(catalog.data.max_forecast) : Infinity;
  const tooLarge = wellFormed && Number(trimmed) > maxForecast;
  const valid = wellFormed && Number(trimmed) > 0 && !tooLarge;
  const inputProblem = !trimmed
    ? null
    : !wellFormed
      ? "Enter a plain decimal price, digits and one dot."
      : Number(trimmed) <= 0
        ? "A forecast has to be greater than zero."
        : tooLarge
          ? "That is larger than this contract will accept."
          : null;

  return (
    <div className="stack" style={{ gap: 20 }}>
      <div>
        <Link to="/" className="dim" style={{ fontSize: 11.5 }}>
          &larr; Board
        </Link>
      </div>

      <header className="masthead" style={{ marginBottom: 0 }}>
        <div className="spread wrap" style={{ marginBottom: 8 }}>
          <span className="dim mono" style={{ fontSize: 11, letterSpacing: "0.12em" }}>
            ROUND {String(r.round_id).padStart(3, "0")}
          </span>
          <StatusChip round={r} />
        </div>
        <h1 style={{ fontSize: 24 }}>
          What will {r.asset} be worth at{" "}
          {fmtGmt1Long(Number(r.window_end))}?
        </h1>
        <p>
          Graded against the price two independent feeds agree on at that exact
          instant. Closest forecast takes the largest share of the pot; anything
          more than{" "}
          {catalog.data ? bpsAsPct(catalog.data.score_cutoff_bps, 0) : "10%"} off
          scores nothing.
        </p>
      </header>

      <section className="panel panel-pad">
        <dl className="kv">
          <dt>Window</dt>
          <dd>
            {fmtGmt1Long(Number(r.window_start))} &rarr; {fmtGmt1Long(Number(r.window_end))}
          </dd>
          <dt>Forecasts lock</dt>
          <dd>
            {fmtGmt1Long(Number(r.locks_at))}
            {accepting && (
              <span style={{ color: "var(--signal)" }}>
                {" "}
                · in {fmtCountdown(Number(r.locks_at) - now)}
              </span>
            )}
          </dd>
          <dt>Scoreable from</dt>
          <dd>
            {fmtGmt1Long(Number(r.scoreable_at))}
            {r.phase === "LOCKED" && (
              <span className="muted">
                {" "}
                · in {fmtCountdown(Number(r.scoreable_at) - now)}
              </span>
            )}
          </dd>
          <dt>Refunds if unscored</dt>
          <dd className="muted">{fmtGmt1Long(Number(r.expires_at))}</dd>
          <dt>Field</dt>
          <dd>
            {r.entrants} {r.entrants === "1" ? "forecast" : "forecasts"} ·{" "}
            {fmtGen(r.pot_wei)} GEN pot
          </dd>
          {r.status === "SCORED" && (
            <>
              <dt>Settled at</dt>
              <dd style={{ color: "var(--signal)", fontSize: 15 }}>
                {trimPrice(r.consensus)}
              </dd>
            </>
          )}
          <dt>Opened by</dt>
          <dd>
            <a
              href={explorerAddress(r.opener)}
              target="_blank"
              rel="noreferrer"
              className="muted"
            >
              {shortAddress(r.opener)}
            </a>
          </dd>
        </dl>
      </section>

      {accepting && (
        <section className="panel panel-pad">
          <div className="section-rule">
            <span>{mine?.entered ? "Your forecast" : "Enter this round"}</span>
          </div>

          {mine?.entered ? (
            <p className="dim" style={{ fontSize: 12, marginTop: 0 }}>
              You are in. Revising costs nothing and you may do it as often as you
              like until the window opens &mdash; only your last number is graded.
              {mine.revisions !== "0" && ` Revised ${mine.revisions} time(s) so far.`}
            </p>
          ) : (
            <p className="dim" style={{ fontSize: 12, marginTop: 0 }}>
              One flat fee of {fmtGen(r.entry_fee_wei)} GEN, one entry per wallet.
              Everybody pays the same, so only accuracy separates the payouts.
            </p>
          )}

          {showLive && (
            <div style={{ marginBottom: 14 }}>
              <LivePrice
                symbol={r.asset}
                toleranceBps={toleranceBps}
                onUse={setDraft}
              />
            </div>
          )}

          <label className="field" style={{ marginBottom: inputProblem ? 8 : 12 }}>
            {r.asset} price at close
            <input
              className="forecast-input mono"
              inputMode="decimal"
              placeholder="0.00"
              value={draft}
              aria-invalid={Boolean(inputProblem)}
              onChange={(e) => setDraft(e.target.value)}
            />
          </label>

          {inputProblem && (
            <div className="note note-warn" style={{ marginBottom: 12 }}>
              {inputProblem}
            </div>
          )}

          <WriteGate action={mine?.entered ? "revise" : "enter"}>
            {mine?.entered ? (
              <button
                className="btn btn-primary"
                disabled={!valid || revise.isPending}
                onClick={() => revise.mutate({ roundId, forecast: draft.trim() })}
              >
                Revise to {valid ? draft.trim() : "…"}
              </button>
            ) : (
              <button
                className="btn btn-primary"
                disabled={!valid || submit.isPending}
                onClick={() =>
                  submit.mutate({ roundId, forecast: draft.trim(), feeWei: fee })
                }
              >
                Submit for {fmtGen(r.entry_fee_wei)} GEN
              </button>
            )}
          </WriteGate>

          <TxStatus pending={submit.isPending} error={submit.error} result={submit.data} />
          <TxStatus pending={revise.isPending} error={revise.error} result={revise.data} />
        </section>
      )}

      {showLive && !accepting && (
        <section className="panel panel-pad">
          <div className="section-rule">
            <span>Where it is trading now</span>
          </div>
          <p className="dim" style={{ fontSize: 12, marginTop: 0 }}>
            Forecasts are locked. This is only here so you can watch the window
            play out.
          </p>
          <LivePrice symbol={r.asset} toleranceBps={toleranceBps} />
        </section>
      )}

      {scoreable && (
        <section className="panel panel-pad">
          <div className="section-rule">
            <span>Price this round</span>
          </div>
          <p className="dim" style={{ fontSize: 12, marginTop: 0 }}>
            The window has closed. Anyone may price it &mdash; there is no
            privileged scorer. You are not submitting a number; the contract
            fetches both feeds itself and every validator checks the result.
          </p>
          <WriteGate action="price this round">
            <button
              className="btn btn-primary"
              disabled={scoreIt.isPending}
              onClick={() => scoreIt.mutate(roundId)}
            >
              Fetch both feeds and grade
            </button>
          </WriteGate>
          <TxStatus pending={scoreIt.isPending} error={scoreIt.error} result={scoreIt.data} />
        </section>
      )}

      {mine?.entered && (
        <section className="panel panel-pad">
          <div className="section-rule">
            <span>Your result</span>
          </div>
          <dl className="kv">
            <dt>You called</dt>
            <dd style={{ fontSize: 15 }}>{trimPrice(mine.forecast)}</dd>
            {mine.error_bps !== "" && (
              <>
                <dt>Off by</dt>
                <dd
                  style={{
                    color: Number(mine.weight) === 0 ? "var(--drift)" : "var(--signal)",
                  }}
                >
                  {bpsAsPct(mine.error_bps)}
                </dd>
              </>
            )}
            {mine.outcome !== "" && (
              <>
                <dt>Outcome</dt>
                <dd style={{ fontFamily: "var(--sans)" }}>
                  {OUTCOME_LABEL[mine.outcome] ?? mine.outcome}
                </dd>
              </>
            )}
            <dt>To collect</dt>
            <dd>{mine.collected ? "collected" : `${fmtGen(mine.collectable_wei)} GEN`}</dd>
          </dl>
          {collectable && (
            <div style={{ marginTop: 12 }}>
              <WriteGate action="collect">
                <button
                  className="btn btn-primary"
                  disabled={collectIt.isPending}
                  onClick={() => collectIt.mutate(roundId)}
                >
                  Collect {fmtGen(mine.collectable_wei)} GEN
                </button>
              </WriteGate>
              <TxStatus
                pending={collectIt.isPending}
                error={collectIt.error}
                result={collectIt.data}
              />
            </div>
          )}
        </section>
      )}

      <section className="panel panel-pad">
        <div className="section-rule">
          <span>Leaderboard</span>
        </div>
        {board.isLoading && <div className="skeleton" style={{ height: 120 }} />}
        {board.data && (
          <Leaderboard
            board={board.data}
            cutoffBps={catalog.data?.score_cutoff_bps ?? "1000"}
            me={address}
          />
        )}
      </section>

      {r.status !== "" && (
        <section className="panel panel-pad">
          <div className="section-rule">
            <span>Where the number came from</span>
          </div>
          {evidence.isLoading && <div className="skeleton" style={{ height: 160 }} />}
          {evidence.data && <PriceEvidence evidence={evidence.data} />}
        </section>
      )}
    </div>
  );
}

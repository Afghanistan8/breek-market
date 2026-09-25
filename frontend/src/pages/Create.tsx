import { useEffect, useMemo, useState } from "react";

import { TxStatus } from "../components/TxStatus";
import { WriteGate } from "../components/WriteGate";
import { useCatalog, useCreateMarket } from "../hooks";
import {
  fmtGmt1Long,
  dayWindow,
  gmt1DayId,
  isMonday,
  isValidWindowId,
  nextMondayId,
  weekWindow,
} from "../lib/gmt";

type Timeframe = "DAILY" | "WEEKLY";
type Shape = "DIR" | "REL";

export default function Create() {
  const catalog = useCatalog();
  const create = useCreateMarket();

  const [shape, setShape] = useState<Shape>("DIR");
  const [timeframe, setTimeframe] = useState<Timeframe>("DAILY");
  const [category, setCategory] = useState("CRYPTO");
  const [asset, setAsset] = useState("SOL");
  const [windowId, setWindowId] = useState(() => gmt1DayId(1));

  const categories = catalog.data?.categories ?? [];
  const current = categories.find((c) => c.key === category);
  const settlable = current?.settlable ?? true;

  // Keep the window id consistent with the timeframe: weeks must start Monday.
  useEffect(() => {
    setWindowId(timeframe === "WEEKLY" ? nextMondayId() : gmt1DayId(1));
  }, [timeframe]);

  useEffect(() => {
    if (current && !current.assets.includes(asset)) setAsset(current.assets[0] ?? "");
  }, [current, asset]);

  const kind = `${shape}_${timeframe}`;

  const problem = useMemo(() => {
    if (!settlable) {
      return (
        current?.note ||
        "This category is listed but cannot be settled from two independent feeds."
      );
    }
    if (!isValidWindowId(windowId)) return "Window must be a real date in YYYY-MM-DD form.";
    if (timeframe === "WEEKLY" && !isMonday(windowId)) {
      return "A GMT+1 week starts on a Monday. Pick a Monday.";
    }
    const [start] = timeframe === "WEEKLY" ? weekWindow(windowId) : dayWindow(windowId);
    const now = Math.floor(Date.now() / 1000);
    if (start <= now) return "That window has already opened. Pick a future one.";
    if (start - now > 366 * 86400) return "Markets cannot be created more than 366 days ahead.";
    return null;
  }, [settlable, current, windowId, timeframe]);

  const bounds = isValidWindowId(windowId)
    ? timeframe === "WEEKLY" && isMonday(windowId)
      ? weekWindow(windowId)
      : timeframe === "DAILY"
        ? dayWindow(windowId)
        : null
    : null;

  return (
    <div className="stack" style={{ gap: 18, maxWidth: 720 }}>
      <div>
        <h1 style={{ fontSize: 22 }}>Create a market</h1>
        <p className="muted" style={{ maxWidth: "62ch" }}>
          Anyone can list a market on a catalog asset. There is no fee, no approval and no
          owner &mdash; you are only choosing which listed thing, and which GMT+1 window.
        </p>
      </div>

      <section className="card card-pad stack">
        <div>
          <div className="eyebrow" style={{ marginBottom: 6 }}>
            What are people predicting
          </div>
          <div className="choice-row">
            <button className="choice" aria-pressed={shape === "DIR"} onClick={() => setShape("DIR")}>
              Direction
              <div className="dim" style={{ fontSize: 11, fontWeight: 400 }}>
                one asset, UP or DOWN
              </div>
            </button>
            <button className="choice" aria-pressed={shape === "REL"} onClick={() => setShape("REL")}>
              Relative return
              <div className="dim" style={{ fontSize: 11, fontWeight: 400 }}>
                which asset gains most
              </div>
            </button>
          </div>
        </div>

        <div>
          <div className="eyebrow" style={{ marginBottom: 6 }}>
            Window length
          </div>
          <div className="choice-row">
            {(["DAILY", "WEEKLY"] as Timeframe[]).map((t) => (
              <button
                key={t}
                className="choice"
                aria-pressed={timeframe === t}
                onClick={() => setTimeframe(t)}
              >
                {t === "DAILY" ? "One GMT+1 day" : "One GMT+1 week"}
              </button>
            ))}
          </div>
          <p className="dim" style={{ fontSize: 12, marginBottom: 0 }}>
            Hourly is not offered: no two independent keyless feeds could be proven to
            reconstruct the same exact GMT+1 hour, and Breek will not weaken the two-source rule
            to add a timeframe.
          </p>
        </div>

        <label className="field">
          Category
          <select value={category} onChange={(e) => setCategory(e.target.value)}>
            {categories.map((c) => (
              <option key={c.key} value={c.key}>
                {c.key}
                {c.settlable ? "" : " (not settlable)"}
              </option>
            ))}
          </select>
        </label>

        {current && !current.settlable && (
          <div className="notice notice-warn">{current.note}</div>
        )}

        {shape === "DIR" && current && (
          <div>
            <div className="eyebrow" style={{ marginBottom: 6 }}>
              Asset
            </div>
            <div className="choice-row">
              {current.assets.map((a) => (
                <button
                  key={a}
                  className="choice"
                  aria-pressed={asset === a}
                  onClick={() => setAsset(a)}
                >
                  {a}
                </button>
              ))}
            </div>
          </div>
        )}

        {shape === "REL" && current && (
          <div className="notice">
            Every asset in {current.key} competes: <strong>{current.assets.join(", ")}</strong>.
            The winner is the one with the strictly greatest return &mdash; {current.return_basis}.
          </div>
        )}

        <label className="field">
          {timeframe === "WEEKLY" ? "Week starting (GMT+1 Monday)" : "GMT+1 day"}
          <input
            type="date"
            value={windowId}
            onChange={(e) => setWindowId(e.target.value)}
            min={gmt1DayId(1)}
          />
        </label>

        {bounds && (
          <div className="notice">
            <div className="spread" style={{ gap: 8 }}>
              <span className="dim">Candle opens</span>
              <span className="mono">{fmtGmt1Long(bounds[0])}</span>
            </div>
            <div className="spread" style={{ gap: 8, marginTop: 4 }}>
              <span className="dim">Candle closes</span>
              <span className="mono">{fmtGmt1Long(bounds[1])}</span>
            </div>
            <div className="dim" style={{ fontSize: 12, marginTop: 8 }}>
              Staking closes the moment the candle opens. Midnight GMT+1 is 23:00 UTC the
              previous day &mdash; not midnight where you are.
            </div>
          </div>
        )}

        {problem && <div className="notice notice-warn">{problem}</div>}

        <WriteGate action="create a market">
          <button
            className="btn btn-primary"
            disabled={Boolean(problem) || create.isPending}
            onClick={() =>
              create.mutate({
                kind,
                category,
                asset: shape === "REL" ? "" : asset,
                timeframe,
                windowId,
              })
            }
          >
            {`Create ${kind} market`}
          </button>
        </WriteGate>

        <TxStatus pending={create.isPending} error={create.error} result={create.data} />
      </section>
    </div>
  );
}

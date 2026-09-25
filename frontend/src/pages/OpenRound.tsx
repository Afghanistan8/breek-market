import { useEffect, useMemo, useState } from "react";

import { TxStatus } from "../components/TxStatus";
import { WriteGate } from "../components/WriteGate";
import { useCatalog, useOpenRound } from "../hooks";
import { bpsAsPct, fmtGen } from "../lib/format";
import {
  dayWindow,
  fmtGmt1Long,
  gmt1DayId,
  isMonday,
  isValidWindowId,
  nextMondayId,
  weekWindow,
} from "../lib/gmt";

type Timeframe = "DAILY" | "WEEKLY";

export default function OpenRound() {
  const catalog = useCatalog();
  const open = useOpenRound();

  const [timeframe, setTimeframe] = useState<Timeframe>("DAILY");
  const [category, setCategory] = useState("CRYPTO");
  const [asset, setAsset] = useState("SOL");
  const [windowId, setWindowId] = useState(() => gmt1DayId(1));

  const categories = catalog.data?.categories ?? [];
  const current = categories.find((c) => c.key === category);
  const priceable = current?.priceable ?? true;

  useEffect(() => {
    setWindowId(timeframe === "WEEKLY" ? nextMondayId() : gmt1DayId(1));
  }, [timeframe]);

  useEffect(() => {
    if (current && !current.assets.includes(asset)) setAsset(current.assets[0] ?? "");
  }, [current, asset]);

  const problem = useMemo(() => {
    if (!priceable) {
      return current?.note || "This category cannot be priced from two independent feeds.";
    }
    if (!isValidWindowId(windowId)) return "Window must be a real date in YYYY-MM-DD form.";
    if (timeframe === "WEEKLY" && !isMonday(windowId)) {
      return "A GMT+1 week starts on a Monday. Pick a Monday.";
    }
    const [start] = timeframe === "WEEKLY" ? weekWindow(windowId) : dayWindow(windowId);
    const now = Math.floor(Date.now() / 1000);
    if (start <= now) return "That window has already opened. Pick a future one.";
    if (start - now > 366 * 86400) return "Rounds cannot be opened more than 366 days ahead.";
    return null;
  }, [priceable, current, windowId, timeframe]);

  const bounds = isValidWindowId(windowId)
    ? timeframe === "WEEKLY" && isMonday(windowId)
      ? weekWindow(windowId)
      : timeframe === "DAILY"
        ? dayWindow(windowId)
        : null
    : null;

  return (
    <div className="stack" style={{ gap: 18, maxWidth: 660 }}>
      <header className="masthead" style={{ marginBottom: 0 }}>
        <h1 style={{ fontSize: 22 }}>Open a round</h1>
        <p>
          Put a question up for forecasting. There is no fee, no approval and no
          owner &mdash; you are only choosing which listed asset, and which GMT+1
          window it closes in. Opening a round does not enter you into it.
        </p>
      </header>

      <section className="panel panel-pad stack">
        <div>
          <div className="section-rule">
            <span>Window length</span>
          </div>
          <div className="pickers">
            {(["DAILY", "WEEKLY"] as Timeframe[]).map((t) => (
              <button
                key={t}
                aria-pressed={timeframe === t}
                onClick={() => setTimeframe(t)}
              >
                {t === "DAILY" ? "One GMT+1 day" : "One GMT+1 week"}
              </button>
            ))}
          </div>
          <p className="dim" style={{ fontSize: 11.5, marginBottom: 0 }}>
            No hourly window: two independent keyless feeds could not be shown to
            reconstruct the same exact GMT+1 hour, and a round that cannot be
            priced twice does not open.
          </p>
        </div>

        <label className="field">
          Category
          <select value={category} onChange={(e) => setCategory(e.target.value)}>
            {categories.map((c) => (
              <option key={c.key} value={c.key}>
                {c.key}
                {c.priceable ? "" : " — not priceable"}
              </option>
            ))}
          </select>
        </label>

        {current && !current.priceable && <div className="note note-warn">{current.note}</div>}

        {current && current.priceable && (
          <div>
            <div className="section-rule">
              <span>Asset</span>
            </div>
            <div className="pickers">
              {current.assets.map((a) => (
                <button key={a} aria-pressed={asset === a} onClick={() => setAsset(a)}>
                  {a}
                </button>
              ))}
            </div>
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
          <div className="note">
            <div className="spread" style={{ gap: 8 }}>
              <span className="dim">Window opens &amp; forecasts lock</span>
              <span className="mono">{fmtGmt1Long(bounds[0])}</span>
            </div>
            <div className="spread" style={{ gap: 8, marginTop: 4 }}>
              <span className="dim">Price is taken</span>
              <span className="mono">{fmtGmt1Long(bounds[1])}</span>
            </div>
            <div className="dim" style={{ fontSize: 11.5, marginTop: 8 }}>
              Midnight GMT+1 is 23:00 UTC the previous day &mdash; not midnight
              where you are.
            </div>
          </div>
        )}

        {catalog.data && (
          <div className="note">
            Entrants will pay {fmtGen(catalog.data.entry_fee_wei)} GEN each. The
            two feeds must land within {bpsAsPct(catalog.data.tolerance_bps)} of
            each other or the round voids and everyone is refunded.
          </div>
        )}

        {problem && <div className="note note-warn">{problem}</div>}

        <WriteGate action="open a round">
          <button
            className="btn btn-primary"
            disabled={Boolean(problem) || open.isPending}
            onClick={() => open.mutate({ category, asset, timeframe, windowId })}
          >
            Open {asset} {timeframe === "WEEKLY" ? "weekly" : "daily"} round
          </button>
        </WriteGate>

        <TxStatus pending={open.isPending} error={open.error} result={open.data} />
      </section>
    </div>
  );
}

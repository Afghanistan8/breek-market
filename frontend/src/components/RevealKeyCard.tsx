import { useState } from "react";

import type { RevealKey } from "../lib/commit";

/**
 * The one piece of state a user cannot afford to lose.
 *
 * A commitment can only be opened with the price and the salt together. Those
 * cannot live on chain -- publishing them would defeat the commitment -- so
 * they live in this browser. If they are lost, the entry can never be revealed
 * and the fee is forfeited. There is no recovery path and deliberately no
 * privileged address that could create one.
 *
 * So the key is not hidden in localStorage and hoped about. It is shown, it can
 * be copied, and it can be downloaded, on the screen where it is created.
 */
export const RevealKeyCard = ({
  rkey,
  tone = "fresh",
}: {
  rkey: RevealKey;
  tone?: "fresh" | "quiet";
}) => {
  const [copied, setCopied] = useState(false);

  const asText =
    `Breek reveal key\n` +
    `contract: ${rkey.contract}\n` +
    `round:    ${rkey.roundId}\n` +
    `wallet:   ${rkey.address}\n` +
    `forecast: ${rkey.forecast}\n` +
    `salt:     ${rkey.salt}\n` +
    `\nBoth the forecast and the salt are needed to reveal. Without them the ` +
    `entry cannot be opened and the fee is forfeited.\n`;

  const copy = () => {
    void navigator.clipboard
      .writeText(asText)
      .then(() => {
        setCopied(true);
        window.setTimeout(() => setCopied(false), 2000);
      })
      .catch(() => setCopied(false));
  };

  const download = () => {
    const blob = new Blob([asText], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `breek-reveal-round-${rkey.roundId}.txt`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className={tone === "fresh" ? "note note-warn keycard" : "keycard keycard-quiet"}>
      <div className="keycard-head">
        <strong>Reveal key — round {String(rkey.roundId).padStart(3, "0")}</strong>
        <span className="row" style={{ gap: 6 }}>
          <button className="btn btn-sm" onClick={copy}>
            {copied ? "Copied" : "Copy"}
          </button>
          <button className="btn btn-sm" onClick={download}>
            Download
          </button>
        </span>
      </div>

      <dl className="keycard-grid">
        <dt>Forecast</dt>
        <dd className="mono">{rkey.forecast}</dd>
        <dt>Salt</dt>
        <dd className="mono keycard-salt">{rkey.salt}</dd>
      </dl>

      {tone === "fresh" && (
        <p style={{ margin: "8px 0 0", fontSize: 11.5 }}>
          Keep these. They are stored in this browser, but only here — clearing
          site data, switching device or using a private window will lose them.
          You need both to reveal after entries close, and an entry that is
          never revealed forfeits its fee.
        </p>
      )}
    </div>
  );
};

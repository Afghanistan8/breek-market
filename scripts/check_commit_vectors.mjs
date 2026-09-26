/**
 * Hold the frontend's commitment scheme to the same known answers the contract
 * is held to.
 *
 *     node scripts/check_commit_vectors.mjs
 *
 * This reads `frontend/src/lib/commit.ts` and runs its real `scalePrice` and
 * `computeCommitment` against `tests/vectors/commit_vectors.json`. It does not
 * reimplement them -- a copy here would drift from the shipped file and start
 * passing for the wrong reason.
 *
 * Why this matters more than a normal unit test: a client that hashes anything
 * the contract will not reproduce still takes the entry fee, and leaves behind
 * a commitment that can never be opened. The fee is then forfeited through no
 * fault of the entrant. There is no recovery path for that, by design, so the
 * only defence is not shipping the mismatch.
 */

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, "..");

const vectors = JSON.parse(
  readFileSync(join(root, "tests", "vectors", "commit_vectors.json"), "utf8"),
);

// Load the shipped TypeScript by stripping the type annotations it uses. The
// file is deliberately plain enough for this to be reliable; anything cleverer
// would mean testing a transformation rather than the code.
const source = readFileSync(join(root, "frontend", "src", "lib", "commit.ts"), "utf8");
const js = source
  .replace(/^import[^;]*;$/gm, "")
  .replace(/^export interface [\s\S]*?^}$/gm, "")
  .replace(/: Promise<[^>]*>/g, "")
  .replace(/: RevealKey\[\]/g, "")
  .replace(/: RevealKey \| null/g, "")
  .replace(/: string \| null/g, "")
  .replace(/\(key: RevealKey\)/g, "(key)")
  .replace(/\(catalog: \{[\s\S]*?\}\)/g, "(catalog)")
  .replace(/\((\w+): (string|number|bigint|ArrayBuffer)\)/g, "($1)")
  .replace(/(\w+): (string|number|bigint),/g, "$1,")
  .replace(/(\w+): (string|number|bigint)\)/g, "$1)")
  .replace(/: (string|number|bigint|void|boolean)(?= =>)/g, "")
  .replace(/ as RevealKey(\[\])?/g, "")
  .replace(/^export /gm, "");

const mod = await import(
  `data:text/javascript;base64,${Buffer.from(
    `${js}\nexport { scalePrice, computeCommitment, unscalePrice };`,
  ).toString("base64")}`
);

let failures = 0;
for (const v of vectors.vectors) {
  const scaled = mod.scalePrice(v.forecast).toString();
  const digest = await mod.computeCommitment(v.round_id, v.address, v.forecast, v.salt);
  const ok = scaled === v.scaled && digest === v.commitment;
  if (!ok) failures += 1;
  console.log(
    `${ok ? "OK  " : "FAIL"} ${v.forecast.padEnd(16)} scaled=${scaled.padEnd(16)} ${digest.slice(0, 20)}`,
  );
  if (!ok) {
    console.log(`     expected scaled=${v.scaled} ${v.commitment.slice(0, 20)}`);
  }
}

// A checksummed address must not quietly produce a different digest than the
// contract would compute, so the client has to lowercase it.
const mixed = await mod.computeCommitment(
  3,
  "0x4184bc5E5444F250767E8D33A49817A9B4FB0df3",
  "5.00",
  "a1b2c3d4e5f60718",
);
const lower = vectors.vectors.find((v) => v.round_id === 3).commitment;
if (mixed !== lower) {
  failures += 1;
  console.log("FAIL checksummed address produced a different digest");
} else {
  console.log("OK   checksummed address normalises to the same digest");
}

console.log(`\n${failures === 0 ? "all vectors match" : `${failures} MISMATCH(ES)`}`);
process.exit(failures === 0 ? 0 : 1);

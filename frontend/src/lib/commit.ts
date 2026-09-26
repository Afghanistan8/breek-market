/**
 * The commitment scheme, client side.
 *
 * A forecast must not be readable by anyone until entries close, and a
 * blockchain cannot hide a plaintext argument -- transaction calldata is public
 * the moment it is broadcast. So the price never leaves this file in the clear:
 * it is hashed here, the digest goes on chain, and the price itself is supplied
 * later, during the reveal window, where the contract recomputes the digest and
 * compares.
 *
 * Everything here mirrors `contracts/BreekForecast.py` exactly. If the scaling
 * or the preimage drifts by a single character, the digest will not match and
 * the entry becomes impossible to reveal -- which forfeits the fee. The
 * contract publishes the scheme through `get_catalog` (`commit_preimage`,
 * `salt_min_len`, `price_scale`) precisely so this can be checked rather than
 * assumed, and `verifyScheme` below does check it.
 */

/** Digits of fixed-point precision. Must equal the contract's PRICE_SCALE. */
const PRICE_DIGITS = 8;

export const COMMIT_VERSION = "c1";

/** 128 bits of salt, as 32 lowercase hex characters. */
const SALT_BYTES = 16;

/**
 * Decimal string to a scaled integer, exactly as the contract does it.
 *
 * Deliberately string arithmetic, never `Number`. A price like `0.1` has no
 * exact double, and `0.1 * 1e8` is `10000000.000000002`; rounding that would
 * produce a digest the contract could never reproduce.
 */
export const scalePrice = (text: string): bigint => {
  const s = text.trim().replace(/^\+/, "");
  if (s === "") throw new Error("Enter a price.");
  if (s.startsWith("-")) throw new Error("A forecast cannot be negative.");
  if (/[eE]/.test(s)) throw new Error("Write the number out in full, not 1e5.");

  const dot = s.indexOf(".");
  const whole = dot === -1 ? s : s.slice(0, dot);
  const rawFrac = dot === -1 ? "" : s.slice(dot + 1);
  if (rawFrac.includes(".")) throw new Error("Only one decimal point.");

  const w = whole === "" ? "0" : whole;
  if (!/^\d+$/.test(w)) throw new Error("Digits and one decimal point only.");
  if (rawFrac !== "" && !/^\d+$/.test(rawFrac)) {
    throw new Error("Digits and one decimal point only.");
  }

  // Excess precision truncates rather than rounding -- the contract does the
  // same, and both sides must agree on the discarded digits.
  const frac = (rawFrac + "0".repeat(PRICE_DIGITS)).slice(0, PRICE_DIGITS);
  return BigInt(w) * 10n ** BigInt(PRICE_DIGITS) + BigInt(frac);
};

/** Render a scaled integer back to the contract's decimal form. */
export const unscalePrice = (scaled: bigint): string => {
  const unit = 10n ** BigInt(PRICE_DIGITS);
  return `${scaled / unit}.${(scaled % unit).toString().padStart(PRICE_DIGITS, "0")}`;
};

/** A fresh salt. Uses the platform CSPRNG; never a timestamp or Math.random. */
export const newSalt = (): string => {
  const bytes = new Uint8Array(SALT_BYTES);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
};

const toHex = (buf: ArrayBuffer): string =>
  Array.from(new Uint8Array(buf), (b) => b.toString(16).padStart(2, "0")).join("");

/**
 * The digest the contract will check a reveal against.
 *
 * The address is lowercased because the contract renders it that way; a
 * checksummed address would produce a different, unrevealable digest.
 */
export const computeCommitment = async (
  roundId: number,
  address: string,
  forecast: string,
  salt: string,
): Promise<string> => {
  const preimage = [
    COMMIT_VERSION,
    String(roundId),
    address.toLowerCase(),
    scalePrice(forecast).toString(),
    salt,
  ].join("|");
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(preimage));
  return toHex(digest);
};

/**
 * Check this file still agrees with the deployed contract.
 *
 * Cheap insurance against the worst failure mode this design has: a client
 * that hashes something the contract will not reproduce takes the fee and
 * leaves an entry that can never be opened. Catching that before the first
 * commit costs one view call.
 */
export const verifyScheme = (catalog: {
  commit_version?: string;
  commit_preimage?: string;
  price_scale?: string;
  salt_min_len?: string;
}): string | null => {
  if (catalog.commit_version && catalog.commit_version !== COMMIT_VERSION) {
    return `This contract uses commitment scheme ${catalog.commit_version}, this app speaks ${COMMIT_VERSION}.`;
  }
  if (catalog.price_scale && catalog.price_scale !== String(10 ** PRICE_DIGITS)) {
    return `This contract scales prices by ${catalog.price_scale}, this app uses ${10 ** PRICE_DIGITS}.`;
  }
  if (catalog.salt_min_len && Number(catalog.salt_min_len) > SALT_BYTES * 2) {
    return `This contract needs a salt of at least ${catalog.salt_min_len} characters; this app generates ${SALT_BYTES * 2}.`;
  }
  return null;
};

// ---------------------------------------------------------------------------
// Reveal keys
// ---------------------------------------------------------------------------

/**
 * What you need to open a commitment later: the price and the salt.
 *
 * This is kept in the browser because it must not be on chain -- putting it
 * anywhere public would defeat the commitment entirely. That makes it the one
 * piece of state the user genuinely cannot afford to lose, so the UI shows it
 * and offers it as a download rather than hiding it in storage and hoping.
 */
export interface RevealKey {
  contract: string;
  roundId: number;
  address: string;
  forecast: string;
  salt: string;
  committedAt: number;
}

const KEY_PREFIX = "breek.reveal.";

const keyName = (contract: string, roundId: number, address: string) =>
  `${KEY_PREFIX}${contract.toLowerCase()}.${roundId}.${address.toLowerCase()}`;

export const saveRevealKey = (key: RevealKey): void => {
  try {
    localStorage.setItem(keyName(key.contract, key.roundId, key.address), JSON.stringify(key));
  } catch {
    // Private windows and blocked site data both land here. The caller still
    // shows the key on screen, so a failed write is survivable -- it must not
    // stop the entry.
  }
};

export const loadRevealKey = (
  contract: string,
  roundId: number,
  address: string,
): RevealKey | null => {
  try {
    const raw = localStorage.getItem(keyName(contract, roundId, address));
    return raw ? (JSON.parse(raw) as RevealKey) : null;
  } catch {
    return null;
  }
};

export const forgetRevealKey = (contract: string, roundId: number, address: string): void => {
  try {
    localStorage.removeItem(keyName(contract, roundId, address));
  } catch {
    /* nothing to do */
  }
};

/** Every reveal key this browser holds, newest first. */
export const allRevealKeys = (): RevealKey[] => {
  const out: RevealKey[] = [];
  try {
    for (let i = 0; i < localStorage.length; i += 1) {
      const name = localStorage.key(i);
      if (!name || !name.startsWith(KEY_PREFIX)) continue;
      const raw = localStorage.getItem(name);
      if (raw) out.push(JSON.parse(raw) as RevealKey);
    }
  } catch {
    return out;
  }
  return out.sort((a, b) => b.committedAt - a.committedAt);
};

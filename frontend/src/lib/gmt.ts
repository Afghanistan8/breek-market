/**
 * GMT+1 time, spelled out.
 *
 * Every window in Breek is a GMT+1 calendar day or week, and GMT+1 here means a
 * fixed +3600 second offset from UTC -- no DST, no timezone database. The UI
 * never shows a bare local time for a window boundary, because "midnight" in
 * the viewer's own zone is almost never the instant the candle opens.
 *
 * These helpers mirror contracts/BreekForecast.py exactly. If one changes, both
 * change.
 */

export const DAY = 86400;
export const HOUR = 3600;
export const WEEK = 7 * DAY;
export const GMT_PLUS_ONE = 3600;

export const isLeap = (y: number): boolean =>
  (y % 4 === 0 && y % 100 !== 0) || y % 400 === 0;

export const daysInMonth = (y: number, m: number): number => {
  if (m === 2) return isLeap(y) ? 29 : 28;
  return [4, 6, 9, 11].includes(m) ? 30 : 31;
};

export const daysFromCivil = (y: number, m: number, d: number): number => {
  const yy = y - (m <= 2 ? 1 : 0);
  const era = Math.floor((yy >= 0 ? yy : yy - 399) / 400);
  const yoe = yy - era * 400;
  const doy = Math.floor((153 * (m + (m > 2 ? -3 : 9)) + 2) / 5) + d - 1;
  const doe = yoe * 365 + Math.floor(yoe / 4) - Math.floor(yoe / 100) + doy;
  return era * 146097 + doe - 719468;
};

export const civilFromDays = (z0: number): [number, number, number] => {
  const z = z0 + 719468;
  const era = Math.floor((z >= 0 ? z : z - 146096) / 146097);
  const doe = z - era * 146097;
  const yoe = Math.floor(
    (doe - Math.floor(doe / 1460) + Math.floor(doe / 36524) - Math.floor(doe / 146096)) / 365,
  );
  const y = yoe + era * 400;
  const doy = doe - (365 * yoe + Math.floor(yoe / 4) - Math.floor(yoe / 100));
  const mp = Math.floor((5 * doy + 2) / 153);
  const d = doy - Math.floor((153 * mp + 2) / 5) + 1;
  const m = mp + (mp < 10 ? 3 : -9);
  return [y + (m <= 2 ? 1 : 0), m, d];
};

/** 0 = Monday .. 6 = Sunday. 1970-01-01 was a Thursday. */
export const weekdayFromDays = (z: number): number => ((z + 3) % 7 + 7) % 7;

const pad = (n: number, width = 2): string => String(n).padStart(width, "0");

/** Unix seconds -> "2026-09-24 00:00 GMT+1". */
export const fmtGmt1 = (unix: number): string => {
  const shifted = unix + GMT_PLUS_ONE;
  const [y, m, d] = civilFromDays(Math.floor(shifted / DAY));
  const rem = ((shifted % DAY) + DAY) % DAY;
  return `${y}-${pad(m)}-${pad(d)} ${pad(Math.floor(rem / HOUR))}:${pad(
    Math.floor((rem % HOUR) / 60),
  )} GMT+1`;
};

/** Unix seconds -> "24 Sep 2026, 00:00 GMT+1". */
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

export const fmtGmt1Long = (unix: number): string => {
  const shifted = unix + GMT_PLUS_ONE;
  const [y, m, d] = civilFromDays(Math.floor(shifted / DAY));
  const rem = ((shifted % DAY) + DAY) % DAY;
  return `${d} ${MONTHS[m - 1]} ${y}, ${pad(Math.floor(rem / HOUR))}:${pad(
    Math.floor((rem % HOUR) / 60),
  )} GMT+1`;
};

/** GMT+1 day id -> [window_start, window_end] in Unix seconds. */
export const dayWindow = (windowId: string): [number, number] => {
  const [y, m, d] = windowId.split("-").map(Number);
  const start = daysFromCivil(y, m, d) * DAY - GMT_PLUS_ONE;
  return [start, start + DAY];
};

export const weekWindow = (mondayId: string): [number, number] => {
  const [y, m, d] = mondayId.split("-").map(Number);
  const start = daysFromCivil(y, m, d) * DAY - GMT_PLUS_ONE;
  return [start, start + WEEK];
};

export const isMonday = (windowId: string): boolean => {
  const [y, m, d] = windowId.split("-").map(Number);
  if (!y || !m || !d) return false;
  return weekdayFromDays(daysFromCivil(y, m, d)) === 0;
};

export const isValidWindowId = (value: string): boolean => {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const [y, m, d] = value.split("-").map(Number);
  return m >= 1 && m <= 12 && d >= 1 && d <= daysInMonth(y, m);
};

/** The GMT+1 day id `offset` days from now. */
export const gmt1DayId = (offsetDays = 0, now = Math.floor(Date.now() / 1000)): string => {
  const z = Math.floor((now + GMT_PLUS_ONE) / DAY) + offsetDays;
  const [y, m, d] = civilFromDays(z);
  return `${y}-${pad(m)}-${pad(d)}`;
};

/** The next GMT+1 Monday strictly after today. */
export const nextMondayId = (now = Math.floor(Date.now() / 1000)): string => {
  const z = Math.floor((now + GMT_PLUS_ONE) / DAY);
  const ahead = 7 - weekdayFromDays(z);
  const [y, m, d] = civilFromDays(z + (ahead === 0 ? 7 : ahead));
  return `${y}-${pad(m)}-${pad(d)}`;
};

/** Seconds -> "2d 04h 17m 09s", trimmed to the two most significant units. */
export const fmtCountdown = (seconds: number): string => {
  if (seconds <= 0) return "0s";
  const d = Math.floor(seconds / DAY);
  const h = Math.floor((seconds % DAY) / HOUR);
  const m = Math.floor((seconds % HOUR) / 60);
  const s = seconds % 60;
  if (d > 0) return `${d}d ${pad(h)}h`;
  if (h > 0) return `${h}h ${pad(m)}m`;
  if (m > 0) return `${m}m ${pad(s)}s`;
  return `${s}s`;
};

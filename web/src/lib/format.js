export const fmt = (n) => Number(n).toLocaleString("en-US");

export function clampNumber(raw, min, max, fallback, decimals = 0) {
  const n = Number(raw);
  if (raw === null || raw === undefined || raw === "" || !Number.isFinite(n)) return fallback;
  const f = 10 ** decimals;
  return Math.round(Math.min(max, Math.max(min, n)) * f) / f;
}

/** Same ramp as the candidate circle-color expression on the map. */
export function scoreColor(score) {
  const a = [0x93, 0xc5, 0xfd];
  const b = [0x1e, 0x3a, 0x8a];
  const t = Math.min(1, Math.max(0, score));
  return "rgb(" + a.map((v, i) => Math.round(v + (b[i] - v) * t)).join(",") + ")";
}

/** Dark text on light ramp colours, white on dark ones. */
export const scoreTextColor = (score) => (score < 0.45 ? "#0f172a" : "#ffffff");

import { DEFAULT_WEIGHTS, WEIGHTS } from "./constants.js";

// The page shows weights as shares of a 100-point score. The API divides the
// weights by their total before scoring (api/main.py _score_expression), so
// these shares give exactly the same ranking as the raw 0-1 values.

const KEYS = WEIGHTS.map(({ key }) => key);

/**
 * Whole numbers in proportion to `values` that add up to exactly `total`
 * (largest remainder method), so rounded percentages still total 100.
 */
export function apportion(values, total) {
  const sum = values.reduce((a, b) => a + b, 0);
  if (sum <= 0) return values.map(() => 0);
  // Rounded first, so float noise like 28.999999999999996 counts as 29.
  const exact = values.map((v) => Math.round((v / sum) * total * 1e9) / 1e9);
  const whole = exact.map(Math.floor);
  let left = total - whole.reduce((a, b) => a + b, 0);
  const byRemainder = exact.map((v, i) => [v - whole[i], i]).sort((a, b) => b[0] - a[0]);
  for (const [, i] of byRemainder) {
    if (left <= 0) break;
    whole[i] += 1;
    left -= 1;
  }
  return whole;
}

/** Weights scaled to add up to 1, the same way the API scales them. */
export function asShares(weights) {
  const total = KEYS.reduce((sum, key) => sum + (weights[key] || 0), 0);
  if (total <= 0) return { ...DEFAULT_WEIGHTS };
  return Object.fromEntries(KEYS.map((key) => [key, (weights[key] || 0) / total]));
}

/** Each weight as a whole-number percentage; together they're always 100. */
export function percentShares(weights) {
  const whole = apportion(KEYS.map((key) => weights[key] || 0), 100);
  return Object.fromEntries(KEYS.map((key, i) => [key, whole[i]]));
}

/**
 * Sets one factor's share to `percent` and scales the others to fill the
 * rest, keeping their sizes relative to each other. If the others are all 0,
 * the rest is split evenly between them.
 */
export function setShare(weights, key, percent) {
  const share = Math.min(100, Math.max(0, percent)) / 100;
  const others = KEYS.filter((k) => k !== key);
  const othersTotal = others.reduce((sum, k) => sum + (weights[k] || 0), 0);
  const next = { [key]: share };
  for (const k of others) {
    next[k] = othersTotal > 0
      ? ((weights[k] || 0) / othersTotal) * (1 - share)
      : (1 - share) / others.length;
  }
  return next;
}

/**
 * How many of a site's 100 points each factor earned (share x factor score),
 * rounded so the rows add up to its rounded total score.
 */
export function scoreBreakdown(site, weights) {
  const shares = asShares(weights);
  const rows = WEIGHTS.map((w) => {
    const factor = Math.min(1, Math.max(0, Number(site[w.key + "_score"]) || 0));
    return { ...w, factor, share: shares[w.key], raw: shares[w.key] * factor * 100 };
  });
  const total = Math.round(rows.reduce((sum, r) => sum + r.raw, 0));
  const points = apportion(rows.map((r) => r.raw), total);
  return rows.map((r, i) => ({ ...r, points: points[i] }));
}

/**
 * The factors that did the most for this site's score, among the ones where
 * it's actually strong (factor 0.5 or more), best first. At most two.
 */
export function topReasons(rows) {
  return rows
    .filter((r) => r.factor >= 0.5 && r.raw > 0)
    .sort((a, b) => b.raw - a.raw)
    .slice(0, 2);
}

import { API_BASE } from "../config.js";

/** The API isn't there at all (server down, or API_BASE points somewhere else). */
export class ApiUnavailable extends Error {}

export async function apiGet(path, signal) {
  let res;
  try {
    res = await fetch(API_BASE + path, { signal });
  } catch (err) {
    if (err.name === "AbortError") throw err;
    throw new ApiUnavailable("network error");
  }
  let body;
  try {
    body = await res.json();
  } catch {
    // A static file server answers /api/... with an HTML page, not JSON.
    throw new ApiUnavailable(`HTTP ${res.status}, not a JSON response`);
  }
  if (!res.ok) throw new Error(body?.error || `HTTP ${res.status}`);
  return body;
}

// Data that doesn't change while the page is open is fetched once and kept,
// so going Home -> Map -> About -> Map doesn't download it again.
const cache = new Map();
function cached(path) {
  if (!cache.has(path)) {
    const promise = apiGet(path).catch((err) => {
      cache.delete(path); // let the next attempt retry
      throw err;
    });
    cache.set(path, promise);
  }
  return cache.get(path);
}

export const getStates = () => cached("/api/states").then((d) => d.states);
export const getHospitals = () => cached("/api/hospitals");
export const getPopulation = () => cached("/api/population");

export function getOptimize({ weights, radius, k, region }, signal) {
  const q = new URLSearchParams({ radius, k, include_hospitals: 0 });
  for (const [key, value] of Object.entries(weights)) q.set("w_" + key, value);
  if (region) q.set("state", region);
  return apiGet("/api/optimize?" + q, signal);
}

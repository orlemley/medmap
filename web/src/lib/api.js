import { API_BASE } from "../config.js";

export class ApiUnavailable extends Error {}

function errorMessage(body, status) {
  const detail = body?.detail;
  if (typeof detail === "string") return detail;
  if (detail?.message) return detail.message;
  if (Array.isArray(detail)) return detail.map((item) => item.msg).filter(Boolean).join("; ");
  return body?.error || `HTTP ${status}`;
}

async function apiRequest(path, { signal, method = "GET", body } = {}) {
  let res;
  try {
    res = await fetch(API_BASE + path, {
      signal, method,
      headers: body ? { "Content-Type": "application/json" } : undefined,
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch (err) {
    if (err.name === "AbortError") throw err;
    throw new ApiUnavailable("network error");
  }
  let payload;
  try {
    payload = await res.json();
  } catch {
    throw new ApiUnavailable(`HTTP ${res.status}, not a JSON response`);
  }
  if (!res.ok) throw new Error(errorMessage(payload, res.status));
  return payload;
}

export const apiGet = (path, signal) => apiRequest(path, { signal });
export const apiPost = (path, body, signal) => apiRequest(path, { method: "POST", body, signal });

const cache = new Map();
function cached(path) {
  if (!cache.has(path)) {
    const promise = apiGet(path).catch((err) => { cache.delete(path); throw err; });
    cache.set(path, promise);
  }
  return cache.get(path);
}

export const getHealth = () => cached("/api/v1/health");
export const getMeta = () => cached("/api/v1/meta");
export const getStates = () => cached("/api/v1/states").then((d) => d.data);
export const getServices = () => cached("/api/v1/services").then((d) => d.data);

function queryPath(path, params) {
  const q = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === "") continue;
    if (Array.isArray(value)) value.forEach((item) => q.append(key, item));
    else q.set(key, value);
  }
  return q.size ? `${path}?${q}` : path;
}

export const getHospitals = ({ bbox, state, limit = 20000 }, signal) =>
  apiGet(queryPath("/api/v1/map/hospitals", { bbox, state, limit }), signal);
export const getPopulation = ({ bbox, state, limit = 100000 }, signal) =>
  apiGet(queryPath("/api/v1/map/population", { bbox, state, limit }), signal);
export const getCandidateDetail = (siteId, signal) =>
  apiGet(`/api/v1/candidates/${encodeURIComponent(siteId)}`, signal);

export function getOptimize({ weights, region, bbox, limit, filters }, signal) {
  return apiPost("/api/v1/optimize", {
    weights,
    state: region || null,
    bbox: bbox || null,
    limit,
    min_score: filters.minScore || null,
    min_beds: filters.minBeds || null,
    max_beds: filters.maxBeds || null,
    services: filters.services,
    require_all_services: filters.requireAllServices,
    routing_refined: filters.routingRefined === "any" ? null : filters.routingRefined === "refined",
    diversify: filters.diversify,
  }, signal);
}

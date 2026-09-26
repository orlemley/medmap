import * as maplibregl from "https://cdn.jsdelivr.net/npm/maplibre-gl@6.11.2/dist/maplibre-gl.mjs";
import { API_BASE, BASEMAP_STYLE } from "./config.js";

// --- Settings ----------------------------------------------------------------

const DEFAULT_WEIGHTS = { population: 0.4, distance: 0.3, shortage: 0.2, cost: 0.1 };
const WEIGHTS = [
  { key: "population", label: "Population", help: "People with no hospital within the radius" },
  { key: "distance", label: "Distance", help: "Miles closer to care for those people" },
  { key: "shortage", label: "Shortage bonus", help: "Site is in an MUA/P or primary-care HPSA" },
  { key: "cost", label: "Cost", help: "Lower population density = cheaper to build" },
];
const DEFAULT_RADIUS = 30;
const DEFAULT_K = 5;
const RADIUS_MIN = 5;
const RADIUS_MAX = 100;
const K_MIN = 1;
const K_MAX = 25;
const DEBOUNCE_MS = 300;
const US_BOUNDS = [[-125, 24.4], [-66.9, 49.5]];

const HOSPITAL_COLOR = "#dc2626";
const CANDIDATE_LOW = "#93c5fd";
const CANDIDATE_HIGH = "#1e3a8a";

// --- App state ---------------------------------------------------------------

const params = new URLSearchParams(location.search);
const state = {
  weights: Object.fromEntries(
    WEIGHTS.map(({ key }) => [key, clampNumber(params.get("w_" + key), 0, 1, DEFAULT_WEIGHTS[key], 2)])
  ),
  radius: clampNumber(params.get("radius"), RADIUS_MIN, RADIUS_MAX, DEFAULT_RADIUS, 0),
  k: clampNumber(params.get("k"), K_MIN, K_MAX, DEFAULT_K, 0),
  region: (params.get("state") || "").toUpperCase(),
  heatmapMode: "all",
};

let statesByCode = new Map();
let lastCandidates = { type: "FeatureCollection", features: [] };
let lastMeta = null;
let lastSummary = "";
// Resolves once the map sources and layers exist; data can arrive before that.
let resolveLayersReady;
const layersReady = new Promise((resolve) => { resolveLayersReady = resolve; });
let populationLoaded = false;
let optimizeController = null;
let popup = null;
let selected = null; // { source, ids: [] }
const hovered = { hospitals: null, candidates: null };

// --- DOM ---------------------------------------------------------------------

const $ = (id) => document.getElementById(id);
const statusEl = $("status");
const resultsEl = $("results");
const stateSelect = $("state-select");
const radiusRange = $("radius-range");
const radiusInput = $("radius-input");
const radiusOutput = $("radius-output");
const kInput = $("k-input");

// --- Helpers -----------------------------------------------------------------

function clampNumber(raw, min, max, fallback, decimals) {
  const n = Number(raw);
  if (raw === null || raw === "" || !Number.isFinite(n)) return fallback;
  const f = 10 ** decimals;
  return Math.round(Math.min(max, Math.max(min, n)) * f) / f;
}

function debounce(fn, ms) {
  let timer;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), ms);
  };
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[c]);
}

const fmt = (n) => Number(n).toLocaleString("en-US");

function setStatus(html, kind = "", owner = "") {
  statusEl.className = "status" + (kind ? " " + kind : "");
  statusEl.innerHTML = html;
  statusEl.dataset.owner = owner;
}

/** The API isn't there at all (server down, or API_BASE points somewhere else). */
class ApiUnavailable extends Error {}

async function api(path, signal) {
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
    // A static file server answers /api/... with an HTML 404, not JSON.
    throw new ApiUnavailable(`HTTP ${res.status}, not a JSON response`);
  }
  if (!res.ok) throw new Error(body?.error || `HTTP ${res.status}`);
  return body;
}

function apiDownMessage(err) {
  const where = API_BASE || location.origin;
  return `Can't reach the MedMap API at <code>${escapeHtml(where)}/api</code> (${escapeHtml(err.message)}). ` +
    "Start it with <code>python web/api/server.py</code> and open the page from there, " +
    "or set <code>API_BASE</code> in <code>web/js/config.js</code> to where the API runs.";
}

/** Same ramp as the candidate circle-color expression, for the results list. */
function scoreColor(score) {
  const a = [0x93, 0xc5, 0xfd];
  const b = [0x1e, 0x3a, 0x8a];
  const t = Math.min(1, Math.max(0, score));
  return "rgb(" + a.map((v, i) => Math.round(v + (b[i] - v) * t)).join(",") + ")";
}

/** Polygon approximating a circle of radiusMi miles around [lon, lat]. */
function circlePolygon([lon, lat], radiusMi, steps = 64) {
  const R = 3958.8;
  const d = radiusMi / R;
  const lat1 = (lat * Math.PI) / 180;
  const lon1 = (lon * Math.PI) / 180;
  const ring = [];
  for (let i = 0; i <= steps; i++) {
    const brng = (2 * Math.PI * i) / steps;
    const lat2 = Math.asin(Math.sin(lat1) * Math.cos(d) + Math.cos(lat1) * Math.sin(d) * Math.cos(brng));
    const lon2 = lon1 + Math.atan2(
      Math.sin(brng) * Math.sin(d) * Math.cos(lat1),
      Math.cos(d) - Math.sin(lat1) * Math.sin(lat2)
    );
    ring.push([(lon2 * 180) / Math.PI, (lat2 * 180) / Math.PI]);
  }
  return ring;
}

function syncUrl() {
  const p = new URLSearchParams();
  for (const { key } of WEIGHTS) p.set("w_" + key, state.weights[key]);
  p.set("radius", state.radius);
  p.set("k", state.k);
  if (state.region) p.set("state", state.region);
  history.replaceState(null, "", "?" + p.toString());
}

// --- Map ---------------------------------------------------------------------

const map = new maplibregl.Map({
  container: "map",
  style: BASEMAP_STYLE,
  bounds: US_BOUNDS,
  fitBoundsOptions: { padding: 20 },
  attributionControl: { compact: true },
});
map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
map.addControl(new maplibregl.ScaleControl({ unit: "imperial" }), "bottom-right");
window.medmapMap = map; // for poking at the map from the browser console

const EMPTY = { type: "FeatureCollection", features: [] };
const isSelected = ["boolean", ["feature-state", "selected"], false];
const isHovered = ["boolean", ["feature-state", "hover"], false];

function heatmapWeight() {
  // Tract populations are mostly 1k-8k; scale so a typical tract is ~0.5.
  const byPopulation = ["interpolate", ["linear"], ["get", "p"], 0, 0, 8000, 1];
  if (state.heatmapMode === "uncovered") {
    return ["case", [">", ["get", "d"], state.radius], byPopulation, 0];
  }
  return byPopulation;
}

function heatmapIntensity() {
  // Uncovered tracts are sparse, so boost them to stay visible.
  const boost = state.heatmapMode === "uncovered" ? 3 : 1;
  return ["interpolate", ["linear"], ["zoom"], 3, 0.5 * boost, 9, 2 * boost];
}

function addLayers() {
  map.addSource("hospitals", { type: "geojson", data: EMPTY });
  map.addSource("candidates", { type: "geojson", data: EMPTY });
  map.addSource("rings", { type: "geojson", data: EMPTY });
  map.addSource("population", { type: "geojson", data: EMPTY });

  // Keep area layers under the basemap's labels.
  const firstLabel = map.getStyle().layers.find((l) => l.type === "symbol")?.id;

  map.addLayer({
    id: "heatmap",
    type: "heatmap",
    source: "population",
    layout: { visibility: $("layer-heatmap").checked ? "visible" : "none" },
    paint: {
      "heatmap-weight": heatmapWeight(),
      "heatmap-intensity": heatmapIntensity(),
      "heatmap-radius": ["interpolate", ["linear"], ["zoom"], 3, 6, 6, 14, 10, 30],
      // Keep in sync with .ramp-heatmap in css/map.css
      "heatmap-color": [
        "interpolate", ["linear"], ["heatmap-density"],
        0, "rgba(254, 243, 199, 0)",
        0.15, "#fef3c7",
        0.35, "#fde68a",
        0.55, "#fbbf24",
        0.75, "#f59e0b",
        1, "#b45309",
      ],
      "heatmap-opacity": 0.8,
    },
  }, firstLabel);

  map.addLayer({
    id: "rings-fill",
    type: "fill",
    source: "rings",
    paint: { "fill-color": "#2563eb", "fill-opacity": 0.06 },
  }, firstLabel);
  map.addLayer({
    id: "rings-line",
    type: "line",
    source: "rings",
    paint: { "line-color": "#2563eb", "line-width": 1.5, "line-opacity": 0.7, "line-dasharray": [3, 2] },
  }, firstLabel);

  map.addLayer({
    id: "hospitals",
    type: "circle",
    source: "hospitals",
    paint: {
      "circle-color": ["case", isSelected, "#7f1d1d", isHovered, "#f87171", HOSPITAL_COLOR],
      "circle-radius": [
        "interpolate", ["linear"], ["zoom"],
        3, ["case", isSelected, 7, isHovered, 6, 2.5],
        10, ["case", isSelected, 12, isHovered, 10, 7],
      ],
      "circle-stroke-color": ["case", isSelected, "#0f172a", "#ffffff"],
      "circle-stroke-width": ["case", isSelected, 2, 1],
    },
  });

  map.addLayer({
    id: "candidates",
    type: "circle",
    source: "candidates",
    paint: {
      "circle-color": ["interpolate", ["linear"], ["get", "score"], 0, CANDIDATE_LOW, 1, CANDIDATE_HIGH],
      "circle-radius": [
        "+",
        ["interpolate", ["linear"], ["get", "score"], 0, 10, 1, 15],
        ["case", isSelected, 4, isHovered, 3, 0],
      ],
      "circle-stroke-color": ["case", isSelected, "#0f172a", "#ffffff"],
      "circle-stroke-width": ["case", isSelected, 3, 2],
    },
  });
  map.addLayer({
    id: "candidate-labels",
    type: "symbol",
    source: "candidates",
    layout: {
      "text-field": ["to-string", ["get", "rank"]],
      "text-font": ["Noto Sans Bold"],
      "text-size": 12,
      "text-allow-overlap": true,
      "text-ignore-placement": true,
    },
    paint: {
      "text-color": ["case", ["<", ["get", "score"], 0.45], "#0f172a", "#ffffff"],
    },
  });

  applyLayerToggles();
}

function setVisibility(layerIds, visible) {
  for (const id of layerIds) {
    if (map.getLayer(id)) map.setLayoutProperty(id, "visibility", visible ? "visible" : "none");
  }
}

function applyLayerToggles() {
  setVisibility(["hospitals"], $("layer-hospitals").checked);
  setVisibility(["candidates", "candidate-labels"], $("layer-candidates").checked);
  setVisibility(["rings-fill", "rings-line"], $("layer-rings").checked);
  setVisibility(["heatmap"], $("layer-heatmap").checked);
}

// --- Hover and selection (feature-state only; layer paint never changes) -----

function setHover(source, id) {
  if (hovered[source] === id) return;
  if (hovered[source] !== null) map.setFeatureState({ source, id: hovered[source] }, { hover: false });
  hovered[source] = id;
  if (id !== null) map.setFeatureState({ source, id }, { hover: true });
  if (source === "candidates") {
    for (const el of resultsEl.querySelectorAll(".result")) {
      el.classList.toggle("active", id !== null && Number(el.dataset.id) === id);
    }
  }
}

function clearSelection() {
  if (!selected) return;
  for (const id of selected.ids) map.setFeatureState({ source: selected.source, id }, { selected: false });
  selected = null;
}

function select(source, ids) {
  clearSelection();
  selected = { source, ids };
  for (const id of ids) map.setFeatureState({ source, id }, { selected: true });
}

/** Select features and show a popup for them. The popup's close clears the selection. */
function openPopup(source, ids, lngLat, html) {
  // Close the old popup first: its close handler clears the old selection,
  // and would wipe the new one if we selected before removing it.
  popup?.remove();
  select(source, ids);
  const mine = new maplibregl.Popup({ maxWidth: "310px", focusAfterOpen: false })
    .setLngLat(lngLat)
    .setHTML(html)
    .addTo(map);
  popup = mine;
  mine.on("close", () => {
    if (popup !== mine) return;
    clearSelection();
    popup = null;
  });
}

function uniqueById(features) {
  const seen = new Map();
  for (const f of features) if (!seen.has(f.id)) seen.set(f.id, f);
  return [...seen.values()];
}

function wireLayerEvents() {
  for (const source of ["hospitals", "candidates"]) {
    map.on("mouseenter", source, () => {
      map.getCanvas().style.cursor = "pointer";
    });
    map.on("mousemove", source, (e) => {
      // Candidates draw on top; don't hover a hospital hidden underneath one.
      if (source === "hospitals" && candidatesAt(e.point).length) return setHover("hospitals", null);
      setHover(source, e.features[0].id);
    });
    map.on("mouseleave", source, () => {
      map.getCanvas().style.cursor = "";
      setHover(source, null);
    });
  }

  map.on("click", "candidates", (e) => {
    showCandidate(e.features[0].id);
  });

  map.on("click", "hospitals", (e) => {
    if (candidatesAt(e.point).length) return;
    const features = uniqueById(e.features);
    openPopup("hospitals", features.map((f) => f.id), features[0].geometry.coordinates, hospitalPopup(features));
  });
}

function candidatesAt(point) {
  return map.getLayer("candidates") ? map.queryRenderedFeatures(point, { layers: ["candidates"] }) : [];
}

// --- Popups ------------------------------------------------------------------

const LOCATION_NOTES = {
  zcta: "Location is the center of the hospital's ZIP code, not its street address.",
  zip3: "ZIP code not found in census data; shown at the nearest ZIP code's center.",
  county: "ZIP code not found in census data; shown at the county's center.",
};

function hospitalItem(p) {
  const rating = p.rating ? `${escapeHtml(p.rating)} / 5` : "Not rated";
  return `
    <div class="popup-item">
      <h3>${escapeHtml(p.name)}</h3>
      <p class="sub">${escapeHtml(p.type)}</p>
      <dl>
        <dt>Address</dt><dd>${escapeHtml(p.address)}<br>${escapeHtml(p.city)}, ${escapeHtml(p.state)} ${escapeHtml(p.zip)}</dd>
        <dt>Phone</dt><dd>${escapeHtml(p.phone)}</dd>
        <dt>Ownership</dt><dd>${escapeHtml(p.ownership)}</dd>
        <dt>Emergency</dt><dd>${p.emergency ? "Yes" : "No"}</dd>
        <dt>CMS rating</dt><dd>${rating}</dd>
      </dl>
      ${p.counts_for_coverage ? "" : '<p class="caveat">Not counted as existing coverage when scoring sites.</p>'}
      <p class="caveat">${LOCATION_NOTES[p.loc_quality] || ""}</p>
    </div>`;
}

function hospitalPopup(features) {
  const head = features.length > 1
    ? `<p class="sub">${features.length} hospitals share this ZIP code location.</p>`
    : "";
  return `<div class="popup">${head}<div class="popup-list${features.length > 1 ? " multi" : ""}">${features.map((f) => hospitalItem(f.properties)).join("")}</div></div>`;
}

function candidatePopup(p) {
  const weights = lastMeta?.weights || state.weights;
  const total = Object.values(weights).reduce((a, b) => a + b, 0) || 1;
  const rows = WEIGHTS.map(({ key, label }) => {
    const factor = Number(p["f_" + key]);
    const points = (weights[key] * factor) / total;
    return `
      <div class="breakdown-row" title="${escapeHtml(label)}: factor ${factor.toFixed(2)} x weight ${weights[key]}">
        <span>${escapeHtml(label)}</span>
        <span class="breakdown-bar"><span style="width:${(factor * 100).toFixed(0)}%"></span></span>
        <span class="breakdown-value">+${points.toFixed(2)}</span>
      </div>`;
  }).join("");
  const flags = [p.in_mua && "MUA/P", p.in_hpsa && "HPSA"].filter(Boolean).join(", ") || "None";
  return `
    <div class="popup">
      <h3>#${p.rank}: ${escapeHtml(p.county)} County, ${escapeHtml(p.state)}</h3>
      <p class="sub">Census tract ${escapeHtml(p.tract_id)}</p>
      <div class="breakdown">${rows}
        <div class="total"><span>Score</span><span>${Number(p.score).toFixed(2)}</span></div>
      </div>
      <dl>
        <dt>Gain coverage</dt><dd>${fmt(p.uncovered_population)} people</dd>
        <dt>Avg. closer by</dt><dd>${p.avg_distance_reduction_mi} mi</dd>
        <dt>Nearest hospital</dt><dd>${p.nearest_hospital_mi} mi</dd>
        <dt>Shortage areas</dt><dd>${flags}</dd>
        <dt>Density</dt><dd>${fmt(p.density_per_sq_mi)} / sq mi${p.density_imputed ? " (estimated)" : ""}</dd>
        <dt>Tract population</dt><dd>${fmt(p.tract_population)}</dd>
      </dl>
      <p class="caveat">Bars show each factor from 0 to 1. Numbers are its weighted share of the score. Distances are straight-line.</p>
    </div>`;
}

function showCandidate(id, fly = false) {
  const feature = lastCandidates.features.find((f) => f.id === id);
  if (!feature) return;
  const coords = feature.geometry.coordinates;
  // Offset the point below center so the popup (which opens above it) fits on screen.
  if (fly) map.flyTo({ center: coords, zoom: Math.max(map.getZoom(), 7.5), offset: [0, 160], essential: true });
  openPopup("candidates", [id], coords, candidatePopup(feature.properties));
}

// --- Results list --------------------------------------------------------------

function renderResults() {
  resultsEl.replaceChildren();
  for (const f of lastCandidates.features) {
    const p = f.properties;
    const li = document.createElement("li");
    li.innerHTML = `
      <button class="result" type="button" data-id="${f.id}">
        <span class="result-rank" style="background:${scoreColor(p.score)};color:${p.score < 0.45 ? "#0f172a" : "#fff"}">${p.rank}</span>
        <span class="result-name">${escapeHtml(p.county)} County, ${escapeHtml(p.state)}</span>
        <span class="result-score">${Number(p.score).toFixed(2)}</span>
        <span class="result-detail">${fmt(p.uncovered_population)} people gain coverage · ${p.avg_distance_reduction_mi} mi closer</span>
      </button>`;
    const button = li.firstElementChild;
    button.addEventListener("mouseenter", () => setHover("candidates", f.id));
    button.addEventListener("mouseleave", () => setHover("candidates", null));
    button.addEventListener("focus", () => setHover("candidates", f.id));
    button.addEventListener("blur", () => setHover("candidates", null));
    button.addEventListener("click", () => showCandidate(f.id, true));
    resultsEl.append(li);
  }
}

// --- Data loading ------------------------------------------------------------

function updateRings() {
  const features = lastCandidates.features.map((f) => ({
    type: "Feature",
    properties: { rank: f.properties.rank },
    geometry: { type: "Polygon", coordinates: [circlePolygon(f.geometry.coordinates, state.radius)] },
  }));
  map.getSource("rings")?.setData({ type: "FeatureCollection", features });
}

async function runOptimize() {
  syncUrl();
  optimizeController?.abort();
  const controller = new AbortController();
  optimizeController = controller;

  const q = new URLSearchParams({ radius: state.radius, k: state.k, include_hospitals: 0 });
  for (const { key } of WEIGHTS) q.set("w_" + key, state.weights[key]);
  if (state.region) q.set("state", state.region);

  setStatus("Scoring candidate sites…", "busy");
  try {
    const data = await api("/api/optimize?" + q, controller.signal);
    await layersReady; // controls work before the map finishes loading
    if (controller !== optimizeController) return; // a newer request superseded this one

    // Old popups and states refer to the previous result set.
    if (selected?.source === "candidates") popup?.remove();
    setHover("candidates", null);
    map.removeFeatureState({ source: "candidates" });

    lastCandidates = data.candidates;
    lastMeta = data.meta;
    map.getSource("candidates").setData(lastCandidates);
    updateRings();
    renderResults();

    const where = state.region ? statesByCode.get(state.region)?.name || state.region : "the U.S.";
    let msg = `Top ${lastCandidates.features.length} of ${fmt(data.meta.candidates_considered)} tracts in ${escapeHtml(where)} · ${data.meta.compute_ms} ms`;
    if (data.meta.candidates_adding_coverage === 0) {
      msg += `<br>Every tract here already has a hospital within ${state.radius} mi, so only shortage and cost affect these results. Try a smaller radius.`;
    }
    lastSummary = msg;
    setStatus(msg);
  } catch (err) {
    if (err.name === "AbortError") return;
    setStatus(err instanceof ApiUnavailable ? apiDownMessage(err) : "Couldn't score sites: " + escapeHtml(err.message), "error");
  }
}

const runOptimizeSoon = debounce(runOptimize, DEBOUNCE_MS);

async function loadPopulation() {
  if (populationLoaded) return;
  populationLoaded = true;
  setStatus("Loading population for the heatmap…", "busy", "population");
  try {
    const population = await api("/api/population");
    await layersReady;
    map.getSource("population").setData(population);
    // Put the results summary back unless something newer took over the status line.
    if (statusEl.dataset.owner === "population") setStatus(lastSummary || "Heatmap loaded.");
  } catch (err) {
    populationLoaded = false;
    setStatus("Couldn't load heatmap data: " + escapeHtml(err.message), "error");
  }
}

// --- Sidebar controls --------------------------------------------------------

function buildWeightSliders() {
  const container = $("weights");
  for (const { key, label, help } of WEIGHTS) {
    const wrap = document.createElement("div");
    wrap.className = "weight";
    wrap.innerHTML = `
      <label class="field">
        <span>${label} <output id="w-${key}-out"></output></span>
        <input id="w-${key}" type="range" min="0" max="1" step="0.01" aria-describedby="w-${key}-help">
      </label>
      <p class="weight-help" id="w-${key}-help">${help}</p>`;
    container.append(wrap);
    $("w-" + key).addEventListener("input", (e) => {
      state.weights[key] = Number(e.target.value);
      renderWeights();
      runOptimizeSoon();
    });
  }
  renderWeights();
}

function renderWeights() {
  let total = 0;
  for (const { key } of WEIGHTS) {
    const value = state.weights[key];
    $("w-" + key).value = value;
    $(`w-${key}-out`).textContent = value.toFixed(2);
    total += value;
  }
  $("weight-total").textContent = total.toFixed(2);
  $("weight-total").parentElement.parentElement.classList.toggle("off", Math.abs(total - 1) > 0.05);
  $("weight-total").title = "Weights are scaled to total 1 when scoring, so this only needs to be roughly 1.";
}

function setRadius(value, { immediate = false } = {}) {
  state.radius = clampNumber(value, RADIUS_MIN, RADIUS_MAX, state.radius, 0);
  radiusRange.value = state.radius;
  radiusInput.value = state.radius;
  radiusOutput.textContent = `${state.radius} mi`;
  if (map.getLayer("heatmap")) map.setPaintProperty("heatmap", "heatmap-weight", heatmapWeight());
  if (immediate) runOptimize();
  else runOptimizeSoon();
}

function wireControls() {
  buildWeightSliders();

  $("reset-weights").addEventListener("click", () => {
    Object.assign(state.weights, DEFAULT_WEIGHTS);
    renderWeights();
    runOptimize();
  });

  $("normalize-weights").addEventListener("click", () => {
    const total = Object.values(state.weights).reduce((a, b) => a + b, 0);
    if (total <= 0) return;
    for (const { key } of WEIGHTS) state.weights[key] = Math.round((state.weights[key] / total) * 100) / 100;
    renderWeights();
    runOptimize();
  });

  radiusRange.addEventListener("input", () => setRadius(radiusRange.value));
  radiusInput.addEventListener("change", () => setRadius(radiusInput.value, { immediate: true }));
  radiusOutput.textContent = `${state.radius} mi`;
  radiusRange.value = state.radius;
  radiusInput.value = state.radius;

  kInput.value = state.k;
  kInput.addEventListener("change", () => {
    state.k = clampNumber(kInput.value, K_MIN, K_MAX, state.k, 0);
    kInput.value = state.k;
    runOptimize();
  });

  stateSelect.addEventListener("change", () => {
    state.region = stateSelect.value;
    zoomToRegion();
    runOptimize();
  });

  for (const id of ["layer-hospitals", "layer-candidates", "layer-rings"]) {
    $(id).addEventListener("change", () => {
      if (!$(id).checked && popup && selected?.source === (id === "layer-hospitals" ? "hospitals" : "candidates")) {
        popup.remove();
      }
      applyLayerToggles();
    });
  }
  $("layer-heatmap").addEventListener("change", () => {
    if ($("layer-heatmap").checked) loadPopulation();
    applyLayerToggles();
  });
  $("heatmap-mode").addEventListener("change", () => {
    state.heatmapMode = $("heatmap-mode").value;
    $("legend-heatmap-label").textContent =
      state.heatmapMode === "uncovered" ? "Population beyond radius" : "Population";
    if (map.getLayer("heatmap")) map.setPaintProperty("heatmap", "heatmap-weight", heatmapWeight());
    if (map.getLayer("heatmap")) map.setPaintProperty("heatmap", "heatmap-intensity", heatmapIntensity());
    if (!$("layer-heatmap").checked) {
      $("layer-heatmap").checked = true;
      loadPopulation();
      applyLayerToggles();
    }
  });

  $("legend-toggle").addEventListener("click", () => {
    const body = $("legend-body");
    body.hidden = !body.hidden;
    $("legend-toggle").setAttribute("aria-expanded", String(!body.hidden));
  });

  const sidebar = $("sidebar");
  const toggle = $("sidebar-toggle");
  if (matchMedia("(max-width: 800px)").matches) {
    sidebar.classList.add("closed");
    toggle.setAttribute("aria-expanded", "false");
    // The legend covers a lot of a phone screen, so start it collapsed.
    $("legend-body").hidden = true;
    $("legend-toggle").setAttribute("aria-expanded", "false");
  }
  toggle.addEventListener("click", () => {
    const closed = sidebar.classList.toggle("closed");
    toggle.setAttribute("aria-expanded", String(!closed));
  });
}

function buildTypeFilters(hospitals) {
  const counts = new Map();
  for (const f of hospitals.features) counts.set(f.properties.type, (counts.get(f.properties.type) || 0) + 1);
  const types = [...counts.keys()].sort((a, b) => counts.get(b) - counts.get(a));
  const container = $("type-filters");
  container.replaceChildren();
  for (const type of types) {
    const label = document.createElement("label");
    label.className = "check";
    label.innerHTML = `<input type="checkbox" checked> ${escapeHtml(type)} <span class="count">${fmt(counts.get(type))}</span>`;
    label.querySelector("input").dataset.type = type;
    container.append(label);
  }
  const note = document.createElement("p");
  note.className = "weight-help";
  note.textContent = "Hides markers only. Scoring always uses acute-care, critical-access, VA, DoD and rural emergency hospitals.";
  container.append(note);

  container.addEventListener("change", () => {
    const visible = [...container.querySelectorAll("input:checked")].map((el) => el.dataset.type);
    map.setFilter("hospitals", visible.length === types.length
      ? null
      : ["in", ["get", "type"], ["literal", visible]]);
    if (selected?.source === "hospitals") popup?.remove();
  });
}

const STATE_NAMES = {
  AL: "Alabama", AK: "Alaska", AZ: "Arizona", AR: "Arkansas", CA: "California", CO: "Colorado",
  CT: "Connecticut", DE: "Delaware", DC: "District of Columbia", FL: "Florida", GA: "Georgia",
  HI: "Hawaii", ID: "Idaho", IL: "Illinois", IN: "Indiana", IA: "Iowa", KS: "Kansas",
  KY: "Kentucky", LA: "Louisiana", ME: "Maine", MD: "Maryland", MA: "Massachusetts",
  MI: "Michigan", MN: "Minnesota", MS: "Mississippi", MO: "Missouri", MT: "Montana",
  NE: "Nebraska", NV: "Nevada", NH: "New Hampshire", NJ: "New Jersey", NM: "New Mexico",
  NY: "New York", NC: "North Carolina", ND: "North Dakota", OH: "Ohio", OK: "Oklahoma",
  OR: "Oregon", PA: "Pennsylvania", RI: "Rhode Island", SC: "South Carolina", SD: "South Dakota",
  TN: "Tennessee", TX: "Texas", UT: "Utah", VT: "Vermont", VA: "Virginia", WA: "Washington",
  WV: "West Virginia", WI: "Wisconsin", WY: "Wyoming",
};

function buildStateSelect(states) {
  statesByCode = new Map(states.map((s) => [s.state, { ...s, name: STATE_NAMES[s.state] || s.state }]));
  const sorted = [...statesByCode.values()].sort((a, b) => a.name.localeCompare(b.name));
  for (const s of sorted) {
    const opt = document.createElement("option");
    opt.value = s.state;
    opt.textContent = `${s.name} (${fmt(s.hospitals)} hospitals)`;
    stateSelect.append(opt);
  }
  if (!statesByCode.has(state.region)) state.region = "";
  stateSelect.value = state.region;
}

function zoomToRegion() {
  const s = statesByCode.get(state.region);
  if (s) {
    const [w, south, e, n] = s.bbox;
    map.fitBounds([[w, south], [e, n]], { padding: 40, maxZoom: 9 });
  } else {
    map.fitBounds(US_BOUNDS, { padding: 20 });
  }
}

// --- Startup -----------------------------------------------------------------

wireControls();

const mapReady = new Promise((resolve) => map.on("load", resolve));

(async () => {
  try {
    const [states, hospitals] = await Promise.all([api("/api/states"), api("/api/hospitals")]);
    buildStateSelect(states.states);
    await mapReady;
    addLayers();
    wireLayerEvents();
    resolveLayersReady();
    map.getSource("hospitals").setData(hospitals);
    buildTypeFilters(hospitals);
    if (state.region) zoomToRegion();
    if ($("layer-heatmap").checked) loadPopulation();
    runOptimize();
  } catch (err) {
    setStatus(err instanceof ApiUnavailable ? apiDownMessage(err) : "Couldn't load map data: " + escapeHtml(err.message), "error");
  }
})();

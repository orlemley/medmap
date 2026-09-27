import { useEffect, useMemo, useRef, useState } from "react";
import { API_BASE } from "../config.js";
import Legend from "../components/map/Legend.jsx";
import SitesPanel from "../components/map/SitesPanel.jsx";
import MedMap from "../components/map/MedMap.jsx";
import { CandidatePopup, HospitalPopup } from "../components/map/Popups.jsx";
import CandidateDetail from "../components/sidebar/CandidateDetail.jsx";
import {
  HospitalTypeFilter, LayerToggles, ModelFilters, Panel, RegionSelect,
  ServiceFilters, StatusBar, TextSizeControl, WeightSliders,
} from "../components/sidebar/Controls.jsx";
import { useDebouncedValue } from "../hooks/useDebouncedValue.js";
import { useOptimize } from "../hooks/useOptimize.js";
import { ApiUnavailable, getCandidateDetail, getHospitals, getMeta, getPopulation, getServices, getStates } from "../lib/api.js";
import { DEBOUNCE_MS, DEFAULT_FILTERS, DEFAULT_WEIGHTS, EMPTY_FC, RESULTS, STATE_NAMES, TEXT_SCALES, US_BOUNDS, WEIGHTS } from "../lib/constants.js";
import { clampNumber, fmt } from "../lib/format.js";
import { useTheme } from "../theme.jsx";

function readUrl(params) {
  const weights = Object.fromEntries(WEIGHTS.map(({ key }) => [key,
    clampNumber(params.get("w_" + key), 0, 1, DEFAULT_WEIGHTS[key], 3)]));
  const services = (params.get("services") || "").split(",").filter(Boolean);
  return {
    weights,
    region: (params.get("state") || "").toUpperCase(),
    limit: clampNumber(params.get("limit"), RESULTS.min, RESULTS.max, RESULTS.default),
    filters: {
      ...DEFAULT_FILTERS, services,
      requireAllServices: params.get("all_services") === "1",
      minBeds: clampNumber(params.get("min_beds"), 0, 2000, 0),
      maxBeds: clampNumber(params.get("max_beds"), 0, 2000, 0),
      minScore: clampNumber(params.get("min_score"), 0, 1, 0, 2),
      routingRefined: ["refined", "estimated"].includes(params.get("routing")) ? params.get("routing") : "any",
      diversify: params.get("diversify") !== "0",
    },
  };
}

function shareQuery({ weights, region, limit, filters }) {
  const q = new URLSearchParams();
  WEIGHTS.forEach(({ key }) => q.set("w_" + key, weights[key]));
  if (region) q.set("state", region);
  q.set("limit", limit);
  if (filters.services.length) q.set("services", filters.services.join(","));
  if (filters.requireAllServices) q.set("all_services", "1");
  if (filters.minBeds) q.set("min_beds", filters.minBeds);
  if (filters.maxBeds) q.set("max_beds", filters.maxBeds);
  if (filters.minScore) q.set("min_score", filters.minScore);
  if (filters.routingRefined !== "any") q.set("routing", filters.routingRefined);
  if (!filters.diversify) q.set("diversify", "0");
  return q.toString();
}

function ApiHelp({ error }) {
  return <>Can't reach the Stage 8 API at <code>{API_BASE || window.location.origin}/api/v1</code> ({error.message}).</>;
}

const isPhone = () => window.matchMedia("(max-width: 800px)").matches;

// Map style (satellite or street map) and heatmap on/off, remembered per
// browser. First-time visitors get satellite photos with the heatmap on.
const MAP_VIEW_KEY = "medmap-map-view";
const DEFAULT_MAP_VIEW = { basemap: "satellite", heatmap: true };
function readMapView() {
  try {
    const saved = JSON.parse(localStorage.getItem(MAP_VIEW_KEY));
    return {
      basemap: saved?.basemap === "streets" || saved?.basemap === "satellite" ? saved.basemap : DEFAULT_MAP_VIEW.basemap,
      heatmap: typeof saved?.heatmap === "boolean" ? saved.heatmap : DEFAULT_MAP_VIEW.heatmap,
    };
  } catch {
    return DEFAULT_MAP_VIEW;
  }
}

// Text size for the sidebar, legend and popups, remembered per browser.
const TEXT_SCALE_KEY = "medmap-text-scale";
function readTextScale() {
  try { const n = Number(localStorage.getItem(TEXT_SCALE_KEY)); return TEXT_SCALES.includes(n) ? n : 1; }
  catch { return 1; }
}

export default function MapPage() {
  const initial = useMemo(() => readUrl(new URLSearchParams(window.location.search)), []);
  const [weights, setWeights] = useState(initial.weights);
  const [region, setRegion] = useState(initial.region);
  const [limit, setLimit] = useState(initial.limit);
  const [filters, setFilters] = useState(initial.filters);
  const [viewport, setViewport] = useState(null);
  const [initialView] = useState(readMapView);
  const [layers, setLayers] = useState({ hospitals: true, candidates: true, rings: false, heatmap: initialView.heatmap });
  const [heatmapMode, setHeatmapMode] = useState("all");
  const [hiddenTypes, setHiddenTypes] = useState(() => new Set());
  const [sidebarOpen, setSidebarOpen] = useState(() => !isPhone());
  const [basemap, setBasemap] = useState(initialView.basemap);
  const [textScale, setTextScale] = useState(readTextScale);
  const { theme } = useTheme();

  const [lookups, setLookups] = useState({ states: [], services: [], meta: null, error: null });
  const [hospitals, setHospitals] = useState(EMPTY_FC);
  const [population, setPopulation] = useState(EMPTY_FC);
  const [layerLoad, setLayerLoad] = useState({ hospitals: "idle", population: "idle", error: null });

  // Remember the map style and heatmap for next time.
  useEffect(() => {
    try {
      localStorage.setItem(MAP_VIEW_KEY, JSON.stringify({ basemap, heatmap: layers.heatmap }));
    } catch {
      // not saved; still works for this visit
    }
  }, [basemap, layers.heatmap]);

  // Step from the latest size (not this render's), so quick repeated clicks all count.
  const changeTextScale = (step) =>
    setTextScale((current) => {
      const i = TEXT_SCALES.indexOf(current) + step;
      return i < 0 || i >= TEXT_SCALES.length ? current : TEXT_SCALES[i];
    });
  useEffect(() => {
    try {
      localStorage.setItem(TEXT_SCALE_KEY, String(textScale));
    } catch {
      // still applies for this visit
    }
  }, [textScale]);
  const [hoveredCandidate, setHoveredCandidate] = useState(null);
  const [popup, setPopup] = useState(null);
  const [detail, setDetail] = useState({ siteId: null, status: "idle", data: null, error: null });
  const popupCounter = useRef(0);
  const mapApi = useRef(null);

  useEffect(() => {
    let alive = true;
    Promise.all([getStates(), getServices(), getMeta()])
      .then(([states, services, meta]) => alive && setLookups({ states, services, meta, error: null }))
      .catch((error) => alive && setLookups((s) => ({ ...s, error })));
    return () => { alive = false; };
  }, []);

  useEffect(() => {
    if (lookups.states.length && region && !lookups.states.some((s) => s.state === region)) setRegion("");
  }, [lookups.states, region]);

  const queryState = useMemo(() => ({ weights, region, limit, filters }), [weights, region, limit, filters]);
  const share = shareQuery(queryState);
  const debouncedShare = useDebouncedValue(share, DEBOUNCE_MS);
  const debouncedViewport = useDebouncedValue(viewport, DEBOUNCE_MS);
  const debouncedState = useMemo(() => readUrl(new URLSearchParams(debouncedShare)), [debouncedShare]);
  const optimizeParams = useMemo(() => ({ ...debouncedState, bbox: debouncedViewport?.bbox || null }), [debouncedState, debouncedViewport]);
  const optimize = useOptimize(optimizeParams);

  useEffect(() => {
    if (debouncedShare !== window.location.search.slice(1)) history.replaceState(null, "", `${location.pathname}?${debouncedShare}`);
  }, [debouncedShare]);

  useEffect(() => {
    if (!debouncedViewport?.bbox && !region) return;
    const controller = new AbortController();
    setLayerLoad((s) => ({ ...s, hospitals: "loading", error: null }));
    getHospitals({ bbox: debouncedViewport?.bbox, state: region }, controller.signal)
      .then((data) => { setHospitals(data); setLayerLoad((s) => ({ ...s, hospitals: "ok" })); })
      .catch((error) => { if (error.name !== "AbortError") setLayerLoad((s) => ({ ...s, hospitals: "error", error })); });
    return () => controller.abort();
  }, [debouncedViewport, region]);

  useEffect(() => {
    if (!layers.heatmap || (!debouncedViewport?.bbox && !region)) return;
    const controller = new AbortController();
    setLayerLoad((s) => ({ ...s, population: "loading", error: null }));
    getPopulation({ bbox: debouncedViewport?.bbox, state: region }, controller.signal)
      .then((data) => { setPopulation(data); setLayerLoad((s) => ({ ...s, population: "ok" })); })
      .catch((error) => { if (error.name !== "AbortError") setLayerLoad((s) => ({ ...s, population: "error", error })); });
    return () => controller.abort();
  }, [layers.heatmap, debouncedViewport, region]);

  useEffect(() => { setPopup((p) => p?.kind === "candidate" ? null : p); setHoveredCandidate(null); }, [optimize.candidates]);

  useEffect(() => {
    if (!detail.siteId) return;
    const controller = new AbortController();
    setDetail((s) => ({ ...s, status: "loading", data: null, error: null }));
    getCandidateDetail(detail.siteId, controller.signal)
      .then((data) => setDetail((s) => ({ ...s, status: "ok", data })))
      .catch((error) => { if (error.name !== "AbortError") setDetail((s) => ({ ...s, status: "error", error })); });
    return () => controller.abort();
  }, [detail.siteId]);

  const regionInfo = lookups.states.find((x) => x.state === region);
  const homeView = useMemo(() => regionInfo
    ? { bounds: [[regionInfo.bbox[0], regionInfo.bbox[1]], [regionInfo.bbox[2], regionInfo.bbox[3]]], padding: 40, maxZoom: 9, label: STATE_NAMES[region] || region }
    : { bounds: US_BOUNDS, padding: 20, label: "the U.S." }, [regionInfo, region]);

  const nextKey = () => ++popupCounter.current;
  const showHospitals = (list, lngLat) => setPopup({ key: nextKey(), kind: "hospitals", source: "hospitals", ids: list.map((h) => h.id), hospitals: list, lngLat });
  const showCandidate = (id, fly) => {
    const feature = optimize.candidates.features.find((f) => String(f.id) === String(id));
    if (!feature) return;
    if (fly) mapApi.current?.focusOn(feature.geometry.coordinates);
    setPopup({ key: nextKey(), kind: "candidate", source: "candidates", ids: [feature.id], lngLat: feature.geometry.coordinates });
    setDetail({ siteId: String(feature.id), status: "loading", data: null, error: null });
  };

  const normalizeWeights = () => {
    const total = Object.values(weights).reduce((a, b) => a + b, 0);
    if (total > 0) setWeights(Object.fromEntries(Object.entries(weights).map(([key, v]) => [key, Math.round(v / total * 1000) / 1000])));
  };
  const changeFilter = (key, value) => setFilters((current) => ({ ...current, [key]: value }));
  const toggleService = (id) => setFilters((current) => ({ ...current, services: current.services.includes(id) ? current.services.filter((x) => x !== id) : [...current.services, id] }));
  const toggleLayer = (key) => setLayers((current) => ({ ...current, [key]: !current[key] }));
  const toggleType = (type) => setHiddenTypes((current) => { const next = new Set(current); next.has(type) ? next.delete(type) : next.add(type); return next; });

  const allTypes = useMemo(() => [...new Set(hospitals.features.map((f) => f.properties.type).filter(Boolean))], [hospitals]);
  const visibleTypes = useMemo(() => hiddenTypes.size ? allTypes.filter((t) => !hiddenTypes.has(t)) : null, [allTypes, hiddenTypes]);
  const selected = popup ? { source: popup.source, ids: popup.ids } : null;
  const usedWeights = optimize.meta?.weights ?? weights;
  const popupView = useMemo(() => {
    if (!popup) return null;
    if (popup.kind === "hospitals") return { key: popup.key, lngLat: popup.lngLat, content: <HospitalPopup hospitals={popup.hospitals} /> };
    const feature = optimize.candidates.features.find((f) => String(f.id) === String(popup.ids[0]));
    return feature ? { key: popup.key, lngLat: popup.lngLat, content: <CandidatePopup site={feature.properties} weights={usedWeights} /> } : null;
  }, [popup, optimize.candidates, usedWeights]);

  let status;
  const error = lookups.error || layerLoad.error || optimize.error;
  if (error) status = { kind: "error", text: error instanceof ApiUnavailable ? <ApiHelp error={error} /> : error.message };
  else if (share !== debouncedShare || optimize.status === "loading") status = { kind: "busy", text: "Ranking Stage 8 candidate sites…" };
  else status = { kind: "", text: <>{optimize.candidates.features.length} candidates shown{region ? ` in ${STATE_NAMES[region] || region}` : " in this view"} · {optimize.meta?.compute_ms ?? "—"} ms<br /><small>Stage 8 run {lookups.meta?.dataset_run_id || "loading"}</small></> };

  return (
    <div className="map-layout" style={{ "--text-scale": textScale }}>
      <title>MedMap: Stage 8 map</title>
      <div className="map-wrap">
        <MedMap ref={mapApi} hospitals={hospitals} population={population} candidates={optimize.candidates}
          ringRadius={0} radius={30} layers={layers} heatmapMode={heatmapMode} hospitalTypes={visibleTypes}
          homeView={homeView} theme={theme} basemap={basemap} selected={selected} hoveredCandidate={hoveredCandidate}
          popup={popupView} onViewportChange={setViewport} onHospitalsClick={showHospitals}
          onCandidateClick={(id) => showCandidate(id, false)} onCandidateHover={setHoveredCandidate}
          onPopupClose={(key) => setPopup((p) => p?.key === key ? null : p)} />
        <div className="map-toolbar">
          <div className="segmented" role="group" aria-label="Map style">
            {[["streets", "Map"], ["satellite", "Satellite"]].map(([value, label]) => <button key={value} className="map-button" type="button" data-basemap={value} aria-pressed={basemap === value} onClick={() => setBasemap(value)}>{label}</button>)}
          </div>
          <button className="map-button heatmap-button" type="button" aria-pressed={layers.heatmap} onClick={() => toggleLayer("heatmap")}><span className="heatmap-dot" aria-hidden="true" /> Heatmap</button>
        </div>
        {/* Top-left: the phone-only Controls button, then the recommended sites */}
        <div className="map-topleft">
          <button
            className="map-button sidebar-toggle"
            id="sidebar-toggle"
            type="button"
            aria-controls="sidebar"
            aria-expanded={sidebarOpen}
            onClick={() => setSidebarOpen((o) => !o)}
          >
            Controls
          </button>
          <SitesPanel
            theme={theme}
            candidates={optimize.candidates}
            busy={share !== debouncedShare || optimize.status === "loading"}
            activeId={hoveredCandidate}
            onHover={setHoveredCandidate}
            onSelect={(id) => showCandidate(id, true)}
          />
        </div>
        <Legend heatmapMode={heatmapMode} basemap={basemap} />
      </div>

      <aside className={sidebarOpen ? "sidebar" : "sidebar closed"} id="sidebar" aria-label="Controls">
        <div className="sidebar-top"><TextSizeControl scale={textScale} canSmaller={textScale > TEXT_SCALES[0]} canLarger={textScale < TEXT_SCALES.at(-1)} onSmaller={() => changeTextScale(-1)} onLarger={() => changeTextScale(1)} /><button className="link-button sidebar-close" type="button" onClick={() => setSidebarOpen(false)}>Close</button></div>
        <StatusBar kind={status.kind}>{status.text}</StatusBar>
        <Panel title="Region"><RegionSelect states={lookups.states} value={region} onChange={setRegion} /></Panel>
        <Panel title="Model weights" action={<button className="link-button" type="button" onClick={() => setWeights(DEFAULT_WEIGHTS)}>Reset</button>}><WeightSliders weights={weights} onChange={(key, value) => setWeights((w) => ({ ...w, [key]: value }))} onNormalize={normalizeWeights} /></Panel>
        <Panel title="Services"><ServiceFilters services={lookups.services} selected={filters.services} requireAll={filters.requireAllServices} onToggle={toggleService} onRequireAll={(v) => changeFilter("requireAllServices", v)} /></Panel>
        <Panel title="Site filters"><ModelFilters filters={filters} onChange={changeFilter} limit={limit} onLimit={setLimit} /></Panel>
        <CandidateDetail state={detail} onClose={() => setDetail({ siteId: null, status: "idle", data: null, error: null })} />
        <Panel title="Layers"><LayerToggles layers={layers} onToggle={toggleLayer} heatmapMode={heatmapMode} onHeatmapMode={(mode) => { setHeatmapMode(mode); setLayers((l) => ({ ...l, heatmap: true })); }} /></Panel>
        <Panel title="Hospital types"><HospitalTypeFilter hospitals={hospitals} hiddenTypes={hiddenTypes} onToggle={toggleType} /></Panel>
      </aside>
    </div>
  );
}

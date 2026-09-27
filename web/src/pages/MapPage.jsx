import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router";
import { API_BASE } from "../config.js";
import Legend from "../components/map/Legend.jsx";
import SitesPanel from "../components/map/SitesPanel.jsx";
import MedMap from "../components/map/MedMap.jsx";
import { CandidatePopup, HospitalPopup } from "../components/map/Popups.jsx";
import {
  HospitalTypeFilter,
  LayerToggles,
  NumberField,
  Panel,
  RegionSelect,
  StatusBar,
  TextSizeControl,
  WeightSliders,
} from "../components/sidebar/Controls.jsx";
import { useDebouncedValue } from "../hooks/useDebouncedValue.js";
import { useOptimize } from "../hooks/useOptimize.js";
import { ApiUnavailable, getHospitals, getPopulation, getStates } from "../lib/api.js";
import { DEBOUNCE_MS, DEFAULT_WEIGHTS, RADIUS, SITES, STATE_NAMES, TEXT_SCALES, US_BOUNDS, WEIGHTS } from "../lib/constants.js";
import { clampNumber, fmt } from "../lib/format.js";
import { useTheme } from "../theme.jsx";

/** Settings come from the URL, so a copied link reproduces the view. */
function readUrl(searchParams) {
  return {
    weights: Object.fromEntries(
      WEIGHTS.map(({ key }) => [key, clampNumber(searchParams.get("w_" + key), 0, 1, DEFAULT_WEIGHTS[key], 2)])
    ),
    radius: clampNumber(searchParams.get("radius"), RADIUS.min, RADIUS.max, RADIUS.default),
    k: clampNumber(searchParams.get("k"), SITES.min, SITES.max, SITES.default),
    region: (searchParams.get("state") || "").toUpperCase(),
  };
}

function toQuery({ weights, radius, k, region }) {
  const q = new URLSearchParams();
  for (const { key } of WEIGHTS) q.set("w_" + key, weights[key]);
  q.set("radius", radius);
  q.set("k", k);
  if (region) q.set("state", region);
  return q.toString();
}

function ApiHelp({ error }) {
  return (
    <>
      Can't reach the MedMap API at <code>{API_BASE || window.location.origin}/api</code> ({error.message}).
      Start it with <code>python web/api/server.py</code> (or double-click <code>web/start.cmd</code>) and open
      the address it prints.
    </>
  );
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
  try {
    const value = Number(localStorage.getItem(TEXT_SCALE_KEY));
    return TEXT_SCALES.includes(value) ? value : 1;
  } catch {
    return 1;
  }
}

export default function MapPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [initial] = useState(() => readUrl(searchParams));

  // --- What the user controls
  const [weights, setWeights] = useState(initial.weights);
  const [radius, setRadius] = useState(initial.radius);
  const [k, setK] = useState(initial.k);
  const [region, setRegion] = useState(initial.region);
  const [initialView] = useState(readMapView);
  const [layers, setLayers] = useState({ hospitals: true, candidates: true, rings: true, heatmap: initialView.heatmap });
  const [heatmapMode, setHeatmapMode] = useState("all");
  const [hiddenTypes, setHiddenTypes] = useState(() => new Set());
  const [sidebarOpen, setSidebarOpen] = useState(() => !isPhone());
  const [basemap, setBasemap] = useState(initialView.basemap); // "satellite" or "streets"
  const [textScale, setTextScale] = useState(readTextScale);
  const { theme } = useTheme();

  // Remember the map style and heatmap for next time.
  useEffect(() => {
    try {
      localStorage.setItem(MAP_VIEW_KEY, JSON.stringify({ basemap, heatmap: layers.heatmap }));
    } catch {
      // not saved; still works for this visit
    }
  }, [basemap, layers.heatmap]);

  const changeTextScale = (step) => {
    const i = TEXT_SCALES.indexOf(textScale) + step;
    if (i < 0 || i >= TEXT_SCALES.length) return;
    setTextScale(TEXT_SCALES[i]);
    try {
      localStorage.setItem(TEXT_SCALE_KEY, String(TEXT_SCALES[i]));
    } catch {
      // still applies for this visit
    }
  };

  // --- Data from the API
  const [states, setStates] = useState([]);
  const [hospitals, setHospitals] = useState(null);
  const [loadError, setLoadError] = useState(null);
  const [population, setPopulation] = useState(null);
  const [populationLoad, setPopulationLoad] = useState({ status: "idle", error: null });

  // --- Map interaction
  const [hoveredCandidate, setHoveredCandidate] = useState(null);
  const [popup, setPopup] = useState(null); // { key, kind, source, ids, lngLat, hospitals? }
  const popupCounter = useRef(0);
  const mapApi = useRef(null);

  useEffect(() => {
    let alive = true;
    Promise.all([getStates(), getHospitals()])
      .then(([s, h]) => {
        if (!alive) return;
        setStates(s);
        setHospitals(h);
      })
      .catch((err) => alive && setLoadError(err));
    return () => {
      alive = false;
    };
  }, []);

  // A state code from an old or hand-edited link that the data doesn't have.
  useEffect(() => {
    if (states.length && region && !states.some((s) => s.state === region)) setRegion("");
  }, [states, region]);

  // --- Scoring: debounced, so dragging a slider sends one request, not dozens.
  // The settings are compared as a query string, so equal settings are always
  // "unchanged" (objects would differ by identity and trigger extra requests).
  const query = toQuery({ weights, radius, k, region });
  const debouncedQuery = useDebouncedValue(query, DEBOUNCE_MS);
  const debounced = useMemo(() => readUrl(new URLSearchParams(debouncedQuery)), [debouncedQuery]);
  const optimize = useOptimize(debounced);

  // Keep the address bar in sync so the current view can be shared as a link.
  const setSearchRef = useRef(setSearchParams);
  useLayoutEffect(() => {
    setSearchRef.current = setSearchParams;
  });
  useEffect(() => {
    if (debouncedQuery !== window.location.search.slice(1)) setSearchRef.current(debouncedQuery, { replace: true });
  }, [debouncedQuery]);

  // New results: old popups and hover refer to sites that may be gone.
  useEffect(() => {
    setPopup((p) => (p?.kind === "candidate" ? null : p));
    setHoveredCandidate(null);
  }, [optimize.candidates]);

  // The map's starting view: the chosen state, or the lower 48. The map flies
  // there when this changes, and its Reset view button returns here.
  const regionInfo = states.find((x) => x.state === region);
  const homeView = useMemo(() => {
    if (!regionInfo) return { bounds: US_BOUNDS, padding: 20, label: "the U.S." };
    const [w, south, e, n] = regionInfo.bbox;
    return { bounds: [[w, south], [e, n]], padding: 40, maxZoom: 9, label: STATE_NAMES[regionInfo.state] || regionInfo.state };
  }, [regionInfo]);

  // Population is ~1 MB, so only fetch it the first time the heatmap is shown.
  useEffect(() => {
    if (!layers.heatmap || populationLoad.status !== "idle") return;
    setPopulationLoad({ status: "loading", error: null });
    getPopulation()
      .then((p) => {
        setPopulation(p);
        setPopulationLoad({ status: "ok", error: null });
      })
      .catch((error) => setPopulationLoad({ status: "error", error }));
  }, [layers.heatmap, populationLoad.status]);

  // Close a popup whose markers were just hidden.
  useEffect(() => {
    setPopup((p) => {
      if (p?.kind === "hospitals" && (!layers.hospitals || p.hospitals.some((h) => hiddenTypes.has(h.type)))) return null;
      if (p?.kind === "candidate" && !layers.candidates) return null;
      return p;
    });
  }, [layers, hiddenTypes]);

  // --- Handlers
  const nextKey = () => ++popupCounter.current;

  const showHospitals = (list, lngLat) =>
    setPopup({ key: nextKey(), kind: "hospitals", source: "hospitals", ids: list.map((h) => h.id), hospitals: list, lngLat });

  const showCandidate = (id, fly) => {
    const feature = optimize.candidates.features.find((f) => f.id === id);
    if (!feature) return;
    const lngLat = feature.geometry.coordinates;
    if (fly) mapApi.current?.focusOn(lngLat);
    setPopup({ key: nextKey(), kind: "candidate", source: "candidates", ids: [id], lngLat });
  };

  // Ignore a close from a popup that has already been replaced by a newer one.
  const closePopup = (key) => setPopup((p) => (p && p.key === key ? null : p));

  const toggleLayer = (key) => {
    setLayers((l) => ({ ...l, [key]: !l[key] }));
    if (key === "heatmap" && populationLoad.status === "error") setPopulationLoad({ status: "idle", error: null });
  };

  const normalizeWeights = () => {
    const total = Object.values(weights).reduce((a, b) => a + b, 0);
    if (total <= 0) return;
    setWeights(Object.fromEntries(Object.entries(weights).map(([key, v]) => [key, Math.round((v / total) * 100) / 100])));
  };

  const toggleType = (type) =>
    setHiddenTypes((prev) => {
      const next = new Set(prev);
      if (next.has(type)) next.delete(type);
      else next.add(type);
      return next;
    });

  // --- Derived values for the map
  const selected = useMemo(() => (popup ? { source: popup.source, ids: popup.ids } : null), [popup]);

  const allTypes = useMemo(() => [...new Set(hospitals?.features.map((f) => f.properties.type))], [hospitals]);
  const visibleTypes = useMemo(
    () => (hiddenTypes.size ? allTypes.filter((t) => !hiddenTypes.has(t)) : null),
    [allTypes, hiddenTypes]
  );

  const usedWeights = optimize.meta?.weights ?? weights;
  const popupView = useMemo(() => {
    if (!popup) return null;
    if (popup.kind === "hospitals") {
      return { key: popup.key, lngLat: popup.lngLat, content: <HospitalPopup hospitals={popup.hospitals} /> };
    }
    const feature = optimize.candidates.features.find((f) => f.id === popup.ids[0]);
    if (!feature) return null;
    return {
      key: popup.key,
      lngLat: popup.lngLat,
      content: <CandidatePopup site={feature.properties} weights={usedWeights} />,
    };
  }, [popup, optimize.candidates, usedWeights]);

  // --- Status line
  let status;
  if (loadError) {
    status = { kind: "error", text: loadError instanceof ApiUnavailable ? <ApiHelp error={loadError} /> : `Couldn't load map data: ${loadError.message}` };
  } else if (query !== debouncedQuery || optimize.status === "loading") {
    status = { kind: "busy", text: "Scoring candidate sites…" };
  } else if (optimize.status === "error") {
    status = {
      kind: "error",
      text: optimize.error instanceof ApiUnavailable ? <ApiHelp error={optimize.error} /> : `Couldn't score sites: ${optimize.error.message}`,
    };
  } else if (populationLoad.status === "loading") {
    status = { kind: "busy", text: "Loading population for the heatmap…" };
  } else if (populationLoad.status === "error") {
    status = { kind: "error", text: `Couldn't load heatmap data: ${populationLoad.error.message}` };
  } else if (optimize.meta) {
    const m = optimize.meta;
    const where = m.state ? STATE_NAMES[m.state] || m.state : "the U.S.";
    status = {
      kind: "",
      text: (
        <>
          Top {optimize.candidates.features.length} of {fmt(m.candidates_considered)} tracts in {where} · {m.compute_ms} ms
          {m.candidates_adding_coverage === 0 && (
            <>
              <br />
              Every tract here already has a hospital within {m.radius_mi} mi, so only shortage and cost affect these
              results. Try a smaller radius.
            </>
          )}
        </>
      ),
    };
  } else {
    status = { kind: "busy", text: "Loading…" };
  }

  return (
    // --text-scale sizes the sidebar, legend and popup text (styles/map.css).
    <div className="map-layout" style={{ "--text-scale": textScale }}>
      <title>MedMap: Map</title>
      <div className="map-wrap">
        <MedMap
          ref={mapApi}
          hospitals={hospitals}
          population={population}
          candidates={optimize.candidates}
          ringRadius={optimize.meta?.radius_mi ?? radius}
          radius={radius}
          layers={layers}
          heatmapMode={heatmapMode}
          hospitalTypes={visibleTypes}
          homeView={homeView}
          theme={theme}
          basemap={basemap}
          selected={selected}
          hoveredCandidate={hoveredCandidate}
          popup={popupView}
          onHospitalsClick={showHospitals}
          onCandidateClick={(id) => showCandidate(id, false)}
          onCandidateHover={setHoveredCandidate}
          onPopupClose={closePopup}
        />
        {/* Top-right toolbar, as on the whiteboard sketch */}
        <div className="map-toolbar">
          <div className="segmented" role="group" aria-label="Map style">
            {[["streets", "Map"], ["satellite", "Satellite"]].map(([value, label]) => (
              <button
                key={value}
                className="map-button"
                type="button"
                data-basemap={value}
                aria-pressed={basemap === value}
                onClick={() => setBasemap(value)}
              >
                {label}
              </button>
            ))}
          </div>
          <button
            className="map-button heatmap-button"
            type="button"
            aria-pressed={layers.heatmap}
            onClick={() => toggleLayer("heatmap")}
          >
            <span className="heatmap-dot" aria-hidden="true" /> Heatmap
          </button>
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
            busy={query !== debouncedQuery || optimize.status === "loading"}
            activeId={hoveredCandidate}
            onHover={setHoveredCandidate}
            onSelect={(id) => showCandidate(id, true)}
          />
        </div>
        <Legend heatmapMode={heatmapMode} basemap={basemap} />
      </div>

      <aside className={sidebarOpen ? "sidebar" : "sidebar closed"} id="sidebar" aria-label="Controls">
        <div className="sidebar-top">
          <TextSizeControl
            scale={textScale}
            canSmaller={textScale > TEXT_SCALES[0]}
            canLarger={textScale < TEXT_SCALES[TEXT_SCALES.length - 1]}
            onSmaller={() => changeTextScale(-1)}
            onLarger={() => changeTextScale(1)}
          />
          <button className="link-button sidebar-close" type="button" onClick={() => setSidebarOpen(false)}>
            Close
          </button>
        </div>
        <StatusBar kind={status.kind}>{status.text}</StatusBar>

        <Panel title="Region">
          <RegionSelect states={states} value={region} onChange={setRegion} />
        </Panel>

        <Panel
          title="Weights"
          action={
            <button className="link-button" id="reset-weights" type="button" onClick={() => setWeights(DEFAULT_WEIGHTS)}>
              Reset
            </button>
          }
        >
          <WeightSliders
            weights={weights}
            onChange={(key, value) => setWeights((w) => ({ ...w, [key]: value }))}
            onNormalize={normalizeWeights}
          />
        </Panel>

        <Panel title="Placement">
          <label className="field">
            <span>Coverage radius <output>{radius} mi</output></span>
            <input
              id="radius-range"
              type="range"
              min={RADIUS.min}
              max={RADIUS.max}
              step="1"
              value={radius}
              onChange={(e) => setRadius(Number(e.target.value))}
            />
          </label>
          <div className="field-row">
            <NumberField id="radius-input" label="Radius (mi)" value={radius} min={RADIUS.min} max={RADIUS.max} onCommit={setRadius} />
            <NumberField id="k-input" label="Sites" value={k} min={SITES.min} max={SITES.max} onCommit={setK} />
          </div>
        </Panel>

        <Panel title="Layers">
          <LayerToggles
            layers={layers}
            onToggle={toggleLayer}
            heatmapMode={heatmapMode}
            onHeatmapMode={(mode) => {
              setHeatmapMode(mode);
              setLayers((l) => ({ ...l, heatmap: true }));
            }}
          />
        </Panel>

        <Panel title="Hospital types">
          <HospitalTypeFilter hospitals={hospitals} hiddenTypes={hiddenTypes} onToggle={toggleType} />
        </Panel>
      </aside>
    </div>
  );
}

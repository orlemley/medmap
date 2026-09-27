import { useEffect, useImperativeHandle, useLayoutEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import * as maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
// Bundlers must hand MapLibre its worker explicitly (MapLibre v6 docs, "Vite").
import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url";
import { BASEMAP_STYLES } from "../../config.js";
import { EMPTY_FC, US_BOUNDS } from "../../lib/constants.js";
import { coverageRings } from "../../lib/geo.js";
import { LAYER_GROUPS, addSourcesAndLayers, applyThemedPaint, heatmapIntensity, heatmapWeight } from "./layers.js";

maplibregl.setWorkerUrl(workerUrl);

/** Fit the home bounds, facing north with no tilt. */
function flyHome(map, home) {
  if (!home) return;
  const options = { padding: home.padding ?? 20, bearing: 0, pitch: 0 };
  // Only pass maxZoom when there is one: an explicit `undefined` overrides
  // MapLibre's default and turns the computed zoom into NaN.
  if (home.maxZoom !== undefined) options.maxZoom = home.maxZoom;
  map.fitBounds(home.bounds, options);
}

/**
 * Applied to each basemap style as it loads: drops the style's own border
 * layers, because we draw clearer ones (state-borders / country-borders in
 * layers.js). This also matters for correctness: the light style's border
 * layer has a filter MapLibre 6 rejects, which silently discards all border
 * data in the tiles, so our own border layers would draw nothing.
 */
const withoutBasemapBorders = (previous, next) => ({
  ...next,
  layers: next.layers.filter((layer) => layer["source-layer"] !== "boundary"),
});

function uniqueById(features) {
  const seen = new Map();
  for (const f of features) if (!seen.has(f.id)) seen.set(f.id, f);
  return [...seen.values()];
}

const HOME_ICON =
  '<svg viewBox="0 0 20 20" width="18" height="18" aria-hidden="true">' +
  '<path d="M3 9.5 10 3.5l7 6M5.5 8v8h3.5v-4.5h2V16h3.5V8" fill="none" stroke="currentColor" ' +
  'stroke-width="1.7" stroke-linejoin="round" stroke-linecap="round"/></svg>';

/**
 * A MapLibre control with one button that flies back to the starting view.
 * It sits in the top-right corner under the zoom buttons and compass.
 */
class ResetViewControl {
  constructor(onClick) {
    this.onClick = onClick;
  }

  onAdd() {
    this.container = document.createElement("div");
    this.container.className = "maplibregl-ctrl maplibregl-ctrl-group";
    this.button = document.createElement("button");
    this.button.type = "button";
    this.button.className = "medmap-reset-view";
    this.button.innerHTML = HOME_ICON;
    this.button.addEventListener("click", this.onClick);
    this.container.append(this.button);
    this.setLabel("the starting view");
    return this.container;
  }

  setLabel(where) {
    if (!this.button) return;
    this.button.title = `Reset view (${where})`;
    this.button.setAttribute("aria-label", `Reset view to ${where}`);
  }

  onRemove() {
    this.button.removeEventListener("click", this.onClick);
    this.container.remove();
  }
}

/** Sets a boolean feature-state key on `ids`, clearing it from the previous set. */
function useFeatureStateFlag(mapRef, loaded, key, target) {
  const previous = useRef(null);
  useEffect(() => {
    if (!loaded) return;
    const map = mapRef.current;
    const prev = previous.current;
    if (prev) for (const id of prev.ids) map.setFeatureState({ source: prev.source, id }, { [key]: false });
    if (target) for (const id of target.ids) map.setFeatureState({ source: target.source, id }, { [key]: true });
    previous.current = target;
  }, [mapRef, loaded, key, target]);
}

/**
 * The MapLibre map as a React component.
 *
 * React owns the data (props); this component pushes it into MapLibre with
 * one effect per concern (sources, visibility, filters, feature-state,
 * popup). MapLibre's own events call back up through the on* props.
 * The parent gets `focusOn` through `ref`.
 *
 * `homeView` ({ bounds, padding, maxZoom, label }) is the "starting view":
 * the map flies there whenever it changes (e.g. a new state is picked), and
 * the Reset view button returns there, facing north with no tilt.
 *
 * `theme` ("light" | "dark") picks the basemap style; `basemap`
 * ("streets" | "satellite") shows or hides the satellite photos on top of it.
 * Changing the theme swaps the whole MapLibre style, which drops our layers,
 * so they're re-added when the new style loads and every effect below runs
 * again (they all depend on `loaded`).
 */
export default function MedMap({
  ref,
  hospitals,
  population,
  candidates = EMPTY_FC,
  ringRadius,
  radius,
  layers,
  heatmapMode,
  hospitalTypes,
  homeView,
  theme = "light",
  basemap = "streets",
  selected,
  hoveredCandidate,
  popup,
  onHospitalsClick,
  onCandidateClick,
  onCandidateHover,
  onPopupClose,
}) {
  const containerRef = useRef(null);
  const mapRef = useRef(null);
  const [loaded, setLoaded] = useState(false);
  const [failure, setFailure] = useState(null);

  // Map events are registered once, so they read the latest props from here.
  const latest = useRef({});
  useLayoutEffect(() => {
    latest.current = {
      radius, heatmapMode, homeView, theme, basemap,
      onHospitalsClick, onCandidateClick, onCandidateHover, onPopupClose,
    };
  });
  const resetControl = useRef(null);
  // Theme of the basemap style currently shown (or loading).
  const styleTheme = useRef(null);

  // --- Create the map once --------------------------------------------------
  useEffect(() => {
    let map;
    try {
      map = new maplibregl.Map({
        container: containerRef.current,
        bounds: US_BOUNDS,
        fitBoundsOptions: { padding: 20 },
        attributionControl: { compact: true },
      });
    } catch (err) {
      setFailure(err instanceof maplibregl.GPUInitializationError
        ? "This browser can't draw the map (it needs WebGL2). Try an up-to-date Chrome, Edge, Firefox or Safari."
        : `The map failed to start: ${err.message}`);
      return undefined;
    }
    mapRef.current = map;
    window.medmapMap = map; // for poking at the map from the browser console
    // The style is set here rather than in the constructor so it can go
    // through withoutBasemapBorders, like every later theme switch.
    styleTheme.current = latest.current.theme;
    map.setStyle(BASEMAP_STYLES[styleTheme.current], { transformStyle: withoutBasemapBorders });
    // The compass shows when the map is rotated or tilted; clicking it points north again.
    map.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), "top-right");
    resetControl.current = new ResetViewControl(() => flyHome(map, latest.current.homeView));
    map.addControl(resetControl.current, "top-right");
    map.addControl(new maplibregl.ScaleControl({ unit: "imperial" }), "bottom-left");

    // Guarded: during a style switch the layer briefly doesn't exist.
    const candidatesAt = (point) =>
      map.getLayer("candidates") ? map.queryRenderedFeatures(point, { layers: ["candidates"] }) : [];
    let hoveredHospital = null;
    const setHospitalHover = (id) => {
      if (hoveredHospital === id) return;
      if (hoveredHospital !== null) map.setFeatureState({ source: "hospitals", id: hoveredHospital }, { hover: false });
      hoveredHospital = id;
      if (id !== null) map.setFeatureState({ source: "hospitals", id }, { hover: true });
    };

    const addListeners = () => {
      for (const layer of ["hospitals", "candidates"]) {
        map.on("mouseenter", layer, () => {
          map.getCanvas().style.cursor = "pointer";
        });
      }
      map.on("mousemove", "hospitals", (e) => {
        // Sites draw on top; don't hover a hospital hidden under one.
        setHospitalHover(candidatesAt(e.point).length ? null : e.features[0].id);
      });
      map.on("mouseleave", "hospitals", () => {
        map.getCanvas().style.cursor = "";
        setHospitalHover(null);
      });
      map.on("mousemove", "candidates", (e) => latest.current.onCandidateHover(e.features[0].id));
      map.on("mouseleave", "candidates", () => {
        map.getCanvas().style.cursor = "";
        latest.current.onCandidateHover(null);
      });
      map.on("click", "candidates", (e) => latest.current.onCandidateClick(e.features[0].id));
      map.on("click", "hospitals", (e) => {
        if (candidatesAt(e.point).length) return;
        const features = uniqueById(e.features);
        latest.current.onHospitalsClick(features.map((f) => ({ id: f.id, ...f.properties })), features[0].geometry.coordinates);
      });
    };

    // Fires for the first style and after every theme switch. Our sources and
    // layers are (re)added here; the effects then push the data back in.
    let listenersAdded = false;
    map.on("style.load", () => {
      addSourcesAndLayers(map, latest.current);
      hoveredHospital = null;
      if (!listenersAdded) {
        addListeners(); // layer listeners survive style switches
        listenersAdded = true;
      }
      setLoaded(true);
    });

    return () => {
      setLoaded(false);
      map.remove();
      mapRef.current = null;
      resetControl.current = null;
      if (window.medmapMap === map) delete window.medmapMap;
    };
  }, []);

  // Go to the starting view whenever it changes, e.g. when a state is picked.
  useEffect(() => {
    if (mapRef.current && homeView) flyHome(mapRef.current, homeView);
    resetControl.current?.setLabel(homeView?.label ?? "the starting view");
  }, [homeView]);

  useImperativeHandle(ref, () => ({
    /** Fly to a point, leaving room above it for its popup. */
    focusOn: (center) => {
      const map = mapRef.current;
      if (map) map.flyTo({ center, zoom: Math.max(map.getZoom(), 7.5), offset: [0, 160], essential: true });
    },
  }), []);

  // --- Data --------------------------------------------------------------------
  useEffect(() => {
    if (loaded && hospitals) mapRef.current.getSource("hospitals").setData(hospitals);
  }, [loaded, hospitals]);

  useEffect(() => {
    if (loaded && population) mapRef.current.getSource("population").setData(population);
  }, [loaded, population]);

  useEffect(() => {
    if (!loaded) return;
    // Old hover/selected states belong to the previous result set.
    mapRef.current.removeFeatureState({ source: "candidates" });
    mapRef.current.getSource("candidates").setData(candidates);
  }, [loaded, candidates]);

  const rings = useMemo(() => coverageRings(candidates, ringRadius), [candidates, ringRadius]);
  useEffect(() => {
    if (loaded) mapRef.current.getSource("rings").setData(rings);
  }, [loaded, rings]);

  // --- Appearance --------------------------------------------------------------
  useEffect(() => {
    if (!loaded) return;
    // Layers are never removed and re-added; switches only flip visibility.
    for (const [group, ids] of Object.entries(LAYER_GROUPS)) {
      for (const id of ids) mapRef.current.setLayoutProperty(id, "visibility", layers[group] ? "visible" : "none");
    }
  }, [loaded, layers]);

  useEffect(() => {
    if (!loaded) return;
    mapRef.current.setPaintProperty("heatmap", "heatmap-weight", heatmapWeight(heatmapMode, radius));
    mapRef.current.setPaintProperty("heatmap", "heatmap-intensity", heatmapIntensity(heatmapMode));
  }, [loaded, heatmapMode, radius]);

  useEffect(() => {
    if (!loaded) return;
    mapRef.current.setFilter("hospitals", hospitalTypes ? ["in", ["get", "type"], ["literal", hospitalTypes]] : null);
  }, [loaded, hospitalTypes]);

  useEffect(() => {
    if (!loaded) return;
    mapRef.current.setLayoutProperty("satellite", "visibility", basemap === "satellite" ? "visible" : "none");
  }, [loaded, basemap]);

  useEffect(() => {
    if (loaded) applyThemedPaint(mapRef.current, theme, basemap);
  }, [loaded, theme, basemap]);

  const hoverTarget = useMemo(
    () => (hoveredCandidate === null ? null : { source: "candidates", ids: [hoveredCandidate] }),
    [hoveredCandidate]
  );
  useFeatureStateFlag(mapRef, loaded, "hover", hoverTarget);
  useFeatureStateFlag(mapRef, loaded, "selected", selected);

  // --- Popup (content is rendered by React through a portal) ---------------------
  const popupRef = useRef(null);
  const [popupNode, setPopupNode] = useState(null);
  const popupKey = popup?.key;
  useEffect(() => {
    if (!loaded || !popup) return undefined;
    const node = document.createElement("div");
    // Width comes from CSS (.popup), which grows with the text size setting.
    const instance = new maplibregl.Popup({ maxWidth: "none", focusAfterOpen: false })
      .setLngLat(popup.lngLat)
      .setDOMContent(node)
      .addTo(mapRef.current);
    // Only user actions (close button, clicking the map) should report a close,
    // not our own cleanup when switching to a different popup.
    const handleClose = () => latest.current.onPopupClose(popup.key);
    instance.on("close", handleClose);
    popupRef.current = instance;
    setPopupNode(node);
    return () => {
      instance.off("close", handleClose);
      instance.remove();
      popupRef.current = null;
      setPopupNode(null);
    };
    // A popup's position is fixed for its key, so the key alone decides when to rebuild.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loaded, popupKey]);

  useLayoutEffect(() => {
    // Re-anchor once React has filled the popup, now that its real size is known.
    if (popupNode && popupRef.current) popupRef.current.setLngLat(popupRef.current.getLngLat());
  }, [popupNode]);

  // --- Theme switch: swap the basemap style ------------------------------------
  // Must stay the LAST effect in this component. setStyle() replaces the style
  // immediately with one that's still loading, and any map update after that
  // (in the same render) would throw. Effects run in order, so every update
  // above has already been applied to the old style by the time this runs.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || styleTheme.current === theme) return;
    styleTheme.current = theme;
    setLoaded(false); // effects wait for "style.load" to re-add our layers
    map.setStyle(BASEMAP_STYLES[theme], { diff: false, transformStyle: withoutBasemapBorders });
  }, [theme]);

  return (
    <>
      <div ref={containerRef} className="map-canvas" role="region" aria-label="Map of hospitals and recommended sites" />
      {failure && <div className="map-failure" role="alert">{failure}</div>}
      {popupNode && popup && createPortal(popup.content, popupNode)}
    </>
  );
}

import { useEffect, useImperativeHandle, useLayoutEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import * as maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
// Bundlers must hand MapLibre its worker explicitly (MapLibre v6 docs, "Vite").
import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url";
import { BASEMAP_STYLE } from "../../config.js";
import { EMPTY_FC, US_BOUNDS } from "../../lib/constants.js";
import { coverageRings } from "../../lib/geo.js";
import { LAYER_GROUPS, addSourcesAndLayers, heatmapIntensity, heatmapWeight } from "./layers.js";

maplibregl.setWorkerUrl(workerUrl);

function uniqueById(features) {
  const seen = new Map();
  for (const f of features) if (!seen.has(f.id)) seen.set(f.id, f);
  return [...seen.values()];
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
 * The parent gets `fitBounds` and `focusOn` through `ref`.
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
    latest.current = { radius, heatmapMode, onHospitalsClick, onCandidateClick, onCandidateHover, onPopupClose };
  });

  // --- Create the map once --------------------------------------------------
  useEffect(() => {
    let map;
    try {
      map = new maplibregl.Map({
        container: containerRef.current,
        style: BASEMAP_STYLE,
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
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    map.addControl(new maplibregl.ScaleControl({ unit: "imperial" }), "bottom-left");

    const candidatesAt = (point) => map.queryRenderedFeatures(point, { layers: ["candidates"] });
    let hoveredHospital = null;
    const setHospitalHover = (id) => {
      if (hoveredHospital === id) return;
      if (hoveredHospital !== null) map.setFeatureState({ source: "hospitals", id: hoveredHospital }, { hover: false });
      hoveredHospital = id;
      if (id !== null) map.setFeatureState({ source: "hospitals", id }, { hover: true });
    };

    map.on("load", () => {
      addSourcesAndLayers(map, latest.current);

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

      setLoaded(true);
    });

    return () => {
      setLoaded(false);
      map.remove();
      mapRef.current = null;
      if (window.medmapMap === map) delete window.medmapMap;
    };
  }, []);

  useImperativeHandle(ref, () => ({
    fitBounds: (bounds, options) => mapRef.current?.fitBounds(bounds, options),
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
    const instance = new maplibregl.Popup({ maxWidth: "310px", focusAfterOpen: false })
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

  return (
    <>
      <div ref={containerRef} className="map-canvas" role="region" aria-label="Map of hospitals and recommended sites" />
      {failure && <div className="map-failure" role="alert">{failure}</div>}
      {popupNode && popup && createPortal(popup.content, popupNode)}
    </>
  );
}

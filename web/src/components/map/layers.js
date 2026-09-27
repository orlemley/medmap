import { SATELLITE } from "../../config.js";
import { EMPTY_FC, MARKER_COLORS, SATELLITE_BORDER } from "../../lib/constants.js";

// Highlighting reads feature-state, so hover/selection never changes layer paint.
const isSelected = ["boolean", ["feature-state", "selected"], false];
const isHovered = ["boolean", ["feature-state", "hover"], false];
// Hospitals whose address couldn't be matched to a map (web/api/geocode_hospitals.py)
// sit at their ZIP code's centre, so they're drawn as hollow rings.
const isApproximate = ["in", ["get", "loc_quality"], ["literal", ["zcta", "zip3", "county"]]];

export function heatmapWeight(mode, radius) {
  // Tract populations are mostly 1k-8k; scale so a typical tract is ~0.5.
  const byPopulation = ["interpolate", ["linear"], ["get", "p"], 0, 0, 8000, 1];
  return mode === "uncovered" ? ["case", [">", ["get", "d"], radius], byPopulation, 0] : byPopulation;
}

export function heatmapIntensity(mode) {
  // Uncovered tracts are sparse, so boost them to stay visible.
  const boost = mode === "uncovered" ? 3 : 1;
  return ["interpolate", ["linear"], ["zoom"], 3, 0.5 * boost, 9, 2 * boost];
}

/** Layer ids toggled by each switch in the Layers panel. */
export const LAYER_GROUPS = {
  hospitals: ["hospitals"],
  candidates: ["candidates", "candidate-labels"],
  rings: ["rings-fill", "rings-line"],
  heatmap: ["heatmap"],
};

/**
 * Paint that depends on the theme (light/dark) and basemap (streets/satellite).
 * Applied when the layers are created and again whenever either changes.
 */
export function themedPaint(theme, basemap) {
  const c = MARKER_COLORS[theme];
  const onPhotos = basemap === "satellite";
  const borderColor = onPhotos ? SATELLITE_BORDER : c.border;
  return {
    hospitals: {
      "circle-color": ["case", isSelected, c.hospitalSelected, isHovered, c.hospitalHover, c.hospital],
      "circle-opacity": ["case", isSelected, 1, isHovered, 1, isApproximate, 0.15, 1],
      "circle-stroke-color": ["case", isSelected, c.selectedStroke, isApproximate, c.hospital, "#ffffff"],
    },
    candidates: {
      "circle-color": ["interpolate", ["linear"], ["get", "score"], 0, c.candidateLow, 1, c.candidateHigh],
      "circle-stroke-color": ["case", isSelected, c.selectedStroke, "#ffffff"],
    },
    "candidate-labels": {
      "text-color": ["case", ["<", ["get", "score"], c.darkTextBelow], "#0f172a", "#ffffff"],
    },
    "rings-fill": { "fill-color": c.ring, "fill-opacity": onPhotos ? 0.12 : 0.06 },
    "rings-line": { "line-color": onPhotos ? "#ffffff" : c.ring },
    "state-borders": { "line-color": borderColor, "line-opacity": onPhotos ? 0.9 : 0.8 },
    "country-borders": { "line-color": borderColor, "line-opacity": onPhotos ? 0.95 : 0.9 },
  };
}

export function applyThemedPaint(map, theme, basemap) {
  for (const [layer, paint] of Object.entries(themedPaint(theme, basemap))) {
    for (const [property, value] of Object.entries(paint)) map.setPaintProperty(layer, property, value);
  }
}

/**
 * Where to insert layers that belong under the place names: just before the
 * style's final block of label layers. (The dark style has some labels early,
 * before roads and buildings, so "before the first label" would put the
 * satellite photos underneath the roads.)
 */
function firstOfFinalLabels(map) {
  const layers = map.getStyle().layers;
  let i = layers.length;
  while (i > 0 && layers[i - 1].type === "symbol") i--;
  return layers[i]?.id;
}

/**
 * Adds MedMap's sources and layers on top of the current basemap style. Runs
 * on first load and again after every basemap style switch (light/dark),
 * since switching styles drops everything that was added.
 */
export function addSourcesAndLayers(map, { theme, basemap, heatmapMode, radius }) {
  const paint = themedPaint(theme, basemap);
  const labels = firstOfFinalLabels(map);

  for (const id of ["hospitals", "candidates", "rings", "population"]) {
    map.addSource(id, { type: "geojson", data: EMPTY_FC });
  }
  map.addSource("satellite", {
    type: "raster",
    tiles: SATELLITE.tiles,
    tileSize: 256,
    maxzoom: SATELLITE.maxzoom,
    attribution: SATELLITE.attribution,
  });

  // --- Under the place names: photos, heatmap, rings, borders ---
  map.addLayer({
    id: "satellite",
    type: "raster",
    source: "satellite",
    layout: { visibility: basemap === "satellite" ? "visible" : "none" },
    paint: { "raster-fade-duration": 150 },
  }, labels);

  map.addLayer({
    id: "heatmap",
    type: "heatmap",
    source: "population",
    layout: { visibility: "none" },
    paint: {
      "heatmap-weight": heatmapWeight(heatmapMode, radius),
      "heatmap-intensity": heatmapIntensity(heatmapMode),
      "heatmap-radius": ["interpolate", ["linear"], ["zoom"], 3, 6, 6, 14, 10, 30],
      // Keep in sync with .ramp-heatmap in styles/map.css
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
  }, labels);

  map.addLayer({
    id: "rings-fill",
    type: "fill",
    source: "rings",
    paint: paint["rings-fill"],
  }, labels);

  // State and country borders, drawn from the basemap's own vector tiles
  // (the "boundary" layer of the OpenMapTiles schema), so there's nothing
  // extra to download. The basemap styles draw these very faintly.
  const borderLayout = { "line-join": "round", "line-cap": "round" };
  map.addLayer({
    id: "country-borders",
    type: "line",
    source: "openmaptiles",
    "source-layer": "boundary",
    filter: ["all", ["==", ["get", "admin_level"], 2], ["!=", ["get", "maritime"], 1]],
    layout: borderLayout,
    paint: {
      ...paint["country-borders"],
      "line-width": ["interpolate", ["linear"], ["zoom"], 3, 1, 6, 1.8, 10, 2.8],
    },
  }, labels);
  map.addLayer({
    id: "state-borders",
    type: "line",
    source: "openmaptiles",
    "source-layer": "boundary",
    filter: ["all", ["==", ["get", "admin_level"], 4], ["!=", ["get", "maritime"], 1]],
    layout: borderLayout,
    paint: {
      ...paint["state-borders"],
      "line-width": ["interpolate", ["linear"], ["zoom"], 3, 0.7, 6, 1.2, 10, 2],
    },
  }, labels);

  map.addLayer({
    id: "rings-line",
    type: "line",
    source: "rings",
    paint: { ...paint["rings-line"], "line-width": 1.5, "line-opacity": 0.8, "line-dasharray": [3, 2] },
  }, labels);

  // --- On top of everything: hospitals and recommended sites ---
  map.addLayer({
    id: "hospitals",
    type: "circle",
    source: "hospitals",
    paint: {
      ...paint.hospitals,
      "circle-radius": [
        "interpolate", ["linear"], ["zoom"],
        3, ["case", isSelected, 7, isHovered, 6, 2.5],
        10, ["case", isSelected, 12, isHovered, 10, 7],
      ],
      "circle-stroke-width": ["case", isSelected, 2, isApproximate, 2, 1],
    },
  });

  map.addLayer({
    id: "candidates",
    type: "circle",
    source: "candidates",
    paint: {
      ...paint.candidates,
      "circle-radius": [
        "+",
        ["interpolate", ["linear"], ["get", "score"], 0, 10, 1, 15],
        ["case", isSelected, 4, isHovered, 3, 0],
      ],
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
    paint: paint["candidate-labels"],
  });
}

import { CANDIDATE_HIGH, CANDIDATE_LOW, EMPTY_FC, HOSPITAL_COLOR } from "../../lib/constants.js";

// Highlighting reads feature-state, so hover/selection never changes layer paint.
const isSelected = ["boolean", ["feature-state", "selected"], false];
const isHovered = ["boolean", ["feature-state", "hover"], false];

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

export function addSourcesAndLayers(map, { heatmapMode, radius }) {
  for (const id of ["hospitals", "candidates", "rings", "population"]) {
    map.addSource(id, { type: "geojson", data: EMPTY_FC });
  }

  // Keep area layers under the basemap's place labels.
  const firstLabel = map.getStyle().layers.find((l) => l.type === "symbol")?.id;

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
}

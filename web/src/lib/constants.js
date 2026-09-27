export const DEFAULT_WEIGHTS = { population: 0.4, distance: 0.3, shortage: 0.2, cost: 0.1 };

export const WEIGHTS = [
  { key: "population", label: "Population", help: "People with no hospital within the radius" },
  { key: "distance", label: "Distance", help: "Miles closer to care for those people" },
  { key: "shortage", label: "Shortage bonus", help: "Site is in an MUA/P or primary-care HPSA" },
  { key: "cost", label: "Cost", help: "Lower population density = cheaper to build" },
];

// Must match the ranges enforced by web/api/server.py
export const RADIUS = { min: 5, max: 100, default: 30 };
export const SITES = { min: 1, max: 25, default: 5 };

export const DEBOUNCE_MS = 300;
export const US_BOUNDS = [[-125, 24.4], [-66.9, 49.5]];

// Map marker colours per theme. Keep in sync with --hospital and
// --candidate-low/high in styles/site.css (used by the legend).
export const MARKER_COLORS = {
  light: {
    hospital: "#dc2626",
    hospitalHover: "#f87171",
    hospitalSelected: "#7f1d1d",
    selectedStroke: "#0f172a",
    candidateLow: "#93c5fd",
    candidateHigh: "#1e3a8a",
    // Scores below this get dark rank numbers (the ramp is pale there).
    darkTextBelow: 0.45,
    ring: "#2563eb",
    border: "#64748b",
  },
  dark: {
    hospital: "#ef4444",
    hospitalHover: "#fca5a5",
    hospitalSelected: "#fecaca",
    selectedStroke: "#f8fafc",
    candidateLow: "#bfdbfe",
    candidateHigh: "#2563eb",
    darkTextBelow: 0.6,
    ring: "#60a5fa",
    border: "#94a3b8",
  },
};

// State borders over satellite photos, in either theme.
export const SATELLITE_BORDER = "#f8fafc";

// Text size steps for the map page (sidebar, legend, popups).
export const TEXT_SCALES = [0.9, 1, 1.15, 1.3, 1.5];

export const EMPTY_FC = { type: "FeatureCollection", features: [] };

export const STATE_NAMES = {
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

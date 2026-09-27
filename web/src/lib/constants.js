export const DEFAULT_WEIGHTS = {
  access: 0.22, capacity: 0.18, vulnerability: 0.12, configuration_fit: 0.12,
  cost_efficiency: 0.08, drive_access: 0.16, service_fit: 0.12,
};

export const WEIGHTS = [
  { key: "access", label: "Access", help: "People who gain timely access to care" },
  { key: "capacity", label: "Capacity gap", help: "Existing hospital and bed-capacity shortfall" },
  { key: "vulnerability", label: "Vulnerability", help: "Social and demographic need in the catchment" },
  { key: "configuration_fit", label: "Facility fit", help: "Fit of the proposed hospital configuration" },
  { key: "cost_efficiency", label: "Cost efficiency", help: "Relative benefit for the proposed facility scale" },
  { key: "drive_access", label: "Drive access", help: "Modeled improvement in travel access" },
  { key: "service_fit", label: "Service fit", help: "Strength of the recommended clinical-service mix" },
];

export const RESULTS = { min: 1, max: 500, default: 75 };
export const DEFAULT_FILTERS = {
  services: [], requireAllServices: false, minBeds: 0, maxBeds: 0,
  minScore: 0, routingRefined: "any", diversify: true,
};
export const DEBOUNCE_MS = 350;
export const US_BOUNDS = [[-125, 24.4], [-66.9, 49.5]];

export const MARKER_COLORS = {
  light: { hospital: "#dc2626", hospitalHover: "#f87171", hospitalSelected: "#7f1d1d", selectedStroke: "#0f172a", candidateLow: "#93c5fd", candidateHigh: "#1e3a8a", darkTextBelow: 0.45, ring: "#2563eb", border: "#64748b" },
  dark: { hospital: "#ef4444", hospitalHover: "#fca5a5", hospitalSelected: "#fecaca", selectedStroke: "#f8fafc", candidateLow: "#bfdbfe", candidateHigh: "#2563eb", darkTextBelow: 0.6, ring: "#60a5fa", border: "#94a3b8" },
};
export const SATELLITE_BORDER = "#f8fafc";
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

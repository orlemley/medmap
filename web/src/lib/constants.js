export const DEFAULT_WEIGHTS = {
  access: 0.22, capacity: 0.18, vulnerability: 0.12, configuration_fit: 0.12,
  cost_efficiency: 0.08, drive_access: 0.16, service_fit: 0.12,
};

// The seven Stage 8 score factors, in plain words. `key` is the API name
// (<key>_score on each site); `help` says what the pipeline measures
// (etl/stage6 fast_stage6.py, stage7 optimize.py, stage8 travel.py and
// services.py); `reason` finishes "Mainly because …" in a site's popup.
export const WEIGHTS = [
  {
    key: "access", label: "People helped",
    help: "Drive time saved across everyone nearby, plus people newly within 30 minutes of a hospital",
    reason: "it would cut drive times for a lot of people",
  },
  {
    key: "drive_access", label: "Remoteness",
    help: "How far the nearest hospital is today, and how many minutes a new one saves each resident",
    reason: "people here live far from a hospital today",
  },
  {
    key: "capacity", label: "Bed shortage",
    help: "People per existing hospital bed within a 30-minute drive",
    reason: "nearby hospitals have too few beds for the population",
  },
  {
    key: "vulnerability", label: "Community need",
    help: "Social and economic vulnerability of the people within a 30-minute drive",
    reason: "it would serve a high-need community",
  },
  {
    key: "service_fit", label: "Service demand",
    help: "How strongly local health needs call for the services this site would offer",
    reason: "local health needs match the services it would offer",
  },
  {
    key: "configuration_fit", label: "Right size",
    help: "Whether the proposed bed count matches unmet local demand, with enough people nearby to support it",
    reason: "its proposed size fits local demand",
  },
  {
    key: "cost_efficiency", label: "Value for cost",
    help: "Benefit (time saved, people reached, beds added) per dollar of estimated construction cost",
    reason: "it delivers a lot of benefit for its cost",
  },
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

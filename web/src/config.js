// Where the frontend finds the API. Empty = same origin, which covers both
// the Python server (it serves the built site) and `npm run dev` (Vite
// proxies /api to the Python server). To use an API somewhere else, e.g. the
// /algorithm server, build with VITE_API_BASE=http://127.0.0.1:8001.
export const API_BASE = import.meta.env.VITE_API_BASE ?? "";

// Free OpenStreetMap basemap, no API key needed.
export const BASEMAP_STYLE = "https://tiles.openfreemap.org/styles/positron";

export const GITHUB_URL = "https://github.com/orlemley/hackathon-237858";

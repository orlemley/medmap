// Where the frontend finds the API. Empty string = same origin, which is what
// you get from `python web/api/server.py`. If the API runs elsewhere (e.g. the
// /algorithm server on another port), set this to its origin, for example
// "http://127.0.0.1:8001".
export const API_BASE = "";

// Free OpenStreetMap basemap, no API key needed.
export const BASEMAP_STYLE = "https://tiles.openfreemap.org/styles/positron";

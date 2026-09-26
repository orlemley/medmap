"""MedMap dev server: the JSON API and the static site on one port.

    python web/api/server.py                 # http://127.0.0.1:8000
    python web/api/server.py --port 9000 --raw path/to/raw

Standard library only. Endpoints (all GET, all JSON):

    /api/health       server status and data-loading stats
    /api/states       states with data, with map bounding boxes
    /api/hospitals    ?state=XX   existing hospitals (FeatureCollection)
    /api/population   ?state=XX   census tract centroids for the heatmap
    /api/optimize     ?w_population=&w_distance=&w_shortage=&w_cost=
                      &radius=30&k=5&state=XX&include_hospitals=1
"""

import argparse
import gzip
import json
import os
import sys
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

API_DIR = os.path.dirname(os.path.realpath(__file__))
# Some Python distributions (e.g. the Windows embeddable zip) don't put the
# script's folder on sys.path, so add it explicitly.
if API_DIR not in sys.path:
    sys.path.insert(0, API_DIR)

from data_loader import Dataset  # noqa: E402
from placeholder_optimizer import PlaceholderOptimizer  # noqa: E402

WEB_ROOT = os.path.dirname(API_DIR)
DEFAULT_RAW = os.path.join(os.path.dirname(WEB_ROOT), "raw")

DEFAULT_WEIGHTS = {"population": 0.4, "distance": 0.3, "shortage": 0.2, "cost": 0.1}
RADIUS_RANGE = (5, 100)  # miles
K_RANGE = (1, 25)

STATIC_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".ico": "image/x-icon",
}


class BadRequest(Exception):
    pass


class MedMapAPI:
    """Turns query parameters into response dicts. No HTTP in here."""

    def __init__(self, dataset, optimizer):
        self.data = dataset
        self.optimizer = optimizer
        self._cache = {}

    def _state_param(self, query):
        state = (query.get("state") or [""])[0].strip().upper()
        if not state:
            return None
        if state not in self.data.states:
            raise BadRequest(f"Unknown state '{state}'. See /api/states for valid values.")
        return state

    def health(self, query):
        return {"status": "ok", "engine": "placeholder", "stats": self.data.stats}

    def states(self, query):
        if "states" not in self._cache:
            boxes = {}
            for t in self.data.tracts:
                # A few Aleutian tracts sit east of 180°; shift them west so
                # Alaska's box doesn't wrap the whole globe.
                lon = t["lon"] - 360 if t["lon"] > 0 else t["lon"]
                b = boxes.setdefault(t["state"], [lon, t["lat"], lon, t["lat"], 0, 0])
                b[0], b[1] = min(b[0], lon), min(b[1], t["lat"])
                b[2], b[3] = max(b[2], lon), max(b[3], t["lat"])
                b[4] += 1
            for h in self.data.hospitals:
                boxes[h["state"]][5] += 1
            self._cache["states"] = {"states": [
                {"state": s, "bbox": [round(v, 3) for v in b[:4]], "tracts": b[4], "hospitals": b[5]}
                for s, b in sorted(boxes.items())
            ]}
        return self._cache["states"]

    def hospitals(self, query):
        state = self._state_param(query)
        key = ("hospitals", state)
        if key not in self._cache:
            features = []
            for h in self.data.hospitals:
                if state and h["state"] != state:
                    continue
                props = {k: v for k, v in h.items() if k not in ("id", "lat", "lon")}
                features.append({
                    "type": "Feature",
                    "id": h["id"],
                    "geometry": {"type": "Point", "coordinates": [round(h["lon"], 5), round(h["lat"], 5)]},
                    "properties": props,
                })
            self._cache[key] = {"type": "FeatureCollection", "features": features}
        return self._cache[key]

    def population(self, query):
        state = self._state_param(query)
        key = ("population", state)
        if key not in self._cache:
            features = []
            for t in self.data.tracts:
                if (state and t["state"] != state) or t["pop"] <= 0:
                    continue
                features.append({
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [round(t["lon"], 4), round(t["lat"], 4)]},
                    # p = people, d = straight-line miles to nearest coverage hospital
                    "properties": {"p": t["pop"], "d": round(min(t["nearest_hospital_mi"], 9999), 1)},
                })
            self._cache[key] = {"type": "FeatureCollection", "features": features}
        return self._cache[key]

    def optimize(self, query):
        def number(name, default, lo, hi, cast=float):
            raw = (query.get(name) or [None])[0]
            if raw in (None, ""):
                return default
            try:
                value = cast(float(raw))
            except (ValueError, OverflowError):
                raise BadRequest(f"'{name}' must be a number, got '{raw}'.")
            if not lo <= value <= hi:
                raise BadRequest(f"'{name}' must be between {lo} and {hi}, got {raw}.")
            return value

        weights = {name: number("w_" + name, default, 0.0, 1.0) for name, default in DEFAULT_WEIGHTS.items()}
        radius = number("radius", 30, *RADIUS_RANGE, cast=int)
        k = number("k", 5, *K_RANGE, cast=int)
        state = self._state_param(query)
        include_hospitals = (query.get("include_hospitals") or ["1"])[0] not in ("0", "false")

        t0 = time.time()
        candidates, meta = self.optimizer.get_top_placements(weights, radius=radius, k=k, state=state)
        meta["compute_ms"] = round((time.time() - t0) * 1000)
        response = {"candidates": candidates, "meta": meta}
        if include_hospitals:
            response["hospitals"] = self.hospitals(query)
        return response


def make_handler(api):
    routes = {
        "/api/health": api.health,
        "/api/states": api.states,
        "/api/hospitals": api.hospitals,
        "/api/population": api.population,
        "/api/optimize": api.optimize,
    }

    class Handler(BaseHTTPRequestHandler):
        server_version = "MedMapDev/0.1"

        def do_GET(self):
            url = urlparse(self.path)
            if url.path.startswith("/api/"):
                self._api(url)
            else:
                self._static(unquote(url.path))

        def do_OPTIONS(self):
            self.send_response(204)
            self._cors()
            self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
            self.send_header("Access-Control-Max-Age", "86400")
            self.end_headers()

        def _cors(self):
            # Lets the frontend be served from a different port/origin.
            self.send_header("Access-Control-Allow-Origin", "*")

        def _api(self, url):
            route = routes.get(url.path.rstrip("/"))
            if route is None:
                return self._json(404, {"error": f"No endpoint {url.path}"})
            try:
                self._json(200, route(parse_qs(url.query)))
            except BadRequest as e:
                self._json(400, {"error": str(e)})
            except Exception:
                traceback.print_exc()
                self._json(500, {"error": "Internal server error; see the server console."})

        def _json(self, status, payload):
            body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
            self._send(status, "application/json; charset=utf-8", body, cors=True, cache="no-store")

        def _static(self, path):
            rel = "index.html" if path in ("", "/") else path.lstrip("/")
            full = os.path.realpath(os.path.join(WEB_ROOT, rel))
            ext = os.path.splitext(full)[1].lower()
            inside = os.path.commonpath([full, WEB_ROOT]) == WEB_ROOT
            is_api_source = os.path.commonpath([full, API_DIR]) == API_DIR
            if not inside or is_api_source or ext not in STATIC_TYPES or not os.path.isfile(full):
                return self._send(404, "text/plain; charset=utf-8", b"Not found")
            with open(full, "rb") as f:
                body = f.read()
            self._send(200, STATIC_TYPES[ext], body, cache="no-cache")

        def _send(self, status, content_type, body, cors=False, cache=None):
            use_gzip = len(body) > 1024 and "gzip" in self.headers.get("Accept-Encoding", "")
            if use_gzip:
                body = gzip.compress(body, compresslevel=5)
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            if use_gzip:
                self.send_header("Content-Encoding", "gzip")
                self.send_header("Vary", "Accept-Encoding")
            if cache:
                self.send_header("Cache-Control", cache)
            if cors:
                self._cors()
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt, *args):
            sys.stderr.write("%s  %s\n" % (self.log_date_time_string(), fmt % args))

    return Handler


def main():
    parser = argparse.ArgumentParser(description="MedMap dev server (API + static site)")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--raw", default=DEFAULT_RAW, help="path to the raw/ data folder")
    args = parser.parse_args()

    if not os.path.isdir(args.raw):
        sys.exit(f"Data folder not found: {args.raw}\n"
                 "Download it with src/optimal_hospital_placer/etl/get_raw_data.ps1 or pass --raw.")

    print(f"Loading data from {args.raw} ...", flush=True)
    dataset = Dataset(args.raw)
    print(f"  {dataset.stats['tracts']} tracts, {dataset.stats['hospitals']} hospitals "
          f"({dataset.stats['load_seconds']}s)", flush=True)
    print("Computing distance from each tract to its nearest hospital ...", flush=True)
    optimizer = PlaceholderOptimizer(dataset)

    server = ThreadingHTTPServer((args.host, args.port), make_handler(MedMapAPI(dataset, optimizer)))
    print(f"MedMap running at http://{args.host}:{args.port}/  (Ctrl+C to stop)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()

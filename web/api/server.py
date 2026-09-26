"""MedMap server: the JSON API and the built React site on one port.

    python web/api/server.py                 # http://127.0.0.1:8000, this computer only
    python web/api/server.py --open          # ...and open it in the browser
    python web/api/server.py --host 0.0.0.0  # also reachable from other devices on the network
    python web/api/server.py --raw path/to/raw   # use raw CSVs instead of the data bundle

HOST and PORT environment variables set the defaults (hosting platforms and
the Docker image use them). Data comes from web/api/medmap_data.json.gz
unless --raw is given. Scoring uses placeholder_optimizer.py unless the
OPTIMIZER_URL environment variable points at another service (see
remote_optimizer.py), e.g. the real algorithm running in its own container.

The site is the React build in web/dist (made by `npm run build` in web/).
Page routes such as /map and /about all get dist/index.html, and React
Router picks the page in the browser.

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
import socket
import sys
import time
import threading
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

API_DIR = os.path.dirname(os.path.realpath(__file__))
# Some Python distributions (e.g. the Windows embeddable zip) don't put the
# script's folder on sys.path, so add it explicitly.
if API_DIR not in sys.path:
    sys.path.insert(0, API_DIR)

from data_loader import BUNDLE_PATH, Dataset, missing_raw_files  # noqa: E402
from placeholder_optimizer import PlaceholderOptimizer  # noqa: E402
from remote_optimizer import OptimizerRejected, RemoteOptimizer, UpstreamError  # noqa: E402

WEB_ROOT = os.path.dirname(API_DIR)
DIST_ROOT = os.path.join(WEB_ROOT, "dist")
DEFAULT_RAW = os.path.join(os.path.dirname(WEB_ROOT), "raw")  # only if there's no bundle

DEFAULT_WEIGHTS = {"population": 0.4, "distance": 0.3, "shortage": 0.2, "cost": 0.1}
RADIUS_RANGE = (5, 100)  # miles
K_RANGE = (1, 25)

STATIC_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".map": "application/json; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".woff2": "font/woff2",
    ".webp": "image/webp",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".ico": "image/x-icon",
}


NOT_BUILT_PAGE = b"""<!DOCTYPE html><meta charset="utf-8"><title>MedMap: not built</title>
<body style="font-family:system-ui,sans-serif;max-width:640px;margin:64px auto;padding:0 20px">
<h1>The MedMap site hasn't been built</h1>
<p>The API is running, but <code>web/dist</code> is missing. Build the React app once:</p>
<pre>cd web
npm install
npm run build</pre>
<p>Then reload this page. Or, while developing, run <code>npm run dev</code> in <code>web/</code>
and open the address it prints (it forwards <code>/api</code> to this server).</p>
</body>"""


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
        engine = getattr(self.optimizer, "name", "placeholder")
        if isinstance(self.optimizer, RemoteOptimizer):
            engine = f"remote ({self.optimizer.base_url})"
        return {"status": "ok", "engine": engine, "stats": self.data.stats}

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
        try:
            candidates, meta = self.optimizer.get_top_placements(weights, radius=radius, k=k, state=state)
        except OptimizerRejected as e:
            raise BadRequest(str(e))
        meta["compute_ms"] = round((time.time() - t0) * 1000)
        response = {"candidates": candidates, "meta": meta}
        if include_hospitals:
            response["hospitals"] = self.hospitals(query)
        return response


class MedMapServer(ThreadingHTTPServer):
    def handle_error(self, request, client_address):
        # A browser closing a tab or cancelling a request mid-connection isn't
        # a server problem; skip the traceback for those.
        if isinstance(sys.exc_info()[1], (ConnectionAbortedError, ConnectionResetError, BrokenPipeError)):
            return
        super().handle_error(request, client_address)


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

        def do_HEAD(self):
            # Same as GET without the body; some uptime checkers use HEAD.
            self._head_only = True
            self.do_GET()

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
                status, payload = 200, route(parse_qs(url.query))
            except BadRequest as e:
                status, payload = 400, {"error": str(e)}
            except UpstreamError as e:
                print(f"  optimizer service error: {e}", file=sys.stderr, flush=True)
                status, payload = 502, {"error": str(e)}
            except Exception:
                traceback.print_exc()
                status, payload = 500, {"error": "Internal server error; see the server console."}
            self._json(status, payload)

        def _json(self, status, payload):
            body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
            self._send(status, "application/json; charset=utf-8", body, cors=True, cache="no-store")

        def _static(self, path):
            index = os.path.join(DIST_ROOT, "index.html")
            if not os.path.isfile(index):
                return self._send(503, "text/html; charset=utf-8", NOT_BUILT_PAGE, cache="no-store")

            rel = path.lstrip("/")
            full = os.path.realpath(os.path.join(DIST_ROOT, rel))
            try:
                inside = os.path.commonpath([full, DIST_ROOT]) == DIST_ROOT
            except ValueError:  # different drive on Windows
                inside = False
            ext = os.path.splitext(rel)[1].lower()

            if rel and inside and os.path.isfile(full):
                if ext not in STATIC_TYPES:
                    return self._send(404, "text/plain; charset=utf-8", b"Not found")
                # Vite puts a content hash in every file name under assets/, so
                # those can be cached forever; everything else is rechecked.
                cache = "public, max-age=31536000, immutable" if rel.startswith("assets/") else "no-cache"
                with open(full, "rb") as f:
                    return self._send(200, STATIC_TYPES[ext], f.read(), cache=cache)

            # A missing file (e.g. /missing.js) is a real 404. Anything else is a
            # page route (/map, /about, old /map.html links) for React Router.
            if ext and ext != ".html":
                return self._send(404, "text/plain; charset=utf-8", b"Not found")
            with open(index, "rb") as f:
                self._send(200, STATIC_TYPES[".html"], f.read(), cache="no-cache")

        def _send(self, status, content_type, body, cors=False, cache=None):
            use_gzip = len(body) > 1024 and "gzip" in self.headers.get("Accept-Encoding", "")
            if use_gzip:
                body = gzip.compress(body, compresslevel=5)
            try:
                self._write(status, content_type, body, use_gzip, cors, cache)
            except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
                # The browser gave up on this request, e.g. the map cancelled
                # an outdated /api/optimize call. Nothing left to send it to.
                pass

        def _write(self, status, content_type, body, use_gzip, cors, cache):
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
            if not getattr(self, "_head_only", False):
                self.wfile.write(body)

        def log_message(self, fmt, *args):
            sys.stderr.write("%s  %s\n" % (self.log_date_time_string(), fmt % args))

    return Handler


def lan_address():
    """This machine's address on the local network, or None.

    Connecting a UDP socket sends no packets; it only picks the interface
    the OS would route through.
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 80))  # TEST-NET-1: never actually contacted
            ip = s.getsockname()[0]
    except OSError:
        return None
    return None if ip.startswith("127.") else ip


def load_dataset(raw):
    """Raw CSVs if --raw was given, else the bundle, else <repo>/raw as a fallback."""
    if raw:
        missing = missing_raw_files(raw)
        if missing:
            sys.exit(f"Missing raw files in {raw}:\n  " + "\n  ".join(missing))
        print(f"Loading raw CSVs from {raw} ...", flush=True)
        return Dataset(raw)
    if os.path.isfile(BUNDLE_PATH):
        print(f"Loading {os.path.relpath(BUNDLE_PATH)} ...", flush=True)
        return Dataset.from_bundle(BUNDLE_PATH)
    if not missing_raw_files(DEFAULT_RAW):
        print(f"No data bundle found; loading raw CSVs from {DEFAULT_RAW} ...", flush=True)
        return Dataset(DEFAULT_RAW)
    sys.exit(f"No data found. {BUNDLE_PATH} is missing (it's normally committed to the repo; "
             "try `git pull`), and there's no raw/ folder to build it from.")


def main():
    parser = argparse.ArgumentParser(description="MedMap server (API + built site)")
    parser.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"),
                        help="interface to listen on; 0.0.0.0 lets other devices connect (default: $HOST or 127.0.0.1)")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8000")),
                        help="port to listen on (default: $PORT or 8000)")
    parser.add_argument("--raw", default=None, help="load raw CSVs from this folder instead of the data bundle")
    parser.add_argument("--open", action="store_true", help="open the site in a browser once it's ready")
    args = parser.parse_args()

    dataset = load_dataset(args.raw)
    print(f"  {dataset.stats['tracts']} tracts, {dataset.stats['hospitals']} hospitals "
          f"({dataset.stats['load_seconds']}s)", flush=True)
    print("Computing distance from each tract to its nearest hospital ...", flush=True)
    # Always built: it also computes each tract's distance to the nearest
    # hospital, which the population heatmap uses.
    placeholder = PlaceholderOptimizer(dataset)
    optimizer_url = os.environ.get("OPTIMIZER_URL", "").strip()
    optimizer = RemoteOptimizer(optimizer_url) if optimizer_url else placeholder
    if optimizer_url:
        print(f"Scoring is forwarded to {optimizer_url}/api/optimize (OPTIMIZER_URL).", flush=True)

    if not os.path.isfile(os.path.join(DIST_ROOT, "index.html")):
        print("  Note: web/dist is missing, so only the API works. Run `npm install` and "
              "`npm run build` in web/ to build the site.", flush=True)

    server = MedMapServer((args.host, args.port), make_handler(MedMapAPI(dataset, optimizer)))
    shared = args.host in ("", "0.0.0.0", "::")
    browser_host = "127.0.0.1" if shared else args.host
    url = f"http://{browser_host}:{args.port}/"
    in_docker = os.path.exists("/.dockerenv") or os.environ.get("MEDMAP_IN_DOCKER")
    if in_docker:
        # The container's own address means nothing to the person reading this.
        print(f"MedMap is listening on port {args.port} inside the container. Open "
              "http://localhost:<published port>/ on this computer (8000 unless you changed "
              "MEDMAP_PORT), or http://<this computer's IP>:<published port>/ from other devices.", flush=True)
    else:
        print(f"MedMap running at {url}  (Ctrl+C to stop)", flush=True)
        if not shared:
            print("  Only this computer can open it. To share it on your Wi-Fi, run web/share.cmd "
                  "or add --host 0.0.0.0.", flush=True)
        else:
            ip = lan_address()
            if ip:
                print(f"  Other devices on the same network: http://{ip}:{args.port}/", flush=True)
            print("  If Windows asks, allow Python through the firewall (Private networks).", flush=True)
    if args.open:
        threading.Timer(0.5, webbrowser.open, [url]).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()

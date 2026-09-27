"""PLACEHOLDER scoring so the map has something real to draw.

This is NOT the MedMap algorithm. The real one will live in /algorithm (see
algorithm_prompt.txt). This file only exists so /api/optimize returns
believable results in the meantime, and it returns the same response shape
the frontend expects. When /algorithm is ready, point the frontend at its
API (API_BASE in web/js/config.js) or swap this module out in server.py.

Scoring (all distances are straight-line miles, not driving distance):

  Each census tract is a candidate site. A tract is "covered" when an
  existing acute-care hospital is within `radius` miles of its centroid.

  population  = uncovered people within `radius` of the candidate
  distance    = population-weighted average of
                (miles to nearest existing hospital - miles to candidate)
                over those same uncovered people
  shortage    = 0.5 * [tract in an active MUA/P] + 0.5 * [tract in an active primary-care HPSA]
  cost        = 1 - normalized log(1 + people per sq. mile)   (dense land is pricier)

  population and distance are divided by the 95th percentile of their
  non-zero values over the candidate pool and clipped at 1; cost is min-max
  normalized over the pool. Every factor ends up in [0, 1].

  score = (w_population*population + w_distance*distance
           + w_shortage*shortage + w_cost*cost) / (sum of weights)

  Picks are the top-k scores, skipping any candidate within `radius` miles
  of a site already picked, so results don't stack on neighbouring tracts.
"""

import math
import os
import threading
from collections import OrderedDict

EARTH_RADIUS_MI = 3958.8
CELL_DEG = 0.5  # spatial grid cell size, in degrees
# (radius, state) factor tables kept in memory. Each nationwide one is ~40 MB,
# so hosted demos with little RAM set MEDMAP_CACHE_SIZE lower (e.g. 4).
try:
    CACHE_SIZE = max(1, int(os.environ.get("MEDMAP_CACHE_SIZE", "16")))
except ValueError:
    CACHE_SIZE = 16


def haversine_mi(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_MI * math.asin(min(1.0, math.sqrt(a)))


def _robust_scale(values):
    """95th percentile of the non-zero values (1 if there are none).

    Dividing by this and clipping at 1 keeps one extreme outlier (a remote
    Aleutian island 900+ miles from a hospital) from squashing every other
    candidate's factor toward zero, which dividing by the max would do.
    """
    nonzero = sorted(v for v in values if v > 0)
    if not nonzero:
        return 1.0
    return nonzero[min(len(nonzero) - 1, int(0.95 * len(nonzero)))]


def _cell(lat, lon):
    return int(math.floor(lat / CELL_DEG)), int(math.floor(lon / CELL_DEG))


class Grid:
    """Bucket points into CELL_DEG x CELL_DEG cells for radius queries."""

    def __init__(self, items):
        self.cells = {}
        for item in items:
            self.cells.setdefault(_cell(item["lat"], item["lon"]), []).append(item)

    def within(self, lat, lon, radius_mi):
        """Yield (item, distance) for items within radius_mi of (lat, lon)."""
        dlat = radius_mi / 69.0
        # Longitude degrees shrink toward the poles; guard the cosine near 90°.
        dlon = radius_mi / (69.172 * max(0.05, math.cos(math.radians(min(89.0, abs(lat) + dlat)))))
        r0, c0 = _cell(lat - dlat, lon - dlon)
        r1, c1 = _cell(lat + dlat, lon + dlon)
        for r in range(r0, r1 + 1):
            for c in range(c0, c1 + 1):
                for item in self.cells.get((r, c), ()):
                    d = haversine_mi(lat, lon, item["lat"], item["lon"])
                    if d <= radius_mi:
                        yield item, d


class PlaceholderOptimizer:
    name = "placeholder"

    def __init__(self, dataset):
        self.data = dataset
        self.tracts = dataset.tracts
        self.coverage_hospitals = [h for h in dataset.hospitals if h["counts_for_coverage"]]
        self._factor_cache = OrderedDict()
        self._lock = threading.Lock()
        self._compute_nearest_hospital()
        self.tract_grid = Grid(self.tracts)

    def _compute_nearest_hospital(self):
        """Straight-line miles from every tract centroid to the nearest coverage hospital."""
        grid = Grid(self.coverage_hospitals)
        for t in self.tracts:
            best = math.inf
            radius = 25.0
            while True:
                for _, d in grid.within(t["lat"], t["lon"], radius):
                    best = min(best, d)
                if best <= radius or radius > 3000:
                    break
                radius *= 2
            t["nearest_hospital_mi"] = best

    # --- Factors ---------------------------------------------------------------

    def _raw_factors(self, radius, state):
        """Weight-independent factors for one (radius, state), cached.

        Candidates are limited to `state` when given, but uncovered demand is
        counted across state lines.
        """
        key = (radius, state)
        with self._lock:
            if key in self._factor_cache:
                self._factor_cache.move_to_end(key)
                return self._factor_cache[key]

            candidates = [t for t in self.tracts if state is None or t["state"] == state]
            pop = {id(c): 0 for c in candidates}
            reduction = {id(c): 0.0 for c in candidates}
            in_pool = set(pop)

            # Walk uncovered tracts outward; far fewer than candidates in dense areas.
            for u in self.tracts:
                if u["nearest_hospital_mi"] <= radius or u["pop"] <= 0:
                    continue
                for c, d in self.tract_grid.within(u["lat"], u["lon"], radius):
                    if id(c) in in_pool:
                        pop[id(c)] += u["pop"]
                        reduction[id(c)] += u["pop"] * (u["nearest_hospital_mi"] - d)

            densities = [c["density"] for c in candidates if c["density"] is not None]
            densities.sort()
            median_density = densities[len(densities) // 2] if densities else 0.0

            rows = []
            for c in candidates:
                p = pop[id(c)]
                density = c["density"] if c["density"] is not None else median_density
                rows.append({
                    "tract": c,
                    "uncovered_pop": p,
                    "avg_reduction_mi": reduction[id(c)] / p if p else 0.0,
                    "log_density": math.log1p(max(0.0, density)),
                    "density": density,
                    "density_imputed": c["density"] is None,
                })

            pop_scale = _robust_scale(r["uncovered_pop"] for r in rows)
            red_scale = _robust_scale(r["avg_reduction_mi"] for r in rows)
            lo = min((r["log_density"] for r in rows), default=0.0)
            hi = max((r["log_density"] for r in rows), default=0.0)
            span = (hi - lo) or 1.0
            for r in rows:
                t = r["tract"]
                r["f_population"] = min(1.0, r["uncovered_pop"] / pop_scale)
                r["f_distance"] = min(1.0, r["avg_reduction_mi"] / red_scale)
                r["f_shortage"] = 0.5 * t["mua"] + 0.5 * t["hpsa"]
                r["f_cost"] = 1.0 - (r["log_density"] - lo) / span

            self._factor_cache[key] = rows
            if len(self._factor_cache) > CACHE_SIZE:
                self._factor_cache.popitem(last=False)
            return rows

    # --- Public API ------------------------------------------------------------

    def get_top_placements(self, weights, radius=30, k=5, state=None):
        """Return (FeatureCollection of ranked candidates, meta dict)."""
        rows = self._raw_factors(radius, state)
        total_w = sum(weights.values())
        if total_w <= 0:
            weights = {name: 1.0 for name in weights}
            total_w = float(len(weights))

        scored = []
        for r in rows:
            s = (weights["population"] * r["f_population"]
                 + weights["distance"] * r["f_distance"]
                 + weights["shortage"] * r["f_shortage"]
                 + weights["cost"] * r["f_cost"]) / total_w
            scored.append((s, r))
        scored.sort(key=lambda x: (-x[0], -x[1]["uncovered_pop"], x[1]["tract"]["id"]))

        picked = []
        for s, r in scored:
            t = r["tract"]
            if any(haversine_mi(t["lat"], t["lon"], p["tract"]["lat"], p["tract"]["lon"]) < radius
                   for _, p in picked):
                continue
            picked.append((s, r))
            if len(picked) == k:
                break

        features = []
        for rank, (s, r) in enumerate(picked, start=1):
            t = r["tract"]
            features.append({
                "type": "Feature",
                "id": int(t["id"]),
                "geometry": {"type": "Point", "coordinates": [round(t["lon"], 5), round(t["lat"], 5)]},
                "properties": {
                    "rank": rank,
                    "score": round(s, 4),
                    "tract_id": t["id"],
                    "state": t["state"],
                    "county": t["county"],
                    "tract_population": t["pop"],
                    "uncovered_population": r["uncovered_pop"],
                    "avg_distance_reduction_mi": round(r["avg_reduction_mi"], 1),
                    "nearest_hospital_mi": round(t["nearest_hospital_mi"], 1),
                    "density_per_sq_mi": round(r["density"], 1),
                    "density_imputed": r["density_imputed"],
                    "in_mua": t["mua"],
                    "in_hpsa": t["hpsa"],
                    "ruca": t["ruca"],
                    "f_population": round(r["f_population"], 4),
                    "f_distance": round(r["f_distance"], 4),
                    "f_shortage": round(r["f_shortage"], 4),
                    "f_cost": round(r["f_cost"], 4),
                },
            })

        meta = {
            "engine": "placeholder",
            "weights": weights,
            "radius_mi": radius,
            "k": k,
            "state": state,
            "candidates_considered": len(rows),
            "candidates_adding_coverage": sum(1 for r in rows if r["uncovered_pop"] > 0),
        }
        return {"type": "FeatureCollection", "features": features}, meta

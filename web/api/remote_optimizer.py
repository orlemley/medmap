"""Scoring done by another service, e.g. the real algorithm in /algorithm.

Set OPTIMIZER_URL (for example http://algorithm:8000 in Docker Compose) and
the MedMap server forwards every /api/optimize call to
{OPTIMIZER_URL}/api/optimize instead of using placeholder_optimizer.py. The
website doesn't change: it keeps calling this server, which still serves the
site, hospitals, states and population data.

The other service must accept the same query parameters (w_population,
w_distance, w_shortage, w_cost, radius, k, state, include_hospitals) and
return {"candidates": FeatureCollection, "meta": {...}} with the feature
properties listed in the README under "GET /api/optimize".
"""

import json
import urllib.error
import urllib.request
from urllib.parse import urlencode


class UpstreamError(Exception):
    """The optimizer service is down or returned something unusable."""


class OptimizerRejected(Exception):
    """The optimizer service said the request itself was bad (HTTP 4xx)."""


class RemoteOptimizer:
    name = "remote"

    def __init__(self, base_url, timeout=60):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def get_top_placements(self, weights, radius=30, k=5, state=None):
        query = {"radius": radius, "k": k, "include_hospitals": 0}
        query.update({"w_" + name: value for name, value in weights.items()})
        if state:
            query["state"] = state
        url = f"{self.base_url}/api/optimize?{urlencode(query)}"

        try:
            with urllib.request.urlopen(url, timeout=self.timeout) as response:
                body = json.load(response)
        except urllib.error.HTTPError as e:
            try:
                message = json.load(e).get("error")
            except (ValueError, AttributeError):
                message = None
            if 400 <= e.code < 500:
                raise OptimizerRejected(message or f"The optimizer service rejected the request (HTTP {e.code}).")
            raise UpstreamError(f"The optimizer service at {self.base_url} failed (HTTP {e.code}): {message or 'no details'}")
        except (urllib.error.URLError, OSError, ValueError) as e:
            raise UpstreamError(f"Can't reach the optimizer service at {self.base_url} ({e}).")

        if not isinstance(body, dict) or not isinstance(body.get("candidates"), dict):
            raise UpstreamError(f"The optimizer service at {self.base_url} didn't return a 'candidates' FeatureCollection.")
        meta = dict(body.get("meta") or {})
        meta.setdefault("engine", self.name)
        meta["optimizer_url"] = self.base_url
        return body["candidates"], meta

"""Conservative fallback geocoding for unresolved Stage 3 hospital rows.

This enriches the broad Stage 3 registry in place; it never creates, removes,
or merges facilities. ZIP centroids are search/display anchors only and are
never promoted to authoritative facility coordinates.
"""
import csv
import hashlib
import io
import json
import math
import re
import time
from datetime import datetime, timezone

import pandas as pd
import requests
from shapely.geometry import Point

from s3_common import read_json, save_json, text


TIE_URL = "https://geocoding.geo.census.gov/geocoder/locations/onelineaddress"
OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]
USER_AGENT = "MedMap hospital-access research (hackathon project)"
PO_BOX = re.compile(r"\b(P\.?\s?O\.?\s*BOX|BOX)\s*\d+\b[\s,/-]*", re.I)
UNIT = re.compile(r"\b(SUITE|STE|FLOOR|FL|BLDG|BUILDING|ROOM|UNIT)\b\.?\s*[\w-]*", re.I)
NAME_STOPWORDS = {
    "THE", "OF", "AND", "INC", "LLC", "HOSPITAL", "HOSPITALS", "MEDICAL",
    "CENTER", "CENTRE", "HEALTH", "HEALTHCARE", "REGIONAL", "COMMUNITY",
    "MEMORIAL", "SYSTEM", "CAMPUS", "ST", "SAINT", "MC", "CTR", "HOSP", "MED",
}


def miles(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = (math.sin((p2 - p1) / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2)
    return 2 * 3958.8 * math.asin(min(1.0, math.sqrt(a)))


def clean_address(value):
    value = PO_BOX.sub(" ", text(value))
    value = UNIT.sub(" ", value)
    value = re.sub(r"^\s*ONE\b", "1", value, flags=re.I)
    value = re.sub(r"^\s*TWO\b", "2", value, flags=re.I)
    return re.sub(r"\s+", " ", value).strip(" ,-/")


def name_tokens(value):
    words = re.sub(r"[^A-Z0-9 ]", " ", text(value).upper().replace("&", " AND ")).split()
    return {w for w in words if w not in NAME_STOPWORDS and len(w) > 1}


def _parse_point(value):
    match = re.search(r"POINT\s*\(\s*(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)\s*\)", text(value), re.I)
    return (float(match.group(1)), float(match.group(2))) if match else None


def zip_anchors(catalog):
    """Return ZIP -> (lon, lat) from the already staged PLACES ZCTA table."""
    if catalog is None:
        return {}
    entry = next((e for e in catalog.entries if e["source"] == "PLACES" and "places_zcta.csv" in e["input"]), None)
    if entry is None:
        return {}
    source = catalog.load(entry)
    zip_col = next((c for c in ("zcta5", "zcta", "locationname") if c in source), None)
    point_col = next((c for c in ("geolocation", "geometry") if c in source), None)
    if not zip_col or not point_col:
        return {}
    result = {}
    for row in source[[zip_col, point_col]].to_dict("records"):
        postal = re.sub(r"\D", "", text(row[zip_col]))[-5:]
        point = _parse_point(row[point_col])
        if len(postal) == 5 and point:
            result[postal] = point
    return result


def _request_json(url, *, params=None, data=None, timeout=240, attempts=5):
    for attempt in range(attempts):
        try:
            response = requests.post(url, data=data, headers={"User-Agent": USER_AGENT}, timeout=timeout) if data else requests.get(
                url, params=params, headers={"User-Agent": USER_AGENT}, timeout=timeout)
            response.raise_for_status()
            return response.json()
        except (requests.RequestException, ValueError):
            if attempt + 1 == attempts:
                raise
            time.sleep(5 * (attempt + 1))


def _tie_candidates(address, benchmark):
    payload = _request_json(TIE_URL, params={"address": address, "benchmark": benchmark, "format": "json"}, timeout=60)
    return [{"latitude": m["coordinates"]["y"], "longitude": m["coordinates"]["x"],
             "matched_address": m.get("matchedAddress")}
            for m in payload.get("result", {}).get("addressMatches", [])]


def _batch_geocode(addresses, benchmark, request_geocode_batch):
    """Return the same cache-record shape as the existing Stage 3 geocoder."""
    if not addresses:
        return {}
    output = {}
    items = list(addresses.items())
    for start in range(0, len(items), 1000):
        batch = items[start:start + 1000]
        buffer = io.StringIO(newline="")
        writer = csv.writer(buffer)
        for key, address in batch:
            writer.writerow([key, *address])
        response = request_geocode_batch(buffer.getvalue().encode("utf-8"), benchmark, start // 1000 + 1)
        for values in csv.reader(io.StringIO(response.content.decode("utf-8-sig"))):
            if len(values) < 3 or values[0] not in dict(batch):
                raise ValueError("Unexpected alternate-address geocoder response")
            item = {"address": dict(batch)[values[0]], "benchmark": benchmark, "response": values,
                    "status": values[2], "longitude": None, "latitude": None,
                    "fetched_utc": datetime.now(timezone.utc).isoformat()}
            if values[2] == "Match" and len(values) >= 6:
                item["longitude"], item["latitude"] = map(float, values[5].split(","))
            output[values[0]] = item
    if set(output) != set(addresses):
        raise ValueError("Census omitted alternate-address records")
    return output


def _osm_places(points):
    clauses = []
    for lat, lon, radius in points:
        around = f"around:{int(radius * 1609)},{lat:.5f},{lon:.5f}"
        clauses.extend([f'nwr["amenity"="hospital"]({around});', f'nwr["healthcare"="hospital"]({around});'])
    query = "[out:json][timeout:180];(" + "".join(clauses) + ");out center tags;"
    last = None
    for index in range(9):
        try:
            payload = _request_json(OVERPASS_URLS[index % len(OVERPASS_URLS)], data={"data": query}, attempts=1)
            break
        except requests.RequestException as exc:
            last = exc
            time.sleep(4 + 4 * index)
    else:
        raise RuntimeError("OpenStreetMap lookup failed; cached work remains available") from last
    result = []
    for element in payload.get("elements", []):
        tags = element.get("tags") or {}
        center = element.get("center") or ({"lat": element["lat"], "lon": element["lon"]} if "lat" in element else None)
        names = [tags[k] for k in ("name", "official_name", "alt_name", "short_name") if tags.get(k)]
        if center and names:
            result.append({"osm_id": f'{element["type"]}/{element["id"]}', "latitude": center["lat"],
                           "longitude": center["lon"], "names": names})
    return result


def _best_osm(row, anchor, places, radius):
    wanted = name_tokens(row.get("name"))
    if not wanted:
        return None
    best = None
    for place in places:
        distance = miles(anchor[1], anchor[0], place["latitude"], place["longitude"])
        if distance > radius:
            continue
        for label in place["names"]:
            got = name_tokens(label)
            if not got:
                continue
            similarity = len(wanted & got) / len(wanted | got)
            candidate = (similarity, -distance, label, place)
            if similarity >= .5 and (best is None or candidate[:2] > best[:2]):
                best = candidate
    return best


def enrich_hospital_geocodes(frame, cache_dir, enabled, catalog, benchmark, request_geocode_batch):
    """Fill only missing hospital coordinates and return (frame, method counts)."""
    frame = frame.copy()
    for column in ("geocode_precision", "geocode_matched_address", "geocode_source_id",
                   "geocode_review_flag", "fallback_method"):
        if column not in frame:
            frame[column] = pd.Series(None, index=frame.index, dtype="object")
    for column in ("geocode_distance_from_anchor_miles", "geocode_name_similarity",
                   "fallback_longitude", "fallback_latitude"):
        if column not in frame:
            frame[column] = pd.Series(float("nan"), index=frame.index, dtype="float64")
    matched = frame.longitude.notna() & frame.latitude.notna()
    frame.loc[matched, "geocode_precision"] = "street_interpolated"
    anchors = zip_anchors(catalog)
    hospitals = frame.facility_type.eq("hospital")
    for index, row in frame.loc[hospitals & ~matched].iterrows():
        anchor = anchors.get(text(row.zip)[:5])
        if anchor:
            frame.at[index, "fallback_longitude"], frame.at[index, "fallback_latitude"] = anchor
            frame.at[index, "fallback_method"] = "zcta_centroid"

    counts = {"census_tie_resolved": 0, "census_alternate_address": 0, "openstreetmap_hospital": 0}
    tie_path = cache_dir / "census_ties.json"
    ties = read_json(tie_path) if tie_path.exists() else {}
    for index, row in frame.loc[hospitals & frame.geocode_status.eq("Tie")].iterrows():
        anchor = anchors.get(text(row.zip)[:5])
        if not anchor:
            continue
        one_line = f'{text(row.street)}, {text(row.city)}, {text(row.state)} {text(row.zip)}'
        if one_line not in ties and enabled:
            ties[one_line] = _tie_candidates(one_line, benchmark)
            save_json(tie_path, ties)
        options = ties.get(one_line) or []
        if options:
            choice = min(options, key=lambda item: miles(anchor[1], anchor[0], item["latitude"], item["longitude"]))
            distance = miles(anchor[1], anchor[0], choice["latitude"], choice["longitude"])
            if distance <= 25:
                frame.at[index, "longitude"], frame.at[index, "latitude"] = choice["longitude"], choice["latitude"]
                frame.at[index, "geocode_status"] = "Match"
                frame.at[index, "geocode_method"] = "census_tie_resolved"
                frame.at[index, "geocode_precision"] = "street_interpolated"
                frame.at[index, "geocode_matched_address"] = choice.get("matched_address")
                frame.at[index, "geocode_distance_from_anchor_miles"] = distance
                counts["census_tie_resolved"] += 1

    # A different address under the same CCN is only used when the unresolved
    # row lacks a usable street address and exactly one unambiguous alternative exists.
    located_now = frame.longitude.notna() & frame.latitude.notna()
    by_ccn = {}
    for ccn, group in frame.loc[hospitals & frame.ccn.notna()].groupby("ccn"):
        alternatives = {(clean_address(r.street), text(r.city), text(r.state), text(r.zip)[:5])
                        for r in group.itertuples() if clean_address(r.street) and not PO_BOX.search(text(r.street))}
        if len(alternatives) == 1:
            by_ccn[text(ccn)] = next(iter(alternatives))
    alternate_rows, pending = {}, {}
    for index, row in frame.loc[hospitals & ~located_now].iterrows():
        if clean_address(row.street) and not PO_BOX.search(text(row.street)):
            continue
        address = by_ccn.get(text(row.ccn))
        if not address:
            continue
        key = hashlib.sha256(json.dumps([benchmark, list(address)]).encode()).hexdigest()
        alternate_rows[index] = (key, address)
        path = cache_dir / f"{key}.json"
        if not path.exists():
            pending[key] = list(address)
    if pending and enabled:
        for key, item in _batch_geocode(pending, benchmark, request_geocode_batch).items():
            save_json(cache_dir / f"{key}.json", item)
    for index, (key, _) in alternate_rows.items():
        path = cache_dir / f"{key}.json"
        item = read_json(path) if path.exists() else None
        if item and item.get("status") == "Match":
            frame.at[index, "longitude"], frame.at[index, "latitude"] = item["longitude"], item["latitude"]
            frame.at[index, "geocode_status"] = "Match"
            frame.at[index, "geocode_method"] = "census_alternate_address"
            frame.at[index, "geocode_precision"] = "street_interpolated"
            frame.at[index, "geocode_matched_address"] = item.get("response", [None] * 5)[4]
            frame.at[index, "geocode_cache_key"] = key
            frame.at[index, "geocode_fetched_utc"] = item.get("fetched_utc")
            counts["census_alternate_address"] += 1

    located_now = frame.longitude.notna() & frame.latitude.notna()
    unresolved = frame.loc[hospitals & ~located_now & frame.fallback_longitude.notna()]
    osm_path = cache_dir / "openstreetmap_hospitals.json"
    osm = read_json(osm_path) if osm_path.exists() else {"places": {}, "searched": []}
    searched = set(osm.get("searched", [])); places_by_id = osm.get("places", {})
    todo = [(index, row) for index, row in unresolved.iterrows() if row.facility_id not in searched]
    if enabled:
        for start in range(0, len(todo), 60):
            chunk = todo[start:start + 60]
            points = [(row.fallback_latitude, row.fallback_longitude, 12) for _, row in chunk]
            for place in _osm_places(points):
                places_by_id[place["osm_id"]] = place
            searched.update(row.facility_id for _, row in chunk)
            osm = {"places": places_by_id, "searched": sorted(searched)}
            save_json(osm_path, osm)
    places = list(places_by_id.values())
    choices = {}
    for index, row in unresolved.iterrows():
        choices[index] = _best_osm(row, (row.fallback_longitude, row.fallback_latitude), places, 12)
    claims = {}
    for index, choice in choices.items():
        if choice:
            claims.setdefault(choice[3]["osm_id"], []).append(index)
    for claimants in claims.values():
        identities = {(text(frame.at[i, "ccn"]), frozenset(name_tokens(frame.at[i, "name"]))) for i in claimants}
        if len(identities) > 1:
            winner = max(claimants, key=lambda i: choices[i][:2])
            for index in claimants:
                if index != winner:
                    choices[index] = None
                    frame.at[index, "geocode_review_flag"] = "osm_feature_claim_conflict"
    for index, choice in choices.items():
        if not choice:
            continue
        similarity, neg_distance, label, place = choice
        frame.at[index, "longitude"], frame.at[index, "latitude"] = place["longitude"], place["latitude"]
        frame.at[index, "geocode_status"] = "Match"
        frame.at[index, "geocode_method"] = "openstreetmap_hospital"
        frame.at[index, "geocode_precision"] = "mapped_facility"
        frame.at[index, "geocode_matched_address"] = label
        frame.at[index, "geocode_source_id"] = place["osm_id"]
        frame.at[index, "geocode_distance_from_anchor_miles"] = -neg_distance
        frame.at[index, "geocode_name_similarity"] = similarity
        counts["openstreetmap_hospital"] += 1

    frame["geometry"] = [Point(lon, lat) if pd.notna(lon) and pd.notna(lat) else None
                         for lon, lat in zip(frame.longitude, frame.latitude)]
    return frame, counts

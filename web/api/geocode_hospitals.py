"""Put each hospital at its real location instead of its ZIP code's center.

The CMS hospital list has street addresses but no coordinates. This module
turns addresses into coordinates in layers, each catching what the one before
missed (full explanation and numbers: docs/hospital-locations.md):

  1. Census Geocoder, batch       street address -> point on the street in front
  2. Census Geocoder, one-line    "Tie" results (address exists twice, e.g. N/S
                                  New Ballas Rd) -> the candidate nearest the ZIP area
  3. CMS Provider of Services     a second CMS file that often has the street
                                  address when the main list only gives a PO box
  4. OpenStreetMap                hospitals mapped as buildings; matched by name
                                  near the hospital's ZIP area (Overpass API)
  5. Fallback                     keep the ZIP / county centre and mark it approximate

Every network answer is cached under raw/_geocode_cache/ (git-ignored, like
raw/), so rebuilding is fast and works offline once the cache exists. Only
build_data.py goes online; the server can reuse the cache with --raw.

Standard library only.
"""

import csv
import io
import json
import math
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

csv.field_size_limit(10**9)  # the CMS Provider of Services file has very wide rows

CENSUS_BATCH_URL = "https://geocoding.geo.census.gov/geocoder/locations/addressbatch"
CENSUS_ONELINE_URL = "https://geocoding.geo.census.gov/geocoder/locations/onelineaddress"
# Same benchmark as the team's ETL (src/optimal_hospital_placer/etl/stage3/s3_facilities.py),
# so both produce the same locations.
CENSUS_BENCHMARK = "Public_AR_Current"
OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]
USER_AGENT = "MedMap hackathon project (hospital geocoding; github.com/orlemley/hackathon-237858)"

# loc_quality values. The first three are precise; the rest are approximate
# (the frontend draws those as hollow rings).
PRECISE = {"address", "address_alt", "osm"}
APPROXIMATE = {"zcta", "zip3", "county"}

PO_BOX = re.compile(r"\b(P\.?\s?O\.?\s*BOX|BOX)\s*\d+\b[\s,/-]*", re.I)
UNIT = re.compile(r"\b(SUITE|STE|FLOOR|FL|BLDG|BUILDING|ROOM|UNIT)\b\.?\s*[\w-]*", re.I)
# Words too common in hospital names to tell two hospitals apart.
NAME_STOPWORDS = {
    "THE", "OF", "AND", "INC", "LLC", "HOSPITAL", "HOSPITALS", "MEDICAL", "CENTER", "CENTRE", "HEALTH",
    "HEALTHCARE", "REGIONAL", "COMMUNITY", "MEMORIAL", "SYSTEM", "CAMPUS", "ST", "SAINT", "MC", "CTR",
    "HOSP", "RMC", "MED",
}


def miles(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * 3958.8 * math.asin(min(1.0, math.sqrt(a)))


def clean_address(address):
    """Drop PO boxes and suite/building text, keep the street address if there is one."""
    a = PO_BOX.sub(" ", address)
    a = UNIT.sub(" ", a)
    a = re.sub(r"^\s*ONE\b", "1", a, flags=re.I)
    a = re.sub(r"^\s*TWO\b", "2", a, flags=re.I)
    return re.sub(r"\s+", " ", a).strip(" ,-/")


def name_tokens(name):
    words = re.sub(r"[^A-Z0-9 ]", " ", name.upper().replace("&", " AND ")).split()
    return {w for w in words if w not in NAME_STOPWORDS and len(w) > 1}


class Cache:
    """One JSON file per kind of lookup, under raw/_geocode_cache/."""

    def __init__(self, directory):
        self.directory = directory
        os.makedirs(directory, exist_ok=True)

    def load(self, name, default):
        path = os.path.join(self.directory, name)
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            return default

    def save(self, name, value):
        path = os.path.join(self.directory, name)
        with open(path + ".tmp", "w", encoding="utf-8") as f:
            json.dump(value, f)
        os.replace(path + ".tmp", path)


def _http(request, timeout, attempts=4):
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read()
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            if attempt == attempts - 1:
                raise
            time.sleep(5 * (attempt + 1))


def census_batch(addresses, log):
    """{key: (street, city, state, zip)} -> {key: {"status", "lat", "lon", "matched"}}"""
    results = {}
    items = list(addresses.items())
    for start in range(0, len(items), 1000):
        chunk = items[start:start + 1000]
        buf = io.StringIO()
        csv.writer(buf).writerows([[i, *address] for i, (_, address) in enumerate(chunk)])
        boundary = uuid.uuid4().hex
        body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"benchmark\"\r\n\r\n{CENSUS_BENCHMARK}\r\n"
                f"--{boundary}\r\nContent-Disposition: form-data; name=\"addressFile\"; filename=\"addresses.csv\"\r\n"
                f"Content-Type: text/csv\r\n\r\n{buf.getvalue()}\r\n--{boundary}--\r\n").encode("utf-8")
        request = urllib.request.Request(CENSUS_BATCH_URL, data=body, headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}", "User-Agent": USER_AGENT})
        text = _http(request, timeout=900).decode("utf-8", "replace")
        for row in csv.reader(io.StringIO(text)):
            if not row or not row[0].isdigit():
                continue
            key = chunk[int(row[0])][0]
            status = row[2] if len(row) > 2 else "No_Match"
            if status == "Match" and len(row) > 5 and "," in row[5]:
                lon, lat = map(float, row[5].split(","))
                results[key] = {"status": "Match", "lat": lat, "lon": lon, "matched": row[4]}
            else:
                results[key] = {"status": status, "lat": None, "lon": None, "matched": None}
        log(f"    Census batch: {start + len(chunk)}/{len(items)}")
    return results


def census_candidates(one_line_address):
    query = urllib.parse.urlencode({"address": one_line_address, "benchmark": CENSUS_BENCHMARK, "format": "json"})
    request = urllib.request.Request(f"{CENSUS_ONELINE_URL}?{query}", headers={"User-Agent": USER_AGENT})
    data = json.loads(_http(request, timeout=60))
    return [{"lat": m["coordinates"]["y"], "lon": m["coordinates"]["x"], "matched": m["matchedAddress"]}
            for m in data["result"]["addressMatches"]]


def osm_hospitals_near(points, log):
    """Named hospital features (points, or the centre of buildings/campuses)
    within the given radius of each (lat, lon, radius_miles) point.

    Many small "near here" questions in one request are far lighter for the
    free Overpass servers than "every hospital in a state".
    """
    clauses = []
    for lat, lon, radius_mi in points:
        around = f"around:{int(radius_mi * 1609)},{lat:.5f},{lon:.5f}"
        clauses.append(f'nwr["amenity"="hospital"]({around});')
        clauses.append(f'nwr["healthcare"="hospital"]({around});')
    query = "[out:json][timeout:180];(" + "".join(clauses) + ");out center tags;"
    data = urllib.parse.urlencode({"data": query}).encode("utf-8")
    for attempt in range(9):
        url = OVERPASS_URLS[attempt % len(OVERPASS_URLS)]
        try:
            request = urllib.request.Request(url, data=data, headers={"User-Agent": USER_AGENT})
            elements = json.loads(_http(request, timeout=240, attempts=1))["elements"]
            break
        except (urllib.error.URLError, TimeoutError, ConnectionError, ValueError):
            time.sleep(4 + 4 * attempt)  # the public servers are often busy; back off
    else:
        raise RuntimeError("OpenStreetMap download failed; run build_data.py again to resume")
    places = []
    for e in elements:
        tags = e.get("tags") or {}
        centre = e.get("center") or ({"lat": e["lat"], "lon": e["lon"]} if "lat" in e else None)
        names = [tags[k] for k in ("name", "official_name", "alt_name", "short_name") if tags.get(k)]
        if names and centre:
            places.append({"names": names, "lat": centre["lat"], "lon": centre["lon"],
                           "osm": f"{e['type']}/{e['id']}"})
    return places


def best_osm_match(hospital, places, max_miles):
    """Same-name OpenStreetMap hospital nearest the hospital's current (ZIP-area) point."""
    wanted = name_tokens(hospital["name"])
    if not wanted:
        return None
    best = None
    for place in places:
        d = miles(hospital["lat"], hospital["lon"], place["lat"], place["lon"])
        if d > max_miles:
            continue
        for name in place["names"]:
            got = name_tokens(name)
            if not got:
                continue
            score = len(wanted & got) / len(wanted | got)
            if score >= 0.5 and (best is None or (score, -d) > (best[0], -best[1])):
                best = (score, d, name, place)
    return best


def _place(hospital, lat, lon, quality, match):
    hospital["lat"], hospital["lon"] = lat, lon
    hospital["loc_quality"] = quality
    hospital["loc_match"] = match


def geocode_hospitals(hospitals, raw_dir, cache_dir, online=True, log=print):
    """Move hospitals from ZIP centres to real locations, in place. Returns counts per step.

    With online=False only cached answers are used (nothing is downloaded).
    Hospitals that no step can place keep their ZIP/county position and
    loc_quality ("zcta", "zip3" or "county").
    """
    cache = Cache(cache_dir)
    steps = {"census_address": 0, "census_tie": 0, "alternate_address": 0, "openstreetmap": 0}
    key = lambda street, h: "|".join([street.upper().strip(), h["city"].upper().strip(), h["state"], h["zip"]])

    # --- 1. Census batch on the address as listed --------------------------------
    census = cache.load("census_batch.json", {})
    todo = {key(h["address"], h): (h["address"], h["city"], h["state"], h["zip"])
            for h in hospitals if key(h["address"], h) not in census}
    if todo and online:
        log(f"  Step 1: Census Geocoder, {len(todo)} addresses")
        census.update(census_batch(todo, log))
        cache.save("census_batch.json", census)
    for h in hospitals:
        r = census.get(key(h["address"], h))
        if r and r["status"] == "Match":
            _place(h, r["lat"], r["lon"], "address", r["matched"])
            steps["census_address"] += 1

    # --- 2. Ties: the address exists more than once; take the nearest candidate --
    ties = cache.load("census_ties.json", {})
    for h in hospitals:
        if h["loc_quality"] in PRECISE:
            continue
        r = census.get(key(h["address"], h))
        if not r or r["status"] != "Tie":
            continue
        one_line = f"{h['address']}, {h['city']}, {h['state']} {h['zip']}"
        if one_line not in ties and online:
            ties[one_line] = census_candidates(one_line)
            time.sleep(0.2)
        candidates = ties.get(one_line) or []
        if candidates:
            c = min(candidates, key=lambda c: miles(h["lat"], h["lon"], c["lat"], c["lon"]))
            if miles(h["lat"], h["lon"], c["lat"], c["lon"]) <= 25:
                _place(h, c["lat"], c["lon"], "address", c["matched"])
                steps["census_tie"] += 1
    if online:
        cache.save("census_ties.json", ties)

    # --- 3. Street address from CMS's Provider of Services file ------------------
    pos_addresses = _provider_of_services_addresses(raw_dir)
    alternates = {}
    for h in hospitals:
        if h["loc_quality"] in PRECISE:
            continue
        for label, street in (("address_alt", clean_address(pos_addresses.get(h["facility_id"], ""))),
                              ("address", clean_address(h["address"]))):
            if street and street[0].isdigit() and street.upper() != h["address"].upper():
                alternates.setdefault(h["facility_id"], []).append((label, street))
    todo = {key(street, h): (street, h["city"], h["state"], h["zip"])
            for h in hospitals for _, street in alternates.get(h["facility_id"], [])
            if key(street, h) not in census}
    if todo and online:
        log(f"  Step 3: Census Geocoder on {len(todo)} alternate addresses")
        census.update(census_batch(todo, log))
        cache.save("census_batch.json", census)
    for h in hospitals:
        for label, street in alternates.get(h["facility_id"], []):
            if h["loc_quality"] in PRECISE:
                break
            r = census.get(key(street, h))
            if r and r["status"] == "Match":
                _place(h, r["lat"], r["lon"], label, r["matched"])
                steps["alternate_address"] += 1

    # --- 4. OpenStreetMap: find the hospital itself by name ----------------------
    remaining = [h for h in hospitals if h["loc_quality"] not in PRECISE]
    max_miles = lambda h: 12 if h["loc_quality"] == "zcta" else 25
    osm = cache.load("openstreetmap.json", {})
    if "places" not in osm:  # older cache layout: {state: [places]}
        osm = {"places": {p["osm"]: p for v in osm.values() for p in v}, "searched": []}
    searched = set(osm["searched"])
    todo = [h for h in remaining if h["facility_id"] not in searched]
    if todo and online:
        log(f"  Step 4: OpenStreetMap, looking near {len(todo)} hospitals")
        for start in range(0, len(todo), 60):
            chunk = todo[start:start + 60]
            for place in osm_hospitals_near([(h["lat"], h["lon"], max_miles(h)) for h in chunk], log):
                osm["places"][place["osm"]] = place
            searched.update(h["facility_id"] for h in chunk)
            osm["searched"] = sorted(searched)
            cache.save("openstreetmap.json", osm)  # save as we go, so a rerun resumes
            log(f"    OpenStreetMap: {start + len(chunk)}/{len(todo)} ({len(osm['places'])} hospitals found nearby)")
            time.sleep(2)
    places = list(osm["places"].values())
    for h in remaining:
        match = best_osm_match(h, places, max_miles(h))
        if match:
            _, _, name, place = match
            _place(h, place["lat"], place["lon"], "osm", f"{name} (OpenStreetMap {place['osm']})")
            steps["openstreetmap"] += 1

    steps["approximate"] = sum(1 for h in hospitals if h["loc_quality"] not in PRECISE)
    steps["osm_not_searched"] = sum(1 for h in remaining if h["facility_id"] not in searched)
    return steps


def _provider_of_services_addresses(raw_dir):
    """CCN -> street address from CMS's Provider of Services file, if it's there."""
    folder = os.path.join(raw_dir, "CMSFacilities")
    try:
        name = next(f for f in sorted(os.listdir(folder)) if f.startswith("Hospital_and_other") and f.endswith(".csv"))
    except (FileNotFoundError, StopIteration):
        return {}
    addresses = {}
    with open(os.path.join(folder, name), newline="", encoding="utf-8-sig", errors="replace") as f:
        for row in csv.DictReader(f):
            if row.get("PRVDR_NUM") and row.get("ST_ADR"):
                addresses[row["PRVDR_NUM"]] = row["ST_ADR"]
    return addresses

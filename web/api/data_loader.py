"""Load the data the API serves: from the raw CSVs, or from the bundle.

Raw CSVs (raw/, ~500 MB, git-ignored) are joined into a few small tables.
Those tables are saved as one compact file, medmap_data.json.gz, which is
committed, so the server (and Docker image) can run without raw/. Rebuild it
with `python web/api/build_data.py` after re-downloading raw data.

Standard library only, so the demo runs on a bare Python install.
Every join and fallback made here is documented in the project README
("Data assumptions").
"""

import csv
import datetime
import gzip
import json
import os
import re
import time

csv.field_size_limit(10**9)

POINT_RE = re.compile(r"POINT\s*\(\s*(-?[\d.]+)\s+(-?[\d.]+)\s*\)")

# Hospital types that count as "existing coverage" when scoring candidates.
# Psychiatric, children's and long-term hospitals are still drawn on the map,
# but they don't serve general emergency/acute demand.
COVERAGE_TYPES = {
    "Acute Care Hospitals",
    "Critical Access Hospitals",
    "Acute Care - Veterans Administration",
    "Acute Care - Department of Defense",
    "Rural Emergency Hospital",
}

# HRSA statuses that still mean "currently designated".
ACTIVE_STATUSES = {"Designated", "Proposed For Withdrawal"}

# HPSA designation types that describe an area or a population in an area.
# Facility HPSAs (FQHCs, prisons, clinics, ...) are points, not areas.
HPSA_AREA_TYPES = {"Geographic HPSA", "High Needs Geographic HPSA", "HPSA Population"}

# Raw files the loader reads, relative to raw/.
REQUIRED_RAW_FILES = [
    os.path.join("PLACES", "places_tract.csv"),
    os.path.join("PLACES", "places_zcta.csv"),
    os.path.join("PLACES", "places_county.csv"),
    os.path.join("RUCA", "2020-rural-urban-commuting-area-codes-census-tracts.csv"),
    os.path.join("MUAP", "MUA_DET.csv"),
    os.path.join("HPSA", "BCD_HPSA_FCT_DET_PC.csv"),
    os.path.join("CMSHospital", "Hospital_General_Information.csv"),
]

BUNDLE_PATH = os.path.join(os.path.dirname(os.path.realpath(__file__)), "medmap_data.json.gz")
BUNDLE_VERSION = 1
TRACT_FIELDS = ["id", "state", "county_fips", "county", "lon", "lat", "pop", "ruca", "density", "mua", "hpsa"]


def missing_raw_files(raw_dir):
    """Required raw files that aren't in raw_dir (all of them if it doesn't exist)."""
    return [f for f in REQUIRED_RAW_FILES if not os.path.isfile(os.path.join(raw_dir, f))]


def _open(path):
    return open(path, newline="", encoding="utf-8-sig", errors="replace")


def _parse_point(text):
    m = POINT_RE.search(text or "")
    if not m:
        return None
    return float(m.group(1)), float(m.group(2))


def _to_float(text, default=None):
    try:
        return float(text)
    except (TypeError, ValueError):
        return default


def _to_int(text, default=0):
    try:
        return int(float(text))
    except (TypeError, ValueError):
        return default


class Dataset:
    """Everything the API needs, loaded once at startup."""

    def __init__(self, raw_dir):
        self.raw_dir = raw_dir
        self.stats = {"source": "raw CSVs"}
        t0 = time.time()
        self.tracts = self._load_tracts()
        self._attach_ruca()
        self._attach_shortage()
        self.hospitals = self._load_hospitals()
        self.stats["load_seconds"] = round(time.time() - t0, 1)
        self.states = sorted({t["state"] for t in self.tracts})

    def path(self, *parts):
        return os.path.join(self.raw_dir, *parts)

    # --- Bundle: the joined tables in one small file ---------------------------

    def save_bundle(self, path=BUNDLE_PATH):
        """Write the joined tables to a gzipped JSON file (columns for tracts)."""
        columns = {name: [t[name] for t in self.tracts] for name in TRACT_FIELDS}
        columns["mua"] = [int(v) for v in columns["mua"]]
        columns["hpsa"] = [int(v) for v in columns["hpsa"]]
        payload = {
            "version": BUNDLE_VERSION,
            "built": datetime.date.today().isoformat(),
            "stats": {k: v for k, v in self.stats.items() if k != "load_seconds"},
            "tracts": columns,
            "hospitals": self.hospitals,
        }
        tmp = path + ".tmp"
        with open(tmp, "wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", compresslevel=9, mtime=0) as gz:
            gz.write(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
        os.replace(tmp, path)

    @classmethod
    def from_bundle(cls, path=BUNDLE_PATH):
        """Load the tables written by save_bundle(); takes a second or two."""
        t0 = time.time()
        with gzip.open(path, "rt", encoding="utf-8") as f:
            payload = json.load(f)
        if payload.get("version") != BUNDLE_VERSION:
            raise ValueError(f"{path} is bundle version {payload.get('version')}, expected {BUNDLE_VERSION}. "
                             "Rebuild it with `python web/api/build_data.py`.")
        self = cls.__new__(cls)
        self.raw_dir = None
        columns = payload["tracts"]
        self.tracts = [dict(zip(TRACT_FIELDS, row)) for row in zip(*(columns[name] for name in TRACT_FIELDS))]
        for t in self.tracts:
            t["mua"] = bool(t["mua"])
            t["hpsa"] = bool(t["hpsa"])
        self.hospitals = payload["hospitals"]
        self.stats = dict(payload["stats"])
        self.stats["source"] = f"bundle built {payload['built']}"
        self.stats["load_seconds"] = round(time.time() - t0, 1)
        self.states = sorted({t["state"] for t in self.tracts})
        return self

    # --- Census tracts (population + centroid) ---------------------------------

    def _load_tracts(self):
        tracts = []
        skipped = 0
        with _open(self.path("PLACES", "places_tract.csv")) as f:
            for row in csv.DictReader(f):
                point = _parse_point(row["Geolocation"])
                if point is None:
                    skipped += 1
                    continue
                tracts.append({
                    "id": row["TractFIPS"].zfill(11),
                    "state": row["StateAbbr"],
                    "county_fips": row["CountyFIPS"].zfill(5),
                    "county": row["CountyName"],
                    "lon": point[0],
                    "lat": point[1],
                    "pop": _to_int(row["TotalPopulation"]),
                    # Filled in by _attach_ruca / _attach_shortage
                    "ruca": None,
                    "density": None,
                    "mua": False,
                    "hpsa": False,
                })
        self.stats["tracts"] = len(tracts)
        self.stats["tracts_without_point"] = skipped
        return tracts

    def _attach_ruca(self):
        """Rural-urban code and population density (people per sq. mile) per tract."""
        by_id = {t["id"]: t for t in self.tracts}
        matched = 0
        with _open(self.path("RUCA", "2020-rural-urban-commuting-area-codes-census-tracts.csv")) as f:
            for row in csv.DictReader(f):
                tract = by_id.get(row["TractFIPS20"].zfill(11))
                if tract is None:
                    continue
                tract["ruca"] = _to_int(row["PrimaryRUCA"], None)
                tract["density"] = _to_float(row["PopDensity"])
                matched += 1
        self.stats["tracts_with_ruca"] = matched

    def _attach_shortage(self):
        """Flag tracts inside an active MUA/P or primary-care HPSA.

        Tract components match by 11-digit tract FIPS; whole-county components
        flag every tract in that county. County-subdivision components can't be
        mapped to tracts with this data, so they're skipped.
        """
        mua_tracts, mua_counties = set(), set()
        with _open(self.path("MUAP", "MUA_DET.csv")) as f:
            for row in csv.DictReader(f):
                if row["MUA/P Status Description"] not in ACTIVE_STATUSES:
                    continue
                kind = row["Medically Underserved Area/Population (MUA/P) Component Geographic Type Description"]
                if kind == "Census Tract":
                    mua_tracts.add(row["MUA/P Area Code"].zfill(11))
                elif kind == "Single County":
                    mua_counties.add(row["State and County Federal Information Processing Standard Code"].zfill(5))

        hpsa_tracts, hpsa_counties = set(), set()
        with _open(self.path("HPSA", "BCD_HPSA_FCT_DET_PC.csv")) as f:
            for row in csv.DictReader(f):
                if row["HPSA Status"] not in ACTIVE_STATUSES or row["Designation Type"] not in HPSA_AREA_TYPES:
                    continue
                kind = row["HPSA Component Type Description"]
                geo_id = row["HPSA Geography Identification Number"]
                if kind == "Census Tract":
                    hpsa_tracts.add(geo_id.zfill(11))
                elif kind == "Single County":
                    hpsa_counties.add(geo_id.zfill(5))

        for t in self.tracts:
            t["mua"] = t["id"] in mua_tracts or t["county_fips"] in mua_counties
            t["hpsa"] = t["id"] in hpsa_tracts or t["county_fips"] in hpsa_counties

        self.stats["tracts_in_mua"] = sum(t["mua"] for t in self.tracts)
        self.stats["tracts_in_hpsa"] = sum(t["hpsa"] for t in self.tracts)

    # --- Hospitals --------------------------------------------------------------

    def _load_hospitals(self):
        """CMS Hospital General Information, placed at its ZIP's ZCTA centroid.

        The CMS file has addresses but no coordinates. Fallbacks, in order:
          zcta   - the ZIP is a ZCTA in PLACES
          zip3   - numerically nearest ZCTA sharing the first three digits
                   (catches PO-box and single-building ZIPs)
          county - centroid of the hospital's county in PLACES
        """
        zcta = {}
        with _open(self.path("PLACES", "places_zcta.csv")) as f:
            for row in csv.DictReader(f):
                point = _parse_point(row["Geolocation"])
                if point:
                    zcta[row["ZCTA5"].zfill(5)] = point
        by_zip3 = {}
        for z in zcta:
            by_zip3.setdefault(z[:3], []).append(z)

        county = {}
        with _open(self.path("PLACES", "places_county.csv")) as f:
            for row in csv.DictReader(f):
                point = _parse_point(row["Geolocation"])
                if point:
                    county[(row["StateAbbr"], row["CountyName"].upper())] = point

        # PLACES only covers the 50 states + DC, so territory hospitals (PR, VI,
        # GU, AS, MP) have no census data to score against and are left out.
        covered_states = {t["state"] for t in self.tracts}

        hospitals = []
        quality_counts = {"zcta": 0, "zip3": 0, "county": 0, "unplaced": 0, "outside_places_states": 0}
        with _open(self.path("CMSHospital", "Hospital_General_Information.csv")) as f:
            for row in csv.DictReader(f):
                if row["State"] not in covered_states:
                    quality_counts["outside_places_states"] += 1
                    continue
                zip5 = row["ZIP Code"].strip().zfill(5)[:5]
                point, quality = zcta.get(zip5), "zcta"
                if point is None and zip5[:3] in by_zip3:
                    nearest = min(by_zip3[zip5[:3]], key=lambda z: abs(int(z) - int(zip5)))
                    point, quality = zcta[nearest], "zip3"
                if point is None:
                    point, quality = county.get((row["State"], row["County/Parish"].upper())), "county"
                if point is None:
                    quality_counts["unplaced"] += 1
                    continue
                quality_counts[quality] += 1
                hospitals.append({
                    "facility_id": row["Facility ID"],
                    "name": row["Facility Name"].strip(),
                    "address": row["Address"].strip(),
                    "city": row["City/Town"].strip(),
                    "state": row["State"],
                    "zip": zip5,
                    "county": row["County/Parish"].strip(),
                    "phone": row["Telephone Number"].strip(),
                    "type": row["Hospital Type"],
                    "ownership": row["Hospital Ownership"],
                    "emergency": row["Emergency Services"] == "Yes",
                    "rating": row["Hospital overall rating"] if row["Hospital overall rating"].isdigit() else None,
                    "counts_for_coverage": row["Hospital Type"] in COVERAGE_TYPES,
                    "loc_quality": quality,
                    "lon": point[0],
                    "lat": point[1],
                })

        # Stable feature ids: sorted by CMS Facility ID so the same hospital gets
        # the same id on every server start (map.setFeatureState needs this).
        hospitals.sort(key=lambda h: h["facility_id"])
        for i, h in enumerate(hospitals):
            h["id"] = i
        self.stats["hospitals"] = len(hospitals)
        self.stats["hospital_location_quality"] = quality_counts
        return hospitals

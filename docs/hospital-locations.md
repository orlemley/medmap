# How MedMap places hospitals on the map

MedMap draws about 5,300 hospitals. None of our data files say where they are
on a map. The CMS hospital list gives each hospital's **street address and ZIP
code**, but no latitude and longitude. This page explains how we turn those
addresses into map locations, why some addresses can't be matched even though
we have them, and what the map shows for those.

The canonical implementation is the Stage 3 ETL in
`src/optimal_hospital_placer/etl/stage3/`. It preserves the broad CMS facility
registry, uses Census matches first, and applies conservative tie,
alternate-address, and OpenStreetMap fallbacks only to unresolved hospitals.
`web/legacy_prototype/geocode_hospitals.py` is an archived frontend-prototype
implementation retained only as provenance for the fallback methodology. It is
not the application API. The production API is in
`src/optimal_hospital_placer/api/`, and the production ETL is in
`src/optimal_hospital_placer/etl/`.

## The problem this fixes

Originally every hospital was drawn at the **center of its ZIP code**, because
that was the only location we had. On the satellite view that was obviously
wrong: dots sat on fields and trees, not hospitals. We measured it on 31
Missouri hospitals: the ZIP-center dot was a median of **1.8 miles** from the
hospital, and up to **5.5 miles**.

## Why "we have the address" isn't enough

Turning an address into coordinates is called **geocoding**. Our main
geocoder is the free U.S. Census Geocoder, the same one the team's ETL uses
(`src/optimal_hospital_placer/etl/stage3/s3_facilities.py`).

The Census Geocoder does **not** look addresses up in a list of buildings.
It has a map of every street segment with the **range of house numbers**
along it (for example, "Franklin St, 60–98, east side"). It finds the segment
and estimates where the number falls. So it can only place an address if
the street and that house number are in its street map.

In the original 5,353-hospital frontend bundle, Census placed **4,617 (86.3%)**.
The other **736** failed for these reasons, none of which is a
missing address:

| Why it fails | Hospitals | Examples |
|---|---|---|
| Street or house number not in the Census street map (numbers outside the recorded range, newer or renamed streets) | 380 | "56 Franklin St, Waterbury CT" |
| The street is the hospital's own campus road (private or new, so not in the Census map) | 123 | "100 Mercy Way", "6000 Hospital Dr", "29101 Hospital Rd" |
| Highway, route or county-road address; highway numbering rarely lines up | 77 | "1400 US Highway 61", "2190 Hwy 85 N" |
| A PO box or building/suite text instead of a street address | 45 | "PO Box 550, Valdez AK", "22 Masonic Ave Bldg Sturges" |
| Ambiguous: the same address exists twice ("Tie") | 41 | "615 New Ballas Rd" is both **N** and **S** New Ballas, 1.5 miles apart |
| No street number, or the number spelled out | 41 | "One Medical Plaza", "Two St Vincent Circle" |
| Military bases and federal sites (base streets aren't in public street data) | 29 | Fort Leonard Wood, Fort Wainwright |

(Counts come from the first full run. Each hospital is counted under the
first reason that fits.)

Rewording or cleaning up the address text (dropping PO boxes and suite
numbers) doesn't fix these. We tried, and it recovered none. The address is
right; the Census street map just doesn't cover it.

## How each hospital gets its location

`geocode_hospitals.py` tries five steps in order. Each hospital keeps the
first location it gets.

| Step | What it does | Hospitals placed |
|---|---|---|
| 1. Census Geocoder (batch) | The address as CMS lists it. Lands on the street in front of the hospital. | 4,617 |
| 2. Census Geocoder (one address at a time) | For "Tie" results, asks again to get every candidate and keeps the one nearest the hospital's ZIP area. | 34 |
| 3. A second CMS address | CMS's *Provider of Services* file sometimes has the street address when the main list only has a PO box ("PO Box 589" → "103 Fram Street"). Also retries the main address with PO box and suite text removed. | 12 |
| 4. OpenStreetMap | Looks for a hospital with a matching name within 12 miles of the hospital's ZIP area (25 miles if even the ZIP wasn't found). OpenStreetMap maps hospitals as buildings or campuses, so street numbering doesn't matter. | 529 |
| 5. Approximate | Nothing matched. The hospital stays at its ZIP code's center (or county center), and the map shows it as a hollow ring. | 161 |

**Prototype-bundle result: 5,192 of 5,353 hospitals (97.0%) are at their
real location.** 161 are approximate. Stage 3 applies the same fallback ideas
to its broader registry; its run-specific counts are written to
`quality_report.json` rather than assuming these smaller-bundle totals.

The 161 that remain approximate:

| Why | Hospitals | Examples |
|---|---|---|
| Name too generic, or too different between CMS and OpenStreetMap, to match safely | 110 | "University of Missouri Health Care" (OpenStreetMap: "MU Health Care University Hospital") |
| Military, VA, federal or Indian Health Service sites | 20 | Bassett Army Community Hospital (Fort Wainwright) |
| Only a PO box, no street address anywhere | 19 | "PO Box 43" (Maniilaq Health Center, Kotzebue AK) |
| Highway or route address | 12 | "960 Hwy 71 N" |

By type: 65 acute care, 38 critical access, 33 psychiatric, 10 Department of
Defense, and a few others.

### How OpenStreetMap names are matched

Hospital names differ between sources ("YALE-NEW HAVEN HOSPITAL" vs "Yale New
Haven Hospital"). Both names are split into words. Words that don't tell
hospitals apart ("hospital", "medical", "center", "regional", "saint", …) are
dropped. The rest must overlap by at least half (Jaccard similarity ≥ 0.5). If
several OpenStreetMap hospitals qualify, the closest name wins, then the
nearest. A name made only of common words ("Community Hospital") is never
matched, since it could be anyone.

One OpenStreetMap hospital can't be two different hospitals. If two
differently named CMS hospitals pick the same one, only the better name match
keeps it, and the other stays approximate. This caught one mistake in the
full run: "Whittier Hospital Medical Center" had matched "PIH Health Hospital
- Whittier" on the word "Whittier" alone. The same hospital listed twice in CMS
(for example as both acute care and critical access) may share a location.

### How accurate is it?

- **Census Geocoder** points land on the street in front of the hospital, not
  on the building. In our satellite checks (Boone Hospital Center in Columbia,
  Phelps Health in Rolla) they were right at the main entrance road.
- **OpenStreetMap** points are the center of the hospital building or campus.
  For hospitals both sources could place, the two were a median of **0.1
  miles** apart (about 500 ft), and 90% were within a quarter mile. (Sample:
  282 hospitals in six states.)
- About 5% of that sample was more than a mile apart. Some of that is a wrong
  name match, some a wrong Census estimate. We only use OpenStreetMap where the
  Census Geocoder failed, which limits the effect.

## What the map shows

- **Solid red dot:** placed by step 1–4. The popup says which source: "street
  address", "Provider of Services file" or "OpenStreetMap".
- **Hollow red ring:** approximate (step 5). The popup says the address
  couldn't be matched and it's shown at the ZIP code's (or county's) center.
- Each hospital's `loc_quality` in the API is `address`, `address_alt`, `osm`
  (precise) or `zcta`, `zip3`, `county` (approximate), and `loc_match` records
  what it was matched to.

Distances used for scoring (how far each area is from the nearest hospital)
use these locations, so they're more accurate than before too.

## Rebuilding the archived prototype bundle

These commands reproduce the historical frontend-prototype bundle only. They
are not part of the current application or deployment workflow.

```bash
python web/legacy_prototype/build_data.py            # looks up anything not cached yet
python web/legacy_prototype/build_data.py --offline  # cached answers only, no network
```

Answers are cached in `raw/_geocode_cache/` (git-ignored, like `raw/`):

| File | Contents |
|---|---|
| `census_batch.json` | Census answers per address |
| `census_ties.json` | Candidates for "Tie" addresses |
| `openstreetmap.json` | OpenStreetMap hospitals found, and which hospitals were already searched around |

The Census steps take about a minute for all hospitals. The OpenStreetMap step
uses the free public Overpass servers, which are often busy. It asks about
60 hospitals per request and took **roughly 50 minutes (12 requests)** for the ~690
hospitals it needed. It saves after each request, so an interrupted run
resumes where it stopped.

## Sources and credit

- **U.S. Census Geocoder** (benchmark `Public_AR_Current`): public domain.
- **CMS Hospital General Information** and **Provider of Services** files:
  public domain.
- **OpenStreetMap** hospital locations: © OpenStreetMap contributors,
  available under the Open Database License (ODbL). The map already shows this
  credit, since the street map is built from OpenStreetMap too.

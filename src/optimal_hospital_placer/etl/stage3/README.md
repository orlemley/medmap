# Stage 3: geographic assembly

Builds `tracts.parquet`, `counties.parquet`, and `facilities.parquet` as GeoParquet,
using the completed stage 2 snapshot and 2023 Census TIGER/Line boundaries.
**The scripts have not been run during implementation. Runtime validation is
still required.** Raw files and stages 1/2 are read-only inputs.

## When you choose to run it

Requires Python 3.10+. From the repository root:

```powershell
py -3 -m pip install -r src/optimal_hospital_placer/etl/stage3/requirements.txt

# Download missing Census boundaries, with checksum caching. National run is large.
py -3 src/optimal_hospital_placer/etl/stage3/prepare_boundaries.py

# Include Census address geocoding, which sends public facility addresses to Census.
# No API key is used. Successful responses (including No_Match) are cached.
py -3 src/optimal_hospital_placer/etl/stage3/run_stage3.py --geocode
```

For a smaller first build, use matching state selections in both commands:

```powershell
py -3 src/optimal_hospital_placer/etl/stage3/prepare_boundaries.py --states 17
py -3 src/optimal_hospital_placer/etl/stage3/run_stage3.py --states 17 --geocode
```

**Without `--geocode`, the runner makes no network calls.** It uses existing
geocode cache entries and leaves other facilities unlocated. This can produce
mostly unlocated facilities on a first run, and corresponding zero located-site
counts. Those zeros do not establish that an area lacks healthcare facilities.
MUA/P area overlays do not require facility geocoding.

Boundaries are never downloaded implicitly by the main runner. Missing inputs
produce an actionable error. Defaults cover the 50 states and DC, not territories.
The boundary loader accepts existing ZIPs with or without downloader receipts;
it hashes all consumed files and verifies receipts when present.

## Modules

- `prepare_boundaries.py`: fetch 2023 county and state tract ZIPs, verify ZIP CRCs,
  retain receipts, and skip matching cached files.
- `s3_geography.py`: load reference polygons and join source attributes by exact
  IDs or reviewed one-to-one equivalences. Reject duplicate matched source keys.
- `s3_facilities.py`: source-to-location registry, cached optional Census batch
  geocoding, point-in-polygon assignment, and registry summaries.
- `s3_muap.py`: read the HRSA component shapes, dissolve by designation, overlay
  them with tracts/counties, and identify facilities within designation boundaries.
- `run_stage3.py`: coordinate, validate, publish a new run and successful pointer.
- `s3_common.py`: checked stage 2 catalog access, hashing, and output IO.

## Output contract

Each build has its own `data/stage3/runs/<timestamp>-<id>/` directory:

| File | Meaning |
| --- | --- |
| `tracts.parquet` | One row per selected 2023 reference tract: polygons, SVI, PLACES, RUCA, MUA/P overlays, located-registry counts. |
| `counties.parquet` | One row per selected reference county: polygons, SVI, PLACES, selected AHRF fields, MUA/P overlays, located-registry counts. |
| `facilities.parquet` | One row per conservatively resolved provider/location identity; includes coordinates or null geometry, geographic assignments, source/match flags and MUA/P boundary membership. |
| `supporting/facility_source_records.parquet` | Source-row-to-facility mappings with source identifiers and selected original attributes. Complete source records remain in stage 2. |
| `supporting/muap_designations.parquet` | Active designation polygons dissolved from components. |
| `supporting/muap_*_links.parquet` | Many-to-many tract/county/facility relationships to designations; never directly merged to inflate final table rows. |
| `supporting/*_unmatched.parquet` | Source rows not joined, with reason (out of scope, malformed ID, or no exact reference ID). |
| `supporting/hpsa_*.parquet` | Original interpreted HPSA component tables, retained separately. |
| `quality_report.json` | Coverage, unmatched IDs, facility conflicts, and limitations. |
| `manifest.json` | Input snapshot, state selection, boundary hashes, output counts/checksums, status. |
| `data_dictionary.json`, `source_reports/` | Output types plus source column rules, units, original headers, and measurement-year metadata from stage 2. |

`latest_success.json` is updated only after all three outputs validate and read
back as GeoParquet. Failed runs keep diagnostics and never replace the previous
pointer. Consumers must follow the pointer rather than glob all historical runs.
No prior outputs are deleted. Only the boundary and geocoding steps are cached;
assembly/overlay is recomputed on each run. Do not run two writers against the
same cache directory concurrently.

## Geography decisions

- Final geometry is EPSG:4326 with `geography_vintage=2023` on geographic tables.
- PLACES uses the 2025 release already in stage 2, documented for 2023 boundaries.
- RUCA joins on `tractfips23`; its older identifiers remain available as attributes.
- SVI 2022 joins on exact matching FIPS; this is explicitly recorded, not a claim
  that all 2022/2023 geometry is identical. Unmatched regions remain missing.
- AHRF's county geography is marked unverified; no redistribution is attempted.
- IDs are never padded, converted from numbers, truncated to infer a match, or
  replaced based on names. Only the state-prefix check is used for scope reporting.

For documented pure ID renumbering, `--crosswalks file.json` accepts:

```json
{
  "EXACT_SOURCE_IDENTITY_FROM_STAGE2": [
    {"source_geoid": "OLD_ID", "target_geoid": "NEW_ID", "evidence": "Reviewed equivalence reference"}
  ]
}
```

This is a template, not an actual crosswalk. Supply digit-string IDs of the correct
length. Only one-to-one mappings are allowed; source IDs must exist and target IDs
must be in the selected reference. Connecticut county reorganizations cannot be
solved by declaring arbitrary equivalences. Splits/mergers and weighting require
a separately reviewed method; this version leaves those unresolved rather than
averaging ranks, rates, or medians. Used crosswalks are saved in supporting tables.

## Facility matching and geocoding

Automatic merging requires the same CCN and exact normalized full address (case
and whitespace normalization only). Suite/unit address lines remain part of the
key. No name-only or fuzzy merging occurs. Rows without sufficient matching data
remain separate. The same CCN at different addresses is flagged for review.
An internal ID is deterministic for that matching key, not a permanent enterprise
ID across relocations. NPI and enrollment IDs live in the source mapping table.

Attribute preference: Hospital General Information, then enrollment tables, then
POS. Conflicting values are recorded; conflicting bed counts become null. Type
classification uses explicit enrollment file identities and Hospital General
Information. Uncorroborated POS codes remain unclassified, not presumed hospitals.
Operational status is not adjudicated: the default summaries are **located
registry counts**, not certified counts of currently active facilities. Hospice,
home-health and unclassified locations are flagged as possible offices.

Census batch geocoding uses 1,000 records per request, below the 10,000 limit.
Each batch gets up to five attempts for timeouts, connection errors, and HTTP
408, 429, 500, 502, 503, or 504 responses. Delays between attempts are 15, 30,
60, and 120 seconds; each attempt retains the 30-second connection and
600-second read timeouts. Retry messages identify the batch and attempt.
Other HTTP errors and invalid response contents fail immediately. If retries
are exhausted, the run stops and previously completed batches remain cached.
Only returned coordinates are used; they are assigned to our local 2023 polygons.
The current geocoder benchmark can change, so cached responses include the
benchmark, response, and retrieval timestamp. Nonmatches are retained; no postcode
centroid substitution is made. Boundary ties receive null assignments and flags.
The geocoder returns approximate street locations, not verified building entrances.

## MUA/P feature semantics

Uses `MUA_CMPPC_SHP.zip`, matching the local stage 1 inventory hash. The component
field names were inspected during implementation. Only `Designated` records are
included; the two designation types remain separate (`mua` versus `mup`).
The DBF character field `MUASRCID` contains both five- and ten-digit designation
IDs, matching the CSV identifiers. Both lengths are retained as text, including
leading zeros; IDs are never truncated or padded.
Governor's-exception designations are included in the corresponding MUA/MUP
category, with their original type retained in the designation table. Invalid
geometries are repaired explicitly and repair counts are reported. Conflicting
designation types/scores or missing active geometry cause a failure.

For each tract/county:

- `mua_designation_count`, `mup_designation_count`: distinct overlapping designations.
- `mua_boundary_area_fraction`, `mup_boundary_area_fraction`: unioned coverage,
  so overlapping designations are not counted twice.
- `muap_spatial_evaluated`: the overlay actually ran; zero then means no overlap
  with the active polygons in this snapshot.

Areas are computed in EPSG:6933 and divided by the reference polygon area. This
includes water footprint; **it is neither a land-only fraction nor a population
fraction**. MUP overlap does not designate every resident. Facility membership
indicates location only, not eligibility, utilization, or patients served.

## Deliberate review items

- AHRF defaults to a small set of county classifications from `AHRF2025geo.csv`.
  `--ahrf-columns ...` selects reviewed fields from `AHRF2025.csv` instead. Their
  stage 2 types are preserved; this does not guess variable years or convert strings.
- HPSA's component definitions are not automatically equated to tracts. HPSA
  records remain in supporting data; the AHRF county HPSA classifications are
  separate source attributes, not computed tract HPSA coverage.
- The table-level data dictionary leaves unknown measurement years null. See
  source reports and metadata; geography vintage is not measurement year.
- Validation covers unique keys, reference-row conservation, parent-child keys,
  geometry, checksums, and GeoParquet readback. It cannot establish geocoder
  accuracy, that a provider is active, or that an ID-equivalence claim is true.

Successful builds are labeled `complete_with_review_items` for these reasons.
There are no driving times, demand estimates, composite need scores or placement
rankings in this stage.

Official input references:
- https://www2.census.gov/geo/tiger/TIGER2023/TRACT/
- https://www2.census.gov/geo/tiger/TIGER2023/COUNTY/
- https://geocoding.geo.census.gov/geocoder/Geocoding_Services_API.html
- https://data.hrsa.gov/data/download?titleFilter=Shortage+Areas

# Raw data downloader

Requires Windows PowerShell 5.1 or PowerShell 7+, internet access, and sufficient disk space.
On Windows PowerShell 5.1, the script enables TLS 1.2 for HTTPS and uses basic
web parsing so Internet Explorer initialization is not required.
The script has **not been executed**; validation was limited to source research,
code review, and PowerShell syntax parsing. Live downloads remain untested.

Run these commands from the repository root when you want to download data:

```powershell
# Offline list of supported sources (no network or file writes)
./src/optimal_hospital_placer/etl/get_raw_data.ps1 -ListSources

# Resolve URLs and show the download plan; uses metadata requests, writes no files
./src/optimal_hospital_placer/etl/get_raw_data.ps1 -PlanOnly

# Start with hospital locations, shortages, and rural classifications
./src/optimal_hospital_placer/etl/get_raw_data.ps1 -Sources CMSHospital,HPSA,MUAP,RUCA

# All ten groups, with Illinois roads instead of the entire US road extract
./src/optimal_hospital_placer/etl/get_raw_data.ps1 -Sources All -OsmRegion illinois

# Selected ACS variables for every tract in Illinois and Wisconsin
./src/optimal_hospital_placer/etl/get_raw_data.ps1 -Sources ACS -AcsYear 2024 `
    -AcsGeography tract -StateFips 17,55 `
    -AcsVariables B01003_001E,B19013_001E,B17001_002E

# Include HRSA shapefiles and SVI geodatabases
./src/optimal_hospital_placer/etl/get_raw_data.ps1 -Sources HPSA,MUAP,SVI -IncludeBoundaries

# Refresh mutable source URLs even when existing files pass checksum verification
./src/optimal_hospital_placer/etl/get_raw_data.ps1 -Sources PLACES,SVI -Force
```

With no arguments, the script selects all ten groups, including the **multi-GB US
OSM extract**. `-OsmRegion` accepts `us` or a Geofabrik US state slug such as
`illinois`, `new-york`, or `district-of-columbia`. It affects only OSM.
`-StateFips` affects only ACS; the other tabular downloads remain nationwide.

Files go to `data/raw/<Source>/` relative to the repository, regardless of the
working directory. Override this with `-OutputDirectory`. Raw downloads are ignored
by Git. ZIPs stay compressed, JSON stays JSON, and no cleaning or joins occur.
If code is run as an editor selection or pasted into a console, the script searches
the current folder and its parents for the repository to determine this default.
Outside the repository, run the saved `.ps1` file or provide `-OutputDirectory`.
Explicit relative output paths are resolved against the current PowerShell folder.

## Coverage and official sources

| Source | Download scope |
| --- | --- |
| [CMS Hospital General Information](https://data.cms.gov/provider-data/dataset/xubh-q36u) | Current full CSV resolved from the provider catalog by `xubh-q36u`. |
| [CMS facilities catalog](https://data.cms.gov/provider-characteristics/hospitals-and-other-facilities) | Selected infrastructure datasets: QIES/iQIES (and legacy hospital/non-hospital POS if present), hospital, FQHC, skilled nursing, hospice, rural health clinic, and home health enrollment files. Latest CSV per matched dataset, not every catalog dataset or historical release. |
| [HRSA AHRF](https://data.hrsa.gov/data/download?data=AHRF) | 2024–2025 county and state/national CSV ZIPs and technical documentation. `-AhrfRelease` changes the release; older releases may use different filenames and require updating the resolver. |
| [HRSA HPSA](https://data.hrsa.gov/data/download?titleFilter=Shortage+Areas) | All-HPSA CSVs for primary care, dental, and mental health plus data dictionary. Optional facility points, component boundaries, and designation boundaries. |
| [HRSA MUA/P](https://data.hrsa.gov/data/download?titleFilter=Shortage+Areas) | MUA/P detail CSV and dictionary; optional designation/component shapefiles. |
| [CDC PLACES](https://www.cdc.gov/places/tools/explore-places-data-portal.html) | All measures in GIS-friendly wide CSVs for county, place, tract, and ZCTA. Use `-PlacesGeographies` to choose levels. Current-release aliases can change vintage; metadata is saved separately. Full CSV exports avoid the default API row cap. |
| [Census ACS API](https://www.census.gov/programs-surveys/acs/data/data-via-api.html) | ACS 5-year detailed tables, default 2024. County nationwide by default; tract requires explicit state FIPS. Saves variable metadata and raw JSON per state and variable batch. This is a configurable variable subset, not every ACS table. |
| [CDC/ATSDR SVI](https://svi.cdc.gov/dataDownloads/data-download.html) | Default 2022, nationwide-ranked tract and county CSVs. `-SviYear` and `-SviGeographies` select vintage/levels; `-IncludeBoundaries` also requests geodatabases. Older-year formats/availability can differ. |
| [USDA RUCA](https://www.ers.usda.gov/data-products/rural-urban-commuting-area-codes) | Discovers 2020 tract and ZIP CSV/XLSX links from the current USDA page. XLSX files include supporting documentation. |
| [Geofabrik OSM extracts](https://download.geofabrik.de/north-america/us.html) | Full US or state `.osm.pbf` data, including roads and other OSM features. Driving times require subsequent routing-engine processing; downloading alone does not calculate accessibility. Attribute OpenStreetMap contributors and follow the [ODbL](https://www.openstreetmap.org/copyright). |

ACS defaults are population (`B01003_001E`), median age (`B01002_001E`), median
household income (`B19013_001E`), people below poverty (`B17001_002E`), unemployed
people (`B23025_005E`), and households without vehicles (`B08201_002E`). Counts
are not rates. Add appropriate denominators, margins of error, and insurance,
disability, or other variables via `-AcsVariables`; consult the saved variable
metadata. Requests are batched at 49 variables plus `NAME`; join batches on their
geography fields, never row position. Keep FIPS/ZIP identifiers as strings.

## Reliability and reruns

Each run writes a timestamped manifest with URLs, status, file size, SHA-256,
notes, and errors. A receipt beside each successful file permits skipping only
when both its URL and local checksum match. This detects local corruption, but
does not check whether an upstream file at the same URL has changed: use `-Force`
for refreshes. Receipts retain the original download timestamp on cached runs.

Downloads use temporary files, retry up to `-Retries` times (default 3), and only
replace the destination after basic content checks and hashing. HTML error pages,
empty responses, invalid ZIP signatures, and invalid JSON are rejected. These
are basic transport checks, not full schema or completeness validation.
Failures do not stop independent sources; the final terminating error gives a
nonzero process exit when invoked as a script. Completed files remain available
for reruns. Do not run concurrent instances against the same output directory.

Some government endpoints may be unavailable or change their structure. Inspect
the recorded error and official source page when that happens. Different sources
have different vintages, definitions, and geographic coverage; align them before
modeling rather than assuming every county/tract identifier matches directly.

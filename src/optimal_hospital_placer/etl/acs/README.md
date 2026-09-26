# ACS preparation and stage 4 enrichment

Adds ACS attributes to a completed stage 3 snapshot. It never invokes stages
1–3, constructs a facility registry, geocodes, or performs spatial overlays.
No API key or account is required. Scripts were not executed during implementation;
only source syntax and upstream header samples were inspected.

## Run when ready

Python 3.10+; use the same environment as stage 3. From the repository root:

```powershell
python -m pip install -r src/optimal_hospital_placer/etl/acs/requirements.txt
python src/optimal_hospital_placer/etl/acs/run_acs.py
```

The runner verifies that a successful stage 3 snapshot exists before downloading,
pins that input snapshot, and downloads, prepares, then enriches. The default
input is `data/stage3/latest_success.json`. To select a particular snapshot:

```powershell
python src/optimal_hospital_placer/etl/acs/run_acs.py --stage3-run data/stage3/runs/YOUR_RUN_DIRECTORY
```

Use `--skip-download` for an offline rerun after the files have been downloaded.
For separate steps:

```powershell
python src/optimal_hospital_placer/etl/acs/download_acs.py
python src/optimal_hospital_placer/etl/acs/prepare_acs.py
python src/optimal_hospital_placer/etl/acs/enrich_acs.py
```

The main `run_etl.py` runs stages 1–3 and then this ACS pipeline as stage 4.
Use `run_acs.py` directly to add ACS to an existing stage 3 result without
rebuilding stages 1–3. Run only one ACS writer at a time.

## Inputs and scope

Pinned to the **2019–2023 ACS five-year estimates (2023 release)** and a stage 3
snapshot using 2023 geography. This is a five-year estimate, not a 2023 census.
The six selected detailed tables are:

| Table | Topic |
| --- | --- |
| B01001 | Sex by age, including total population |
| B17001 | Poverty status by sex by age |
| B19013 | Median household income in 2023 inflation-adjusted dollars |
| B27001 | Health insurance coverage by sex by age |
| B08201 | Household size by vehicles available |
| B18101 | Sex by age by disability status |

All estimate and margin-of-error columns in these tables are retained. ACS
universes differ by table; the dictionary preserves their published definitions
and hierarchical labels. For example, household vehicle counts are not person
counts. County values come from county records, never sums or averages of tracts.

The downloader fetches individual **national** files for the six tables plus
geography and table-shell metadata. Expect hundreds of MB rather than the full
multi-GB ACS archive. Even a one-state stage 3 run uses these national inputs;
enrichment retains only reference rows in the selected snapshot.

Source headers were verified as pipe-delimited text. Geography is selected only
from `1400000US` plus 11-digit tract IDs and `0500000US` plus 5-digit county IDs;
component STATE/COUNTY/TRACT fields are checked against those identifiers.

## Outputs

- `data/raw/ACS/2023/`: original files and SHA-256 download receipts.
- `data/acs/2023/tables/<table>/<fingerprint>/`: independent prepared tables,
  column dictionaries, and special-value reports.
- `data/acs/2023/runs/<fingerprint>/`: `acs_tracts.parquet`,
  `acs_counties.parquet`, dictionary, issues, and checksum manifest.
- `data/stage4/runs/<fingerprint>/`: enriched `tracts.parquet` and
  `counties.parquet`, byte-identical copy of `facilities.parquet`, ACS join report,
  unmatched-ID Parquet files, expanded dictionary, and source reports/manifests.
- `data/stage4/latest_success.json`: published only after successful validation.

Stage 3 files and its success pointer remain untouched. Its other supporting
artifacts remain at the stage 3 directory referenced in the stage 4 manifest.

Columns retain Census variable names under an `acs_` prefix: for example,
`acs_b01001_e001` is the total population estimate and `acs_b01001_m001` its
published MOE. Each numeric column has an `_annotation` companion preserving
original special-value tokens. There are also table-record-presence flags,
`acs_geography_matched`, and survey-period metadata.

## Quality and interpretation

Known missing, controlled, unavailable, and thresholded tokens become null
numeric values with original tokens retained. Blank cells also become null and
are counted in the issues report. Unexpected nonnumeric/negative values fail
preparation with the column and example values; they are not silently coerced.
MOEs for controlled estimates are not changed to zero. No derived percentages,
aggregated MOEs, vulnerability scores, or candidate rankings are added yet.

Joins require exact, unique, string GEOIDs, the matching release/reference year,
and at least one matching reference row at each level. Row counts, order, and
geometries are preserved. Unmatched reference IDs remain in the output with null
ACS attributes. Unused ACS IDs are reported within selected states. Inspect
`acs_join_report.json` before modeling: same-year ID matches do not independently
prove boundary equivalence, and there is no crosswalk/interpolation adapter.
All prior stage 3 limitations still apply.

Download retries cover timeouts, connection failures, and transient HTTP status
codes, with five attempts and increasing delays. Partial files never receive a
success receipt. Normal reruns reuse checksum-matching local downloads; delete
the relevant receipt deliberately to fetch a revised upstream file.

Preparation checkpoints depend on input checksums and parser code. Enrichment
checkpoints depend on prepared ACS, stage 3 input checksums, and enrichment code.
Output checksums are revalidated before reuse. Changed inputs produce a different
snapshot; earlier outputs remain available. Changing parser code can invalidate
all prepared-table checkpoints; adding a table leaves existing ones reusable.
The selection is configured in `tables.json`; only add tables whose numeric and
special-value conventions have been reviewed for this adapter.

## Official references

- [2023 data files](https://www2.census.gov/programs-surveys/acs/summary_file/2023/table-based-SF/data/5YRData/)
- [2023 geography and table shells](https://www2.census.gov/programs-surveys/acs/summary_file/2023/table-based-SF/documentation/)
- [Census table-based summary-file guide](https://www.census.gov/programs-surveys/acs/data/summary-file.html)

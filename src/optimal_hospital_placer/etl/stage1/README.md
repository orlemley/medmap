# Stage 1: prepare source tables

Python 3.10+ only. Run the single entry point; it calls inventory and conversion
modules in order. None of these files have been executed during implementation.
Runtime conversion remains untested.

From the repository root, when you choose to run it:

```powershell
py -3 -m pip install -r src/optimal_hospital_placer/etl/stage1/requirements.txt
py -3 src/optimal_hospital_placer/etl/stage1/run_stage1.py

# Or prepare a smaller selection:
py -3 src/optimal_hospital_placer/etl/stage1/run_stage1.py --sources CMSHospital PLACES SVI RUCA
```

This is the preparation stage after the existing download step. It performs no
network requests, changes no raw files, and invokes no PowerShell scripts.

## Responsibilities

1. `inventory.py`: inventory raw sources, sizes, source receipts, SHA-256 hashes,
   and ZIP member names. Reject checksum mismatches against existing receipts.
   Inventory OSM PBF by size/time and receipt only; do not reread its multi-GB
   contents or claim its receipt hash was verified.
2. `convert.py`: stream standalone CSVs and CSV members of ZIPs into Zstandard
   compressed Parquet. Each source file/member gets its own table. AHRF's full
   county file and thematic subsets intentionally remain separate.
3. `run_stage1.py`: orchestrate the modules, check input stability, write reports,
   and publish a latest-success pointer only if all selected inputs succeeded.

All CSV values remain **strings**, including empty strings, whitespace, leading
zeros, dates, percentages, and sentinel codes such as `-999`. Nothing is imputed,
rounded, deduplicated, geographically interpreted, or cast to numeric types.
Only column names are normalized to lowercase snake_case, with collision suffixes.
Every original column name/position is preserved in a companion schema JSON.
This also handles the trailing whitespace in the PLACES mobility header.

The three HRSA HPSA detail exports have an empty trailing header from an extra
comma. Stage 1 removes only that empty header (and a matching empty trailing field
if present), recording the repair in the schema sidecar. Populated extra fields
are never discarded.

Rows with an unexpected field count fail that table; they are never silently
skipped. Malformed encodings fail explicitly. Output footer row/column counts are
checked against the CSV parser. Source row order is preserved within each file.
These are structural checks, not validation of the scientific meaning of values.

## Output contract for stage 2

```text
data/stage1/
  latest_success.json
  runs/<timestamp>-<unique-id>/
    run.json
    inventory.json
    issues.json
    tables.json
    tables/<source>/<name>--<identity-hash>.parquet
    tables/<source>/<name>--<identity-hash>.schema.json
```

Each execution creates a new run directory; it does not overwrite previous tables
or reuse a previous run. Partial runs retain successful tables for inspection but
do not change `latest_success.json`. Stage 2 should follow that pointer and use
`tables.json`, not glob across all runs (which would double-count snapshots).
Inspect the pointer's `sources` when running with a subset. Raw paths in the
inventory are references, so retain the raw directory for stage 2.

Schema sidecars include column mappings, row counts, per-column empty-string
counts, encoding, and input/output checksums. `inventory.json` retains source
receipts and metadata-file locations. Raw JSON metadata, Excel workbooks, PDFs,
Word documents, shapefile ZIPs, and OSM PBF remain reference-only assets. They are
not duplicated or expanded. ZIP members are streamed rather than extracted.

## Encoding overrides

Default: strict `utf-8-sig` (UTF-8 with or without BOM). The eight known legacy
CMS/RUCA files listed in `convert.py` use explicit `cp1252` defaults; iQIES and
other inputs retain UTF-8. The chosen encoding is recorded per table. If a source fails decoding,
inspect its actual encoding, then supply `--encoding-config path/to/encodings.json`.
The JSON maps a source name (e.g. `CMSFacilities`) or the exact input identity from
`issues.json` to a Python encoding name (e.g. `cp1252`). Per-file/member overrides
take precedence over source overrides, which take precedence over built-in defaults.
There is no silent replacement of bytes.

Use `--raw-dir`, `--output-dir`, or `--batch-size` if needed. The default batch size
is 1,000 rows to limit memory with wide AHRF files. Default directories are resolved
from the runner's location, not the shell's current folder.

## Later stages

Stage 2 handles source interpretation before geography:

- Interpret source-specific missing values, types, units and measurement years.
- Apply reviewed variable rules and produce typed source tables and quality reports.

Stage 3 handles geography and final assembly:

- Choose/align tract and county geographic vintages (including RUCA 2020 vs 2023).
- Select AHRF variables and avoid double-counting thematic subsets.
- Assign stable facility identities, deduplicate, geocode, and resolve care sites.
- Read MUA/P/HPSA shapes and distinguish population from area designations.
- Join sources, compute rates, aggregate, build routing/accessibility features.
- Publish `tracts.parquet`, `facilities.parquet`, and `counties.parquet`.

The stage 1 Parquet files are deliberately source-specific staging data, not those
three final analytical tables. ACS contributes metadata only; no API key is used.

# Stage 2: interpret source tables before geography

Python 3.10+. These files have not been run during implementation. No geographic
alignment, spatial joins, geocoding, routing, cross-source facility matching, or
aggregation occurs. The final tracts/facilities/counties tables belong to stage 3.

When you are ready, from the repository root:

```powershell
py -3 -m pip install -r src/optimal_hospital_placer/etl/stage2/requirements.txt
py -3 src/optimal_hospital_placer/etl/stage2/run_stage2.py
```

The runner reads `data/stage1/latest_success.json` and requires a completed stage 1
run with zero issues. It does not run stage 1 or the downloader. Use `--stage1-run`
to select another completed run; `--stage1-dir`, `--output-dir`, `--batch-size`, and
`--rules` are optional. Relative CLI paths use your current directory.

## What gets prepared

| Source | Automatic interpretation |
| --- | --- |
| SVI | Numeric estimate/MOE/percentage/ranking/flag columns; documented -999 becomes null; geography and labels stay strings. |
| PLACES | Population counts, prevalence percentages, and confidence intervals as `{lower, upper}` structs. Crude and adjusted measures remain distinct. |
| CMS hospitals | Yes/No and Y/N service fields, ratings, and measure counts. Explicit Not Available/Not Applicable values become null in these fields only. |
| CMS facilities | Selected named bed-count columns; Not Applicable/Not Available become null. Provider IDs, enrollment IDs, service codes, and addresses remain unchanged strings. |
| HPSA | Selected scores (NA becomes null), quantities, poverty percentage, designation/withdrawal dates. Ratio goals such as 4000:1 remain text. Negative published quantities remain numeric; they are not guessed to be missing. |
| MUA/P | IMU score, selected percentages and dates. Designations and component identities are not merged or deduplicated. |
| RUCA | Population, land area, density. Classifications and all geographic vintage columns remain strings. |
| AHRF | Preserved as strings pending explicit per-variable dictionary rules. Full and thematic tables remain separate. |

Blank/whitespace-only cells become null. Nonblank string values retain their
original whitespace and leading zeros. No automatic ID padding, case conversion,
address cleanup, row deletion, imputation, or source merging is performed.
Stage 1 remains the exact raw-value reference. Every output row adds
`_stage2_source_table` and `_stage2_source_row` (1-based data row, excluding header).
`_stage2_quality_flags` contains JSON annotations when a row has an exceptional
value; otherwise it is null. These include the source column and original value.

HPSA poverty percentages outside 0-100 (or otherwise unparseable) become null
with a warning, original value in the row flag, and a report entry. Values are
never clipped, rescaled, or silently accepted as valid percentages. This policy
is scoped to this field; other invalid values still reject the affected table.

SVI margin-of-error values of -555555555 (including .0/.00 variants) become null
with a `controlled_estimate_moe` annotation, rather than being interpreted as
negative uncertainty. This is distinct from the ordinary -999 missing sentinel.
The annotation follows the [Census explanation](https://www.census.gov/data/developers/data-sets/acs-1year/notes-on-acs-estimate-and-annotation-values.html).

Rules live in `stage2_rules.py`, separate from the batch converter and runner.
They are intentionally conservative. Unreviewed columns are retained and listed
for review, rather than being guessed from samples. A successful run means that
the applied rules passed; it does not mean every retained column is interpreted.
Measurement years remain unknown unless explicitly configured. Source receipt
dates and filenames are not treated as variable measurement years.

SVI missing-value rule reference:
https://svi.cdc.gov/map25/data/docs/SVI2022Documentation_ZCTA.pdf
PLACES measure/interval context:
https://www.cdc.gov/places/faqs/index.html

## Reviewed variable overrides (including AHRF)

Supply a JSON object with `sources` and/or `tables`. Each maps an exact source
name or input identity (from stage 1 tables.json) to column rules. Example:

```json
{
  "sources": {
    "CMSHospital": {
      "hospital_overall_rating": {
        "type": "int64", "minimum": 1, "maximum": 5,
        "missing": ["Not Available", "Not Applicable"], "unit": "stars"
      }
    }
  }
}
```

Supported types: string, int64, float64, bool (Yes/No or Y/N), date, interval.
Missing tokens are exact after trimming/case folding, not substring matches.
Other properties: minimum, maximum, unit, measurement_year. Table rules override
source rules, which override built-ins. Unknown scope/column names are rejected.
Use AHRF technical documentation to author exact column rules; do not apply a
numeric rule indiscriminately to identifiers or assume all AHRF negative values
are missing. This review is still stage 2 work and does not require geography.

## Outputs and validation

Each run writes a new `data/stage2/runs/<timestamp>-<id>/` directory:

- `tables/*.parquet`: source-specific typed tables, no rows dropped.
- `tables.json`: source identity, input/output checksums, row counts and paths.
- `reports/*.json`: original column mapping, applied rules, counts of present,
  blank, sentinel and invalid cells, and up to 100 invalid-cell examples per table.
- `source_inventory.json`: stage 1 provenance and paths to reference assets.
- `rules_overrides.json`, `issues.json`, `run.json`: configuration and run status.

Stage 1 hashes are checked before and after conversion. Numeric bounds, dates,
finite values, integer precision, interval ordering, and row conservation are
validated. Except for the explicitly flagged HPSA poverty rule above, invalid
cells cause the entire affected output table to be rejected. Warning counts are
included in table reports, tables.json, run.json, and the console summary.
Other tables continue, but a failed run
never changes `latest_success.json`. Previous outputs and all raw files remain
untouched. New runs reprocess their inputs; no conversion cache is implemented.

Stage 3 should read the latest-success pointer and manifest, not glob all runs.
It will select geographic vintages, resolve facility identities and locations,
interpret geographic designation coverage, join sources, and build the final
analytical tables. Road accessibility can remain a separately cached later task.

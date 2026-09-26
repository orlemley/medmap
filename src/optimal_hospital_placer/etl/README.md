# Run all four ETL stages

Requires Python 3.10+, the dependencies in each stage's `requirements.txt`,
existing raw downloads in `data/raw`, and prepared TIGER boundaries (see
[stage 3 instructions](stage3/README.md)). Install the ACS dependencies in
`acs/requirements.txt` too. The runner downloads missing ACS files during stage 4;
other raw inputs and boundaries must already be prepared. Use
`--skip-acs-download` to require cached ACS inputs instead.

From the repository root:

```powershell
python src/optimal_hospital_placer/etl/run_etl.py

# Also geocode addresses that are missing from the existing cache:
python src/optimal_hospital_placer/etl/run_etl.py --geocode

# Restrict the final geographic assembly to Illinois:
python src/optimal_hospital_placer/etl/run_etl.py --states 17 --geocode
```

Runs stages 1, 2, 3, then ACS enrichment (stage 4) using the same Python interpreter, showing each stage's
output live. Each stage receives the successful snapshot from the preceding
stage. A failure stops the pipeline before any later stage starts.

Every invocation rebuilds stages 1–3 in new run directories. ACS preparation
reuses its checksum-verified checkpoints. Previous
outputs remain intact, and stage 3 reuses the geocode cache. This runner does not
add checkpoint resumption. Stage 3 retries temporary geocoding failures as
described in its README. Avoid concurrent ETL runs using the
same output directories or cache.

The final directory printed by the runner contains `tracts.parquet`,
`counties.parquet`, and `facilities.parquet`. Without `--geocode`, only cached
facility coordinates are available. `--boundary-dir` and `--geocode-cache`
override the standard reference directories. For other stage-specific options,
use the individual stage runners.

The runner was not executed during implementation.

## Add ACS without rerunning stages 1–3

Use the independent [ACS pipeline](acs/README.md) to enrich a completed stage 3
snapshot with key-free ACS bulk data:

```powershell
python src/optimal_hospital_placer/etl/acs/run_acs.py
```

This publishes new stage 4 outputs and carries facilities forward unchanged.

# Run the complete ETL pipeline (Stages 1–8)

Requires Python 3.10+, existing raw downloads in `data/raw`, and prepared TIGER boundaries (see
[stage 3 instructions](stage3/README.md)). By default, the runner first asks the active Python
interpreter's pip to resolve and install every stage's `requirements.txt` in one
transaction. Use a project virtual environment so these packages stay isolated;
`--skip-dependency-install` opts out for an already provisioned or offline environment.
The runner downloads missing ACS files during stage 4;
other raw inputs and boundaries must already be prepared. Use
`--skip-acs-download` to require cached ACS inputs instead.

From the repository root:

```powershell
# Reproduce the latest large nationwide profile (about 34k Stage 8 sites):
python src/optimal_hospital_placer/etl/run_etl.py

# Also geocode addresses that are missing from the existing cache:
python src/optimal_hospital_placer/etl/run_etl.py --geocode

# Restrict the final geographic assembly to Illinois:
python src/optimal_hospital_placer/etl/run_etl.py --states 17 --geocode
```

Runs Stages 1–5, the Stage 6A screen, and Stages 6–8 using the same Python
interpreter, showing every exact child command. Each stage receives the newly
successful snapshot from the preceding stage. A failure stops the pipeline
before later stages begin.

The default large-sample profile matches the most recent successful manifests:

- Stage 6A keeps up to 300 sites per state plus the top 15% and severe-access cases.
- Stage 6 generates two candidate points per shortlisted tract.
- Stage 7 writes 3,000 finalists and 100 routing-refinement sites.
- Stage 8 reads `top-sites` with no maximum, preserving the full discoverable
  candidate pool rather than only the 3,000 finalist subset.

All of these thresholds are exposed by `--help`; command-line overrides are
recorded in `data/etl/latest_success.json` with every published run directory.
Nationwide runs also stop if Stage 6A falls below 10,000 shortlisted tracts or
Stages 6/8 fall below 20,000 sites. This catches accidental sample collapse;
`--allow-small-output` disables the guard, and `--states` disables nationwide
floors automatically.

Every invocation rebuilds the stages in new run directories. ACS preparation
reuses its checksum-verified checkpoints. Previous
outputs remain intact, and stage 3 reuses the geocode cache. This runner does not
add checkpoint resumption. Stage 3 retries temporary geocoding failures as
described in its README. Avoid concurrent ETL runs using the
same output directories or cache.

The final directory printed by the runner is the Stage 8 run containing final
candidates, service recommendations, travel-access bands, and the precise-routing
queue. Without `--geocode`, only cached facility coordinates are available.
`--boundary-dir` and `--geocode-cache` override the reference directories.

The runner was not executed during implementation.

## Add ACS without rerunning stages 1–3

Use the independent [ACS pipeline](acs/README.md) to enrich a completed stage 3
snapshot with key-free ACS bulk data:

```powershell
python src/optimal_hospital_placer/etl/acs/run_acs.py
```

This publishes new stage 4 outputs and carries facilities forward unchanged.

# Run the complete ETL pipeline (Stages 1–8)

Requires Python 3.10+ and existing raw downloads in `data/raw`. By default, the runner first asks the active Python
interpreter's pip to resolve and install every stage's `requirements.txt` in one
transaction. Use a project virtual environment so these packages stay isolated;
`--skip-dependency-install` opts out for an already provisioned or offline environment.
Before Stage 3, the runner downloads and checksum-caches the required Census
TIGER 2023 county and tract boundaries. It downloads missing ACS files during
Stage 4. Other raw inputs must already exist. Use `--skip-boundary-download`
or `--skip-acs-download` to require the corresponding cached inputs instead.

Successful stages are checkpointed by their immutable input run, parameters,
relevant Python source hash, and (for Stage 1) raw-file size/timestamp inventory.
An identical repeat reuses each validated completed run and republishes its
pointer instead of producing duplicate output. Use `--force-stage stage5` to
rebuild one stage (changed output automatically invalidates downstream keys),
`--force-stage all` or `--no-stage-cache` for a clean rebuild, and
`--force-dependency-install` to bypass the requirements checkpoint. The runner
does not inventory the optional nationwide OSM PBF because the current fast
travel model never consumes it; standalone Stage 1 can still inventory OSM.

The runner stores operational run references relative to the repository, such
as `data/stage8/runs/<id>`. At startup it also migrates resolvable legacy
`latest_success.json` pointers containing another checkout's absolute Windows
path. Absolute paths printed in the console are only the commands executing on
the current computer; they are not persisted as cross-machine run pointers.

From the repository root:

```powershell
# Reproduce the latest large nationwide profile (about 34k Stage 8 sites):
python src/optimal_hospital_placer/etl/run_etl.py

# Missing hospital addresses are geocoded by default because Stage 6 requires
# authoritative hospital coordinates:
python src/optimal_hospital_placer/etl/run_etl.py

# Restrict the final geographic assembly to Illinois:
python src/optimal_hospital_placer/etl/run_etl.py --states 17
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

Matching completed stages are reused from validated checkpoints. Previous
outputs remain intact, and Stage 3 reuses its persistent geocode cache. Stage 3
retries temporary geocoding failures as described in its README. Avoid concurrent
ETL runs using the same output directories or cache.

The final directory printed by the runner is the Stage 8 run containing final
candidates, service recommendations, travel-access bands, and the precise-routing
queue. `--no-geocode` is an explicit offline/cache-only mode; it succeeds only
when the existing cache still produces at least one located hospital.
`--boundary-dir` and `--geocode-cache` override the reference directories.

The runner was not executed during implementation.

## Add ACS without rerunning stages 1–3

Use the independent [ACS pipeline](acs/README.md) to enrich a completed stage 3
snapshot with key-free ACS bulk data:

```powershell
python src/optimal_hospital_placer/etl/acs/run_acs.py
```

This publishes new stage 4 outputs and carries facilities forward unchanged.

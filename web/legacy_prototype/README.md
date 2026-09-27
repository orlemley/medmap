# Archived frontend prototype

This directory is retained only for historical provenance and for three
geocoding helper functions imported by `addresses/get_addr.ipynb`.

It is **not** the MedMap application API and is not used by the current Vite
frontend, Docker image, deployment, or ETL runner.

The authoritative implementation is:

- API: `src/optimal_hospital_placer/api/`
- ETL: `src/optimal_hospital_placer/etl/`
- Frontend: `web/src/`

`server.py`, the placeholder optimizer, and `medmap_data.json.gz` belong to an
earlier prototype architecture. Do not use them to run or evaluate the current
application.

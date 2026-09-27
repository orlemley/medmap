# Precise routing after Stage 7

Do **not** put nationwide Valhalla back into Stage 6.

Recommended final architecture:

1. Stage 6 fast produces tract-level candidate-site features with `routing_refined=false`.
2. Stage 7 evaluates site x hospital-configuration combinations and selects a very small finalist set.
3. A finalist refinement job performs exact road routing only for those unique sites.

For each finalist site (or a tiny cluster of finalists within roughly 20-30 miles):

- identify demand points within a generous straight-line radius;
- identify existing hospitals within a larger straight-line radius;
- derive a **local** OSM extract around that finalist only;
- build a temporary Valhalla graph for that local area;
- road-snap the finalist;
- calculate exact candidate-to-demand and demand-to-existing-hospital matrices;
- optionally generate 15/30/45/60-minute isochrones for MapLibre;
- overwrite/augment the finalist's approximate Stage-6 fields with refined fields;
- set `routing_refined=true` and `travel_time_model=valhalla_road_network`;
- delete the temporary graph before moving to the next finalist/cluster.

This means five finalists in five different parts of the country use five small local routing workspaces, never one rectangle spanning all five.

The precise refinement belongs after Stage 7 because Stage 7 may find that several hospital configurations share the same site. Route each unique site once, not once per configuration.

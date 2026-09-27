# MedMap Features

## Scoring & Ranking
- **Live re-ranking**: Move a slider and the sites re-rank right away, with no pipeline rerun.
- **Seven weighted factors**: People helped, remoteness, bed shortage, community need, service demand, right size, value for cost.
- **Presets**: One-click mixes: Most people, Remote areas, High-need communities, Best value.
- **Shares add to 100%**: Raising one weight scales the others down to fit.
- **Reset weights**: Go back to the default mix in one click.
- **Score breakdown**: See how many points each factor adds to a site's score.

## Hospital Modeling
- **Configuration optimizer**: Tests several hospital sizes and setups for each site and picks the best.
- **Right-sizing penalty**: Lowers the score of hospitals too big for local demand.
- **Alternate configurations**: Shows the setups that weren't picked, for comparison.
- **Cost estimates**: Models capital and operating cost for each configuration.
- **Service recommendations**: Scores need for 11 services (ER, ICU, maternity, stroke, dialysis, and others).
- **Service gaps**: Flags services an area needs that the base hospital design leaves out.

## Access Analysis
- **Multi-threshold access**: Counts population, hospitals and beds within 15, 30, 45 and 60 minutes.
- **Newly served population**: Counts people who would newly be within 30 minutes of a hospital.
- **Drive-time savings**: Adds up drive minutes saved across the population.
- **Routing refinement**: Uses real road routing for the finalists and estimates for the rest.

## Filters
- **State filter**: Show the whole U.S. or one state, with a site count for each.
- **Service filter**: Require certain services, matching all of them or any one.
- **Bed range**: Set a minimum and maximum bed count.
- **Minimum score**: Hide sites below a chosen score.
- **Routing filter**: Show routing-refined sites, estimated sites, or both.
- **Result count**: Show from 1 to 500 sites.
- **Geographic spreading**: Keeps the top results from crowding into one area.
- **Hospital type filter**: Show or hide existing hospitals by type.

## Map
- **Recommended sites panel**: Ranked, collapsible list; click a site to fly to it.
- **Follow the map**: Re-ranks sites for the area on screen after each pan or zoom.
- **Street / satellite toggle**: Switch between the OpenFreeMap street map and USGS aerial photos.
- **Population heatmap**: Shows all population, or only people far from existing care.
- **Layer toggles**: Turn hospitals, recommended sites and the heatmap on or off.
- **Hospital popups**: Show name, type, address, ER status and rating.
- **Approximate location flags**: Mark hospitals placed at a ZIP or county center.
- **Candidate detail panel**: Full breakdown of access, services, configuration and routing for a site.
- **Legend**: Collapsible and closable, and updates with the map mode.
- **Hover highlight**: Hovering a list row highlights that site on the map.

## Usability
- **Shareable URLs**: Weights, filters and region are saved in the link.
- **Remembered map view**: Keeps your basemap, heatmap and follow-map choices between visits.
- **Dark / light theme**: Follows the system setting, can be toggled, and doesn't flash on load.
- **Text size control**: A− / A+ buttons scale the map page text.
- **Mobile layout**: Panels start collapsed on phones and fold away after you pick a site.
- **Debounced updates**: Waits briefly while you adjust controls, then cancels outdated requests.
- **Accessibility**: ARIA labels, live status messages and keyboard-friendly controls.
- **API-down help**: Shows setup help when the backend can't be reached.
- **Home & About pages**: Explain the method, data sources and team.

## Backend & Data
- **FastAPI + DuckDB API**: Typed endpoints that query Parquet data with SQL.
- **Dynamic SQL scoring**: Builds weighted scores inside each query.
- **Tract de-duplication**: Keeps one candidate per census tract.
- **Multi-stage ETL**: Stages 1–8 cover ingest, cleaning, geocoding, candidates, routing, optimization and services.
- **ACS enrichment**: Adds Census demographics and vulnerability data.
- **Geocoding fallbacks**: Falls back from Census to OSM, then ZIP, then county center.
- **Docker deployment**: Container setup with prepared runtime data.

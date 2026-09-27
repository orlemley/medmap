# Try it Now

## Live Cloudflare Link

link

# MedMap

**MedMap is an interactive hospital-planning platform that identifies communities where a new hospital could have the greatest impact.**

Rather than ranking locations from a single statistic such as population or distance to the nearest hospital, MedMap combines healthcare access, existing capacity, community vulnerability, travel burden, facility size, service needs, and estimated cost into a nationwide site-selection model. The resulting candidates can then be explored and **re-ranked interactively** according to the priorities of a planner, health system, or community.

The project consists of a multi-stage Python geospatial/data pipeline, an analytical FastAPI + DuckDB backend, and an interactive React + MapLibre interface.

## What MedMap actually models

For every candidate community, MedMap evaluates the effect of placing a hospital there against the healthcare system that already exists.

The model tracks factors including:

- how many people would experience a shorter trip to a hospital;
- how many people would become newly accessible within specific travel-time windows;
- population-weighted drive minutes saved;
- existing hospital and bed capacity around the site;
- social and economic vulnerability within the surrounding catchment;
- distance and modeled travel time to existing hospitals;
- whether the proposed hospital is appropriately sized for local demand;
- which clinical services are particularly well matched to the area's needs; and
- estimated benefit relative to the cost of the proposed hospital configuration.

Instead of producing one opaque recommendation, MedMap preserves these components separately so that users can inspect *why* a location ranks highly and change the assumptions used to rank it.

## Interactive multi-objective optimization

One of MedMap's central features is **live re-ranking of candidate sites**.

The final score contains seven independently adjustable dimensions:

- **People helped** — combines access improvements with the population newly brought within a 30-minute hospital-access window.
- **Remoteness** — rewards locations where residents currently face long hospital travel times.
- **Bed shortage** — measures local hospital-capacity gaps.
- **Community need** — incorporates socioeconomic and demographic vulnerability in the site's catchment area.
- **Service demand** — measures how strongly local conditions support the clinical services associated with a site.
- **Right size** — evaluates whether the proposed hospital's bed count matches modeled unmet demand and whether the surrounding market can support it.
- **Value for cost** — compares modeled benefits such as access improvement and capacity added with estimated capital cost.

The API constructs the weighted score dynamically in DuckDB, so changing the weights does not require rerunning the expensive data pipeline. The frontend exposes these dimensions directly, along with presets such as **Most people**, **Remote areas**, **High-need communities**, and **Best value**.

This makes MedMap useful not just for finding a single "best" site, but for exploring how the answer changes when the definition of *best* changes.

## Hospital configuration optimization

MedMap does not assume that every candidate should receive the same hospital.

The Stage 7 optimizer expands each physical site into multiple possible hospital configurations and evaluates each configuration separately. It models:

- total beds;
- ICU capacity;
- emergency-department capacity;
- available service lines;
- estimated capital cost;
- operating-cost characteristics;
- minimum viable catchment population; and
- how closely the proposed capacity matches the modeled local bed shortage.

A configuration-fit model compares the size of each proposed facility with local unmet capacity, market support, and access conditions. Configurations that appear substantially oversized for their communities are explicitly penalized.

The system then selects the strongest configuration for each physical location while retaining the alternatives, which can be inspected from the application's candidate-detail view.

## Clinical service recommendations

MedMap also generates **site-specific service recommendations** rather than treating a hospital as a generic collection of beds.

The implemented service model evaluates demand for:

- Emergency Care
- ICU
- General Surgery
- Maternity
- Cardiology
- Stroke Care
- Behavioral Health
- Pediatrics
- Advanced Imaging
- Oncology
- Dialysis

Each service has its own need model based on relevant combinations of population, demographics, vulnerability, existing access, capacity, isolation, and facility scale.

For example, stroke and cardiology scores place more emphasis on older populations, while pediatrics places greater emphasis on the local under-18 population. Behavioral-health need incorporates vulnerability, poverty, insurance coverage, and access conditions.

The pipeline also distinguishes between a service that the chosen hospital archetype already includes and a **service gap**—a service that local conditions strongly support but that is absent from the base configuration.

## Travel-access analysis

The data pipeline models access at multiple travel-time thresholds rather than relying on a single radius around each hospital.

For each candidate, MedMap stores access statistics at:

**15, 30, 45, and 60 minutes**

including:

- total population within the travel window;
- population newly gaining access;
- existing hospitals;
- existing beds; and
- modeled travel distance.

The candidate model also calculates population-weighted travel-time savings by comparing travel to the proposed hospital with the best existing option for nearby population centers.

This allows a site to receive credit not only when it serves a completely unserved area, but also when it substantially reduces the travel burden for people who technically already have access.

## Geographic diversification

A purely numerical ranking can easily return many neighboring points representing essentially the same opportunity. MedMap contains explicit logic to prevent this.

For interactive maps, results can be diversified spatially based on map scale. For optimization requests, the backend first removes duplicate candidates from the same census tract and then applies geographic separation to the larger ranked candidate pool.

As a result, a "top 30" list can represent distinct communities and planning opportunities rather than thirty nearly identical points clustered around one high-scoring area.

Users can turn geographic spreading on or off depending on whether they want a broad national view or the strict underlying score order.

## Interactive map and candidate inspection

The React frontend turns the analytical model into an explorable planning interface.

Users can:

- view existing hospitals and recommended candidate sites together;
- display a population/access heatmap;
- switch between street and satellite imagery;
- filter candidates by state;
- require specific clinical services;
- require either **all** or **any** selected services;
- filter by proposed bed capacity;
- set a minimum score;
- distinguish estimated from routing-refined results;
- change the number of displayed candidates;
- enable or disable geographic diversification; and
- optionally make recommendations follow the current map viewport.

Selecting a candidate exposes considerably more than its final score. The details panel includes the recommended hospital configuration, proposed bed count, recommended services, travel-model information, access at each time threshold, service-level scores and gaps, and alternate hospital configurations.

## Shareable scenarios

MedMap's ranking state is encoded into the URL.

Weights, region selection, service filters, bed limits, minimum score, diversification settings, and other model choices can therefore be shared as a link. Two users can open the same planning scenario and see the same assumptions instead of trying to reproduce a set of controls manually.

The interface also debounces model updates and cancels outdated API requests, allowing users to experiment quickly without an old, slower request overwriting a newer set of preferences.

## Data pipeline and architecture

MedMap separates expensive geospatial processing from interactive analysis.

The ETL pipeline prepares and combines data from sources including Census/ACS population and demographic information, hospital/facility data, geographic boundaries, healthcare-access indicators, and location/routing information. Later pipeline stages construct candidate locations, model existing access, calculate site-level access improvements, evaluate hospital configurations, generate service recommendations, and publish the final analytical dataset.

The web application does **not** rerun those computations every time a slider moves. The final outputs are stored as Parquet datasets and queried directly with **DuckDB**, while **FastAPI** provides typed endpoints for optimization, mapping, site details, services, access bands, hospital configurations, hospitals, and population data.

This gives MedMap a useful division of labor:

**offline pipeline → analytical Parquet snapshot → DuckDB/FastAPI → interactive React map**

The architecture allows relatively complex nationwide calculations to be performed ahead of time while keeping interactive re-ranking lightweight.

## Example use cases

MedMap can support several different planning questions without requiring a different model for each one.

A **state or rural-health planner** could emphasize remoteness and community need to identify isolated populations with poor existing access.

A **hospital system** could emphasize capacity, configuration fit, and cost efficiency when comparing potential expansion markets.

A **public-health organization** could filter specifically for sites with strong modeled need for services such as maternity care, behavioral health, dialysis, or stroke care.

A **researcher or policymaker** could change the scoring weights and inspect how sensitive recommended locations are to different definitions of healthcare need.

And because the individual score components remain visible, the system can be used to investigate *why* a location is recommended rather than treating the model's output as a black box.

## Built with

- **Python, Pandas, GeoPandas, NumPy** — geospatial ETL and analytical modeling
- **Parquet** — processed analytical datasets
- **DuckDB** — fast analytical queries and dynamic candidate scoring
- **FastAPI + Pydantic** — typed optimization and map APIs
- **React + Vite** — interactive frontend
- **MapLibre GL JS** — map visualization
- **OpenFreeMap / OpenStreetMap** — basemap data
- **USGS imagery** — satellite/aerial map view

## Why we built it

Deciding where healthcare infrastructure should go is inherently a multi-objective problem. The location that reaches the most people is not necessarily the location with the worst existing access, the greatest shortage of beds, the most vulnerable population, or the best return on a limited construction budget.

MedMap is designed around that tension.

Instead of hiding those tradeoffs inside one fixed ranking, it computes them separately and gives users an interactive way to explore them—while still grounding every recommendation in the same underlying nationwide healthcare-access model.
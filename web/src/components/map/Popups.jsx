import { WEIGHTS } from "../../lib/constants.js";
import { fmt } from "../../lib/format.js";

// How each hospital's position was found (web/api/geocode_hospitals.py,
// docs/hospital-locations.md). Approximate ones are drawn as hollow rings.
const LOCATION_NOTES = {
  address: { text: "Located from its street address (U.S. Census Geocoder)." },
  address_alt: { text: "Located from its street address in CMS's Provider of Services file (U.S. Census Geocoder)." },
  osm: { text: "Located from OpenStreetMap's map of this hospital." },
  census_street_interpolation: { text: "Located from its street address (U.S. Census Geocoder)." },
  census_tie_resolved: { text: "Located by resolving an ambiguous U.S. Census Geocoder address match." },
  census_alternate_address: { text: "Located from an alternate address linked by its exact CMS identifier." },
  openstreetmap_hospital: { text: "Located from a conservatively matched OpenStreetMap hospital feature." },
  zcta: { approximate: true, text: "Approximate location: its address couldn't be matched to a map, so it's shown at the center of its ZIP code." },
  zcta_centroid: { approximate: true, text: "Approximate display location: no authoritative point was found, so it is shown at its ZIP area's center and excluded from access calculations." },
  zip3: { approximate: true, text: "Approximate location: its address couldn't be matched to a map, so it's shown at the center of a nearby ZIP code." },
  county: { approximate: true, text: "Approximate location: its address couldn't be matched to a map, so it's shown at the center of its county." },
};

function HospitalItem({ h }) {
  return (
    <div className="popup-item">
      <h3>{h.name}</h3>
      <p className="sub">{h.type}</p>
      <dl>
        <dt>Address</dt>
        <dd>{h.address}<br />{h.city}, {h.state} {h.zip}</dd>
        <dt>Phone</dt><dd>{h.phone}</dd>
        <dt>Ownership</dt><dd>{h.ownership}</dd>
        <dt>Emergency</dt><dd>{h.emergency ? "Yes" : "No"}</dd>
        <dt>CMS rating</dt><dd>{h.rating ? `${h.rating} / 5` : "Not rated"}</dd>
      </dl>
      {!h.counts_for_coverage && <p className="caveat">Not counted as existing coverage when scoring sites.</p>}
      {LOCATION_NOTES[h.loc_quality] && (
        <p className={LOCATION_NOTES[h.loc_quality].approximate ? "caveat" : "location-note"}>
          {LOCATION_NOTES[h.loc_quality].text}
        </p>
      )}
    </div>
  );
}

export function HospitalPopup({ hospitals }) {
  const many = hospitals.length > 1;
  return (
    <div className="popup">
      {many && <p className="sub">{hospitals.length} hospitals at this spot.</p>}
      <div className={many ? "popup-list multi" : "popup-list"}>
        {hospitals.map((h) => <HospitalItem key={h.id} h={h} />)}
      </div>
    </div>
  );
}

export function CandidatePopup({ site, weights }) {
  const total = Object.values(weights).reduce((a, b) => a + b, 0) || 1;
  const flags = [site.in_mua && "MUA/P", site.in_hpsa && "HPSA"].filter(Boolean).join(", ") || "None";
  return (
    <div className="popup">
      <h3>#{site.rank}: {site.county} County, {site.state}</h3>
      <p className="sub">Census tract {site.tract_id} · {site.proposed_beds ?? "—"} proposed beds</p>
      <div className="breakdown">
        {WEIGHTS.map(({ key, label }) => {
          const factor = Number(site[key + "_score"] ?? 0);
          const points = (weights[key] * factor) / total;
          return (
            <div className="breakdown-row" key={key} title={`${label}: factor ${factor.toFixed(2)} x weight ${weights[key]}`}>
              <span>{label}</span>
              <span className="breakdown-bar"><span style={{ width: `${(factor * 100).toFixed(0)}%` }} /></span>
              <span className="breakdown-value">+{points.toFixed(2)}</span>
            </div>
          );
        })}
        <div className="total"><span>Score</span><span>{Number(site.score).toFixed(2)}</span></div>
      </div>
      <dl>
        <dt>New 30-min access</dt><dd>{fmt(site.newly_accessible_population_30min ?? site.uncovered_population)} people</dd>
        <dt>Time saved</dt><dd>{site.population_weighted_mean_minutes_saved ?? "—"} min average</dd>
        <dt>Nearest hospital</dt><dd>{site.nearest_existing_hospital_estimated_drive_miles ?? site.nearest_hospital_mi ?? "—"} mi</dd>
        <dt>Shortage areas</dt><dd>{flags}</dd>
        <dt>Density</dt><dd>{fmt(site.density_per_sq_mi)} / sq mi{site.density_imputed ? " (estimated)" : ""}</dd>
        <dt>Tract population</dt><dd>{fmt(site.tract_population)}</dd>
      </dl>
      <p className="caveat">
        Bars show each Stage 8 component from 0 to 1. Select this site for services, access bands and configurations.
        The circle is a representative planning point for an area, not a surveyed building parcel.
      </p>
    </div>
  );
}

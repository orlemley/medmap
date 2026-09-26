import { WEIGHTS } from "../../lib/constants.js";
import { fmt } from "../../lib/format.js";

const LOCATION_NOTES = {
  zcta: "Location is the center of the hospital's ZIP code, not its street address.",
  zip3: "ZIP code not found in census data; shown at the nearest ZIP code's center.",
  county: "ZIP code not found in census data; shown at the county's center.",
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
      <p className="caveat">{LOCATION_NOTES[h.loc_quality]}</p>
    </div>
  );
}

export function HospitalPopup({ hospitals }) {
  const many = hospitals.length > 1;
  return (
    <div className="popup">
      {many && <p className="sub">{hospitals.length} hospitals share this ZIP code location.</p>}
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
      <p className="sub">Census tract {site.tract_id}</p>
      <div className="breakdown">
        {WEIGHTS.map(({ key, label }) => {
          const factor = Number(site["f_" + key]);
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
        <dt>Gain coverage</dt><dd>{fmt(site.uncovered_population)} people</dd>
        <dt>Avg. closer by</dt><dd>{site.avg_distance_reduction_mi} mi</dd>
        <dt>Nearest hospital</dt><dd>{site.nearest_hospital_mi} mi</dd>
        <dt>Shortage areas</dt><dd>{flags}</dd>
        <dt>Density</dt><dd>{fmt(site.density_per_sq_mi)} / sq mi{site.density_imputed ? " (estimated)" : ""}</dd>
        <dt>Tract population</dt><dd>{fmt(site.tract_population)}</dd>
      </dl>
      <p className="caveat">
        Bars show each factor from 0 to 1. Numbers are its weighted share of the score. Distances are straight-line.
      </p>
    </div>
  );
}

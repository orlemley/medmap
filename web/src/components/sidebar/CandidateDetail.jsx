import { fmt } from "../../lib/format.js";

const value = (v, suffix = "") => v === null || v === undefined || v === "" ? "—" : `${fmt(v)}${suffix}`;

export default function CandidateDetail({ state, onClose }) {
  if (!state.siteId) return null;
  const data = state.data;
  const candidate = data?.candidate;
  return (
    <section className="candidate-detail" aria-label="Candidate details">
      <div className="panel-heading detail-heading">
        <div>
          <p className="eyebrow">Candidate detail</p>
          <h2>{candidate ? `${candidate.county || candidate.county_name || candidate.source_county_name || "Site"}, ${candidate.state || ""}` : "Loading site…"}</h2>
        </div>
        <button className="link-button" type="button" onClick={onClose}>Close</button>
      </div>
      {state.status === "loading" && <p className="empty">Loading services and access bands…</p>}
      {state.status === "error" && <p className="status error">{state.error.message}</p>}
      {candidate && (
        <>
          <dl className="detail-facts">
            <dt>Stage 8 score</dt><dd>{value(candidate.stage8_score)}</dd>
            <dt>Configuration</dt><dd>{candidate.configuration_name || candidate.configuration_id || "—"}</dd>
            <dt>Proposed beds</dt><dd>{value(candidate.proposed_beds)}</dd>
            <dt>Recommended services</dt><dd>{candidate.recommended_services || "—"}</dd>
            <dt>Travel model</dt><dd>{candidate.travel_time_model || candidate.stage8_distance_model || "Estimated"}</dd>
            <dt>Routing refined</dt><dd>{candidate.routing_refined ? "Yes" : "No"}</dd>
          </dl>

          <h3>Access by travel time</h3>
          <div className="detail-table-wrap">
            <table className="detail-table">
              <thead><tr><th>Minutes</th><th>Population</th><th>New access</th><th>Hospitals</th></tr></thead>
              <tbody>{(data.access || []).map((row) => (
                <tr key={row.minutes}><td>{row.minutes}</td><td>{value(row.population)}</td>
                  <td>{value(row.newly_accessible_population)}</td><td>{value(row.existing_hospitals)}</td></tr>
              ))}</tbody>
            </table>
          </div>

          <h3>Clinical services</h3>
          <ul className="service-detail-list">
            {(data.services || []).filter((service) => service.recommended).map((service) => (
              <li key={service.service_id}>
                <span><strong>{service.service_name}</strong><small>{service.description}</small></span>
                <span>{Number(service.service_score).toFixed(2)}{service.service_gap ? " · gap" : ""}</span>
              </li>
            ))}
          </ul>

          {!!data.configurations?.length && (
            <>
              <h3>Alternate configurations</h3>
              <ul className="configuration-list">
                {data.configurations.slice(0, 5).map((config, index) => (
                  <li key={config.configuration_id || index}>
                    <strong>{config.configuration_name || config.configuration_id}</strong>
                    <span>{value(config.proposed_beds)} beds · score {value(config.overall_score)}</span>
                  </li>
                ))}
              </ul>
            </>
          )}
        </>
      )}
    </section>
  );
}

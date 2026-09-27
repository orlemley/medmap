import { Link } from "react-router";

const STEPS = [
  ["Map existing care", "About 5,300 hospitals from CMS, and the distance from every census tract to the nearest one."],
  ["Score every tract", "Each of 83,000 census tracts is a candidate site, scored on the four factors below."],
  ["Rank the best sites", "The top sites appear on the map with a full score breakdown. Move the sliders and they update."],
];

const FACTORS = [
  ["Population", "People within the coverage radius of the site who have no hospital within that radius today."],
  ["Distance", "How many miles closer to a hospital those people would be, on average."],
  ["Shortage", "Whether the site is in a federally designated Medically Underserved Area or primary-care shortage area."],
  ["Cost", "Population density as a stand-in for land and build cost. Sparse areas score higher."],
];

const SOURCES = [
  ["CMS Hospital General Information", "Existing hospitals: name, type, address, ZIP, rating"],
  ["U.S. Census Geocoder, OpenStreetMap", "Turning hospital addresses into map locations"],
  ["CDC PLACES (tract and ZCTA)", "Tract population and centroids; ZIP-area centers as a fallback for hospital locations"],
  ["HRSA MUA/P", "Medically Underserved Areas and Populations"],
  ["HRSA HPSA (primary care)", "Health Professional Shortage Areas"],
  ["USDA RUCA 2020", "Population density and rural-urban codes per tract"],
];

export default function HomePage() {
  return (
    <>
      <title>MedMap: Hospital Placement</title>
      <main className="page">
        <p className="eyebrow">TigerHacks26</p>
        <h1>Where should the next hospital go?</h1>
        <p className="lead">
          MedMap recommends sites for a new hospital that would cut driving distance for the people farthest from
          care and take pressure off existing hospitals. It combines census population, federal shortage-area
          designations, and the locations of every hospital CMS tracks.
        </p>
        <div className="button-row">
          <Link className="button" to="/map">Open the map</Link>
          <a className="button secondary" href="#how">How it works</a>
        </div>

        <h2 id="how">How it works</h2>
        <div className="card-grid">
          {STEPS.map(([title, text], i) => (
            <div className="card" key={title}>
              <span className="step-number">{i + 1}</span>
              <h3>{title}</h3>
              <p>{text}</p>
            </div>
          ))}
        </div>

        <h2>What gets weighed</h2>
        <p>You choose how much each factor matters with sliders on the map page.</p>
        <div className="card-grid">
          {FACTORS.map(([title, text]) => (
            <div className="card" key={title}>
              <h3>{title}</h3>
              <p>{text}</p>
            </div>
          ))}
        </div>

        <h2>Data sources</h2>
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr><th>Source</th><th>Used for</th></tr>
            </thead>
            <tbody>
              {SOURCES.map(([source, use]) => (
                <tr key={source}><td>{source}</td><td>{use}</td></tr>
              ))}
            </tbody>
          </table>
        </div>

        <h2>Limitations</h2>
        <p className="note">
          This is a hackathon prototype. Distances are straight-line, not driving distance. Most hospitals are placed
          from their street address; the few whose address couldn't be matched to a map are shown at their ZIP
          code's center (hollow rings on the map). The scoring on the map is a placeholder until the placement
          algorithm is finished.
        </p>
      </main>
      <footer className="site-footer">MedMap · TigerHacks26</footer>
    </>
  );
}

import { Link } from 'react-router'
import '../styles/home.css'

const STEPS = [
  ['01', 'Measure existing access', 'Combine hospital locations, population, vulnerability, workforce shortages, and travel access into a consistent national planning dataset.'],
  ['02', 'Score candidate communities', 'Evaluate roughly 34,000 candidate locations with the Stage 8 model and retain the strongest options for interactive analysis.'],
  ['03', 'Explore tradeoffs', 'Re-rank candidates instantly by changing priorities, services, bed capacity, state, routing quality, and diversification preferences.'],
]

const FACTORS = [
  ['Access', 'How much practical access to care a proposed site could add.'],
  ['Capacity', 'Whether existing nearby hospitals and beds appear sufficient for the population.'],
  ['Vulnerability', 'Social vulnerability, health burden, and shortage-area evidence.'],
  ['Configuration fit', 'How well the proposed hospital size and archetype fit the community.'],
  ['Cost efficiency', 'Expected benefit relative to the scale of the proposed facility.'],
  ['Drive access', 'Modeled travel-time improvement relative to existing hospitals.'],
  ['Service fit', 'How strongly local service gaps support the recommended clinical mix.'],
]

const SOURCES = [
  'CMS hospital and service data',
  'U.S. Census and ACS population data',
  'CDC SVI and PLACES community indicators',
  'HRSA health-professional shortage data',
  'USDA rural–urban commuting classifications',
  'Processed road-routing and accessibility outputs',
]

export default function HomePage() {
  return (
    <main className="home-page">
      <section className="hero">
        <div className="hero-content">
          <p className="eyebrow">Evidence-informed hospital planning</p>
          <h1>Find communities where a new hospital could make the greatest difference.</h1>
          <p className="hero-copy">
            Explore a national planning model built from public health, demographic,
            hospital, workforce, and travel-access data—then tune its priorities to
            match the question your team is asking.
          </p>
          <div className="hero-actions">
            <Link className="btn btn-primary" to="/map">Explore the map</Link>
            <Link className="btn btn-secondary" to="/about">Read the methodology</Link>
          </div>
        </div>
      </section>

      <section className="home-section">
        <p className="section-kicker">How it works</p>
        <h2>From public data to an explainable shortlist</h2>
        <div className="step-grid">
          {STEPS.map(([number, title, body]) => (
            <article className="step-card" key={number}>
              <span className="step-number">{number}</span>
              <h3>{title}</h3>
              <p>{body}</p>
            </article>
          ))}
        </div>
      </section>

      <section className="home-section muted-section">
        <p className="section-kicker">What the score considers</p>
        <h2>Seven priorities, visible and adjustable</h2>
        <div className="factor-grid">
          {FACTORS.map(([title, body]) => (
            <article className="factor-card" key={title}>
              <h3>{title}</h3>
              <p>{body}</p>
            </article>
          ))}
        </div>
      </section>

      <section className="home-section data-section">
        <div>
          <p className="section-kicker">Data foundation</p>
          <h2>Built from complementary public datasets</h2>
          <p>
            No single source can describe healthcare access. The processed model links
            facility, population, health, vulnerability, shortage, rurality, and travel
            measures into a common geographic view.
          </p>
        </div>
        <ul className="source-list">
          {SOURCES.map(source => <li key={source}>{source}</li>)}
        </ul>
      </section>

      <section className="home-section caveat-section">
        <h2>A planning aid, not a final site-selection decision</h2>
        <p>
          Results identify places worth deeper investigation. They do not replace local
          demand forecasting, land and construction analysis, regulatory review,
          community consultation, or clinical and financial due diligence. Candidate
          hospital coordinates derived from Census geography are representative planning
          points rather than surveyed parcels.
        </p>
        <Link className="text-link" to="/map">Open the interactive model →</Link>
      </section>
    </main>
  )
}

import { useState } from "react";

/** Bottom-right legend, as on the whiteboard sketch: collapsible and closable. */
export default function Legend({ heatmapMode, basemap }) {
  const startCollapsed = typeof window !== "undefined" && window.matchMedia("(max-width: 800px)").matches;
  const [expanded, setExpanded] = useState(!startCollapsed);
  const [closed, setClosed] = useState(false);

  if (closed) {
    return (
      <button className="legend-reopen" type="button" onClick={() => setClosed(false)}>
        Legend
      </button>
    );
  }

  return (
    <section className="legend" aria-label="Legend">
      <div className="legend-header">
        <button
          className="legend-title"
          type="button"
          aria-expanded={expanded}
          aria-controls="legend-body"
          onClick={() => setExpanded((v) => !v)}
        >
          Legend <span className="chevron" aria-hidden="true" />
        </button>
        <button className="legend-close" type="button" aria-label="Close legend" onClick={() => setClosed(true)}>
          ×
        </button>
      </div>
      {expanded && (
        <div className="legend-body" id="legend-body">
          <div className="legend-row"><span className="swatch swatch-hospital" />Existing hospital</div>
          <div className="legend-row"><span className="swatch swatch-hospital approximate" />Hospital, approximate location</div>
          <div className="legend-row"><span className="swatch swatch-candidate"><span>1</span></span>Recommended site (rank)</div>
          <div className="legend-scale">
            <span>Score</span>
            <span className="ramp ramp-candidate" />
            <span className="ramp-labels"><span>low</span><span>high</span></span>
          </div>
          <div className="legend-row"><span className="swatch swatch-border" />State border</div>
          <div className="legend-scale">
            <span>{heatmapMode === "uncovered" ? "Population farther from existing care" : "Population"}</span>
            <span className="ramp ramp-heatmap" />
            <span className="ramp-labels"><span>fewer</span><span>more</span></span>
          </div>
          {basemap === "satellite" && <p className="legend-note">Photos: USGS, up to neighborhood detail</p>}
        </div>
      )}
    </section>
  );
}

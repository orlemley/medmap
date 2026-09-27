import { useState } from "react";
import { ResultsList } from "../sidebar/Controls.jsx";

const isPhone = () => window.matchMedia("(max-width: 800px)").matches;

/**
 * Recommended sites, floating over the left side of the map. Click a site to
 * fly there. Collapsible; starts collapsed on phones, and on phones it folds
 * away again after you pick a site so the map is visible.
 */
export default function SitesPanel({ theme, candidates, busy, activeId, onHover, onSelect }) {
  const [open, setOpen] = useState(() => !isPhone());
  const count = candidates.features.length;

  const select = (id) => {
    onSelect(id);
    if (isPhone()) setOpen(false);
  };

  return (
    <section className={open ? "sites-panel open" : "sites-panel"} aria-label="Recommended sites" aria-busy={busy}>
      <button
        className="sites-header"
        type="button"
        aria-expanded={open}
        aria-controls="sites-body"
        onClick={() => setOpen((o) => !o)}
      >
        <span className="sites-title-long">Recommended sites</span>
        <span className="sites-title-short">Top sites</span>
        <span className="sites-count">{count}</span>
        <span className="chevron" aria-hidden="true" />
      </button>
      {/* Hidden rather than removed, so the list keeps its place and state. */}
      <div className="sites-body" id="sites-body" hidden={!open}>
        <ResultsList theme={theme} candidates={candidates} activeId={activeId} onHover={onHover} onSelect={select} />
      </div>
    </section>
  );
}

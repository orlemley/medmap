import { useEffect, useMemo, useState } from "react";
import { STATE_NAMES, WEIGHTS } from "../../lib/constants.js";
import { clampNumber, fmt, scoreColor, scoreTextColor } from "../../lib/format.js";

export function Panel({ title, action, children }) {
  return (
    <section className="panel">
      <div className="panel-heading">
        <h2>{title}</h2>
        {action}
      </div>
      {children}
    </section>
  );
}

/** A− / A+ buttons for the map page's text size (sidebar, legend, popups). */
export function TextSizeControl({ scale, canSmaller, canLarger, onSmaller, onLarger }) {
  return (
    <div className="text-size" role="group" aria-label="Text size">
      <span className="text-size-label">Text size</span>
      <button type="button" className="text-size-button smaller" onClick={onSmaller} disabled={!canSmaller}
        aria-label="Smaller text" title="Smaller text">
        A−
      </button>
      <output aria-live="polite">{Math.round(scale * 100)}%</output>
      <button type="button" className="text-size-button larger" onClick={onLarger} disabled={!canLarger}
        aria-label="Larger text" title="Larger text">
        A+
      </button>
    </div>
  );
}

export function StatusBar({ kind, children }) {
  return (
    <div className={kind ? `status ${kind}` : "status"} role="status" aria-live="polite">
      {children}
    </div>
  );
}

export function RegionSelect({ states, value, onChange }) {
  const options = useMemo(
    () => states
      .map((s) => ({ ...s, name: STATE_NAMES[s.state] || s.state }))
      .sort((a, b) => a.name.localeCompare(b.name)),
    [states]
  );
  return (
    <label className="field">
      <span>Show</span>
      <select value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="">Entire U.S.</option>
        {options.map((s) => (
          <option key={s.state} value={s.state}>{s.name} ({fmt(s.hospitals)} hospitals)</option>
        ))}
      </select>
    </label>
  );
}

export function WeightSliders({ weights, onChange, onNormalize }) {
  const total = Object.values(weights).reduce((a, b) => a + b, 0);
  return (
    <>
      {WEIGHTS.map(({ key, label, help }) => (
        <div className="weight" key={key}>
          <label className="field">
            <span>{label} <output>{weights[key].toFixed(2)}</output></span>
            <input
              id={`w-${key}`}
              type="range"
              min="0"
              max="1"
              step="0.01"
              value={weights[key]}
              aria-describedby={`w-${key}-help`}
              onChange={(e) => onChange(key, Number(e.target.value))}
            />
          </label>
          <p className="help" id={`w-${key}-help`}>{help}</p>
        </div>
      ))}
      <div
        className={Math.abs(total - 1) > 0.05 ? "weight-total off" : "weight-total"}
        title="Weights are scaled to total 1 when scoring, so this only needs to be roughly 1."
      >
        <span>Total <strong id="weight-total">{total.toFixed(2)}</strong></span>
        <button className="link-button" id="normalize-weights" type="button" onClick={onNormalize} disabled={total <= 0}>
          Make total 1
        </button>
      </div>
    </>
  );
}

/**
 * Number box that commits valid values as you type and clamps on blur/Enter,
 * so typing "15" doesn't briefly commit "1".
 */
export function NumberField({ id, label, value, min, max, onCommit }) {
  const [draft, setDraft] = useState(String(value));
  useEffect(() => setDraft(String(value)), [value]);

  const commitClamped = () => {
    const n = clampNumber(draft, min, max, value);
    setDraft(String(n));
    if (n !== value) onCommit(n);
  };

  return (
    <label className="field compact">
      <span>{label}</span>
      <input
        id={id}
        type="number"
        inputMode="numeric"
        min={min}
        max={max}
        step="1"
        value={draft}
        onChange={(e) => {
          setDraft(e.target.value);
          const n = Number(e.target.value);
          if (e.target.value !== "" && Number.isInteger(n) && n >= min && n <= max) onCommit(n);
        }}
        onBlur={commitClamped}
        onKeyDown={(e) => {
          if (e.key === "Enter") commitClamped();
        }}
      />
    </label>
  );
}

export function ResultsList({ theme, candidates, activeId, onHover, onSelect }) {
  if (!candidates.features.length) return <p className="empty">No results yet.</p>;
  return (
    <ol className="results">
      {candidates.features.map((f) => {
        const p = f.properties;
        return (
          <li key={f.id}>
            <button
              className={f.id === activeId ? "result active" : "result"}
              type="button"
              data-id={f.id}
              onMouseEnter={() => onHover(f.id)}
              onMouseLeave={() => onHover(null)}
              onFocus={() => onHover(f.id)}
              onBlur={() => onHover(null)}
              onClick={() => onSelect(f.id)}
            >
              <span className="result-rank" style={{ background: scoreColor(p.score, theme), color: scoreTextColor(p.score, theme) }}>
                {p.rank}
              </span>
              <span className="result-name">{p.county} County, {p.state}</span>
              <span className="result-score">{Number(p.score).toFixed(2)}</span>
              <span className="result-detail">
                {fmt(p.uncovered_population)} people gain coverage · {p.avg_distance_reduction_mi} mi closer
              </span>
            </button>
          </li>
        );
      })}
    </ol>
  );
}

const LAYER_LABELS = [
  ["hospitals", "Hospitals"],
  ["candidates", "Recommended sites"],
  ["rings", "Coverage radius around sites"],
  ["heatmap", "Heatmap"],
];

export function LayerToggles({ layers, onToggle, heatmapMode, onHeatmapMode }) {
  return (
    <>
      {LAYER_LABELS.map(([key, label]) => (
        <label className="check" key={key}>
          <input id={`layer-${key}`} type="checkbox" checked={layers[key]} onChange={() => onToggle(key)} /> {label}
        </label>
      ))}
      <label className="field indent">
        <span>Heatmap shows</span>
        <select id="heatmap-mode" value={heatmapMode} onChange={(e) => onHeatmapMode(e.target.value)}>
          <option value="all">All population</option>
          <option value="uncovered">Population outside the radius of any hospital</option>
        </select>
      </label>
    </>
  );
}

export function HospitalTypeFilter({ hospitals, hiddenTypes, onToggle }) {
  const counts = useMemo(() => {
    const c = new Map();
    for (const f of hospitals?.features ?? []) c.set(f.properties.type, (c.get(f.properties.type) || 0) + 1);
    return [...c.entries()].sort((a, b) => b[1] - a[1]);
  }, [hospitals]);

  if (!counts.length) return <p className="empty">Loading…</p>;
  return (
    <>
      {counts.map(([type, count]) => (
        <label className="check" key={type}>
          <input type="checkbox" data-type={type} checked={!hiddenTypes.has(type)} onChange={() => onToggle(type)} />
          {type}
          <span className="count">{fmt(count)}</span>
        </label>
      ))}
      <p className="help">
        Hides markers only. Scoring always uses acute-care, critical-access, VA, DoD and rural emergency hospitals.
      </p>
    </>
  );
}

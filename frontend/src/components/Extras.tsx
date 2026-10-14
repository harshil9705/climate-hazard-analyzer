import { useEffect, useState } from "react";
import type { Analysis, AnnualRow } from "../api/types";

/* ------------------------------------------------------------------ verdict */

type Verdict = { tone: "up" | "down" | "weak" | "flat" | "none"; label: string; icon: string };

export function verdictFor(a: Analysis): Verdict {
  const t = a.trends.heatwave_days;
  if (a.event_total === 0) return { tone: "none", label: "No heatwaves detected", icon: "○" };
  if (t.status !== "ok") return { tone: "flat", label: "Not enough data for a trend", icon: "?" };
  if (t.significance === "significant")
    return t.direction === "increasing"
      ? { tone: "up", label: "Significant increase", icon: "↑" }
      : { tone: "down", label: "Significant decrease", icon: "↓" };
  if (t.significance === "weak") return { tone: "weak", label: `Weak evidence of ${t.direction === "increasing" ? "increase" : "decrease"}`, icon: t.direction === "increasing" ? "↗" : "↘" };
  return { tone: "flat", label: "No clear trend", icon: "≈" };
}

export function VerdictBanner({ analysis }: { analysis: Analysis }) {
  const v = verdictFor(analysis);
  return (
    <div className={`verdict verdict-${v.tone}`}>
      <span className="verdict-icon" aria-hidden>
        {v.icon}
      </span>
      <div>
        <span className="verdict-label">{v.label}</span>
        <p className="verdict-text">{analysis.insights.headline}</p>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------- heat stripes */

/** One cell per year, shaded by heatwave days (single-hue sequential scale, light → dark = few → many). */
export function HeatStripes({ annual }: { annual: AnnualRow[] }) {
  const [hover, setHover] = useState<AnnualRow | null>(null);
  const max = Math.max(1, ...annual.map((r) => r.heatwave_days ?? 0));
  const mid = annual[Math.floor(annual.length / 2)];
  const shown = hover ?? null;

  return (
    <div className="stripes-wrap">
      <div className="stripes" role="img" aria-label="Heat stripes: one cell per year, darker means more heatwave days" onMouseLeave={() => setHover(null)}>
        {annual.map((r) => {
          const style =
            r.excluded || r.heatwave_days == null
              ? undefined
              : { background: `color-mix(in oklab, var(--series-heat) ${8 + (92 * r.heatwave_days) / max}%, var(--surface-2))` };
          return (
            <span
              key={r.year}
              className={`stripe${r.excluded ? " stripe-excluded" : ""}${hover?.year === r.year ? " on" : ""}`}
              style={style}
              onMouseEnter={() => setHover(r)}
              title={r.excluded ? `${r.year}: excluded (data gaps)` : `${r.year}: ${r.heatwave_days} heatwave days`}
            />
          );
        })}
      </div>
      <div className="stripes-axis">
        <span>{annual[0]?.year}</span>
        <span>{mid?.year}</span>
        <span>{annual[annual.length - 1]?.year}</span>
      </div>
      <div className="stripes-foot">
        <span className="stripes-readout" aria-live="polite">
          {shown ? (
            shown.excluded ? (
              <>
                <strong>{shown.year}</strong> excluded (too much missing data)
              </>
            ) : (
              <>
                <strong>{shown.year}</strong> · {shown.heatwave_days} heatwave days · {shown.event_count} event
                {shown.event_count === 1 ? "" : "s"}
                {shown.longest_event_days ? ` · longest ${shown.longest_event_days} d` : ""}
              </>
            )
          ) : (
            "Hover a year for details"
          )}
        </span>
        <span className="stripes-legend">
          0<span className="stripes-ramp" aria-hidden />
          {max} days
        </span>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------ loading panel */

const STEPS = [
  { at: 0, label: "Checking the database for a cached result" },
  { at: 1.5, label: "Downloading daily ERA5 temperatures for each grid cell" },
  { at: 6, label: "Pacing requests to stay within Open-Meteo's free quota" },
  { at: 50, label: "Almost there: detecting heatwaves and testing trends" },
];

export function LoadingPanel({ isBox }: { isBox: boolean }) {
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    const start = performance.now();
    const t = setInterval(() => setElapsed((performance.now() - start) / 1000), 250);
    return () => clearInterval(t);
  }, []);
  const active = STEPS.filter((s) => elapsed >= s.at).length - 1;
  return (
    <div className="card loading-panel" aria-busy="true" aria-live="polite">
      <div className="loading-head">
        <span className="spinner" aria-hidden />
        <div>
          <strong>Analysing heatwaves…</strong>
          <span className="muted-inline"> {Math.floor(elapsed)}s</span>
        </div>
      </div>
      <div className="progress" aria-hidden>
        <span />
      </div>
      <ol className="steps">
        {STEPS.map((s, i) => (
          <li key={s.label} className={i < active ? "done" : i === active ? "active" : ""}>
            {s.label}
          </li>
        ))}
      </ol>
      <p className="hint">
        {isBox
          ? "A new region needs decades of daily data for several grid cells, so the first run can take about a minute. Repeat runs are instant."
          : "A new location usually takes a few seconds. Repeat runs are served from the database instantly."}
      </p>
    </div>
  );
}

/* -------------------------------------------------------------- section nav */

export const SECTIONS = [
  { id: "overview", label: "Overview" },
  { id: "annual", label: "Annual trend" },
  { id: "indices", label: "Indices" },
  { id: "seasonal", label: "Seasonal cycle" },
  { id: "events", label: "Events" },
  { id: "method", label: "Method & data" },
];

export function SectionNav() {
  const [active, setActive] = useState("overview");
  useEffect(() => {
    const obs = new IntersectionObserver(
      (entries) => {
        const visible = entries.filter((e) => e.isIntersecting).sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top);
        if (visible[0]) setActive(visible[0].target.id);
      },
      { rootMargin: "-120px 0px -60% 0px" },
    );
    SECTIONS.forEach((s) => {
      const el = document.getElementById(s.id);
      if (el) obs.observe(el);
    });
    return () => obs.disconnect();
  }, []);
  return (
    <nav className="section-nav" aria-label="Result sections">
      {SECTIONS.map((s) => (
        <a key={s.id} href={`#${s.id}`} className={active === s.id ? "on" : ""} aria-current={active === s.id ? "true" : undefined}>
          {s.label}
        </a>
      ))}
    </nav>
  );
}

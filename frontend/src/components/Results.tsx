import { useMemo, useState } from "react";
import { api } from "../api/client";
import type { Analysis, AnyAnalysis, DroughtAnalysis, DroughtEvent, HeatwaveEvent, RainfallAnalysis, RainfallEvent, Trend } from "../api/types";
import { SIGNIFICANCE_LABEL, formatP, formatSigned } from "../lib/format";
import { AnnualHeatwaveChart, ClimatologyChart, MetricGrid } from "./charts";
import { HeatStripes, VerdictBanner } from "./Extras";

// ── Shared helpers ────────────────────────────────────────────────────────────

function FindingsCard({ findings }: { findings: { metric: string; text: string; significance?: string }[] }) {
  return (
    <section className="card">
      <h3>Key findings</h3>
      <ul className="findings">
        {findings.map((f) => (
          <li key={f.metric}>
            {f.significance && <span className={`dot dot-${f.significance}`} aria-hidden />}
            {f.text}
          </li>
        ))}
      </ul>
    </section>
  );
}

function DataQualityCard({ a, fromCache }: { a: AnyAnalysis; fromCache: boolean }) {
  const q = a.data_quality;
  return (
    <section className="card">
      <h3>Data quality</h3>
      <dl className="kv">
        <dt>Days analysed</dt>
        <dd>{q.total_days.toLocaleString()}</dd>
        <dt>Missing in source</dt>
        <dd>{q.missing_raw}</dd>
        <dt>Implausible values removed</dt>
        <dd>{q.implausible_removed}</dd>
        <dt>Short gaps interpolated</dt>
        <dd>{q.interpolated}</dd>
        <dt>Still missing</dt>
        <dd>{q.missing_after_cleaning}</dd>
        <dt>Years excluded</dt>
        <dd>{q.excluded_years.length ? q.excluded_years.join(", ") : "none"}</dd>
        <dt>Cache</dt>
        <dd>
          {fromCache ? "result served from database" : `${a.cache.years_from_cache}/${a.cache.years_requested} grid-cell years cached`}
        </dd>
      </dl>
    </section>
  );
}

function TrendBadge({ trend }: { trend: Trend }) {
  const sig = trend.significance;
  return (
    <span className="tile-sub">
      {trend.sens_slope_per_decade != null ? `${formatSigned(trend.sens_slope_per_decade)} /decade` : "—"} ·{" "}
      {sig ? <span className={`badge badge-${sig}`}>{SIGNIFICANCE_LABEL[sig]}</span> : null}{" "}
      {formatP(trend.mann_kendall?.p_value)}
    </span>
  );
}

// ── Heatwave results ──────────────────────────────────────────────────────────

function HeatwaveStatTiles({ a }: { a: Analysis }) {
  const hw = a.trends.heatwave_days;
  const comp = a.insights.period_comparison;
  const sig = hw.significance;
  return (
    <div className="tiles">
      <div className="tile">
        <span className="tile-label">Heatwave days, change</span>
        <span className="tile-value">
          {comp ? (comp.percent_change != null ? `${formatSigned(comp.percent_change, 0)}%` : formatSigned(comp.absolute_change)) : "—"}
        </span>
        <span className="tile-sub">
          {comp
            ? `${comp.early.mean.toFixed(1)} → ${comp.late.mean.toFixed(1)} days/yr (${comp.early.start}–${String(comp.early.end).slice(2)} vs ${comp.late.start}–${String(comp.late.end).slice(2)})`
            : "not enough data"}
        </span>
      </div>
      <div className="tile">
        <span className="tile-label">Trend</span>
        <span className="tile-value">{hw.sens_slope_per_decade != null ? `${formatSigned(hw.sens_slope_per_decade)}` : "—"}</span>
        <span className="tile-sub">
          days/decade · {sig ? <span className={`badge badge-${sig}`}>{SIGNIFICANCE_LABEL[sig]}</span> : null}{" "}
          {formatP(hw.mann_kendall?.p_value)}
        </span>
      </div>
      <div className="tile">
        <span className="tile-label">Heatwaves detected</span>
        <span className="tile-value">{a.event_total.toLocaleString()}</span>
        <span className="tile-sub">
          {a.request.start_year}–{a.request.end_year}
        </span>
      </div>
      <div className="tile">
        <span className="tile-label">Threshold</span>
        <span className="tile-value">{a.threshold.value_c != null ? `${a.threshold.value_c.toFixed(1)} °C` : "Day-of-year"}</span>
        <span className="tile-sub">
          {a.threshold.percentile}th pct of {a.threshold.baseline[0]}–{a.threshold.baseline[1]}, ≥{a.threshold.min_duration_days} days
        </span>
      </div>
    </div>
  );
}

type HWSortKey = "start" | "duration_days" | "peak_tmax_c" | "cumulative_excess_cdays";

function HeatwaveEventsTable({ events, total }: { events: HeatwaveEvent[]; total: number }) {
  const [sort, setSort] = useState<HWSortKey>("duration_days");
  const maxDuration = Math.max(1, ...events.map((e) => e.duration_days));
  const [showAll, setShowAll] = useState(false);
  const sorted = useMemo(() => {
    const copy = [...events];
    copy.sort((a, b) => (sort === "start" ? b.start.localeCompare(a.start) : (b[sort] as number) - (a[sort] as number)));
    return copy;
  }, [events, sort]);
  const rows = showAll ? sorted : sorted.slice(0, 10);
  const header = (key: HWSortKey, label: string) => (
    <th aria-sort={sort === key ? "descending" : "none"}>
      <button type="button" className={sort === key ? "sort on" : "sort"} onClick={() => setSort(key)}>
        {label}
      </button>
    </th>
  );
  if (events.length === 0) return <p className="muted">No heatwave events in this period.</p>;
  return (
    <>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              {header("start", "Dates")}
              {header("duration_days", "Duration")}
              {header("peak_tmax_c", "Peak Tmax")}
              <th>Mean excess</th>
              {header("cumulative_excess_cdays", "Excess heat")}
            </tr>
          </thead>
          <tbody>
            {rows.map((e) => (
              <tr key={e.start}>
                <td>
                  {e.start} → {e.end}
                </td>
                <td className="num">
                  <span className="dur">
                    <span className="dur-track" aria-hidden>
                      <span className="dur-bar" style={{ width: `${(100 * e.duration_days) / maxDuration}%` }} />
                    </span>
                    {e.duration_days} d
                  </span>
                </td>
                <td className="num">{e.peak_tmax_c.toFixed(1)} °C</td>
                <td className="num">+{e.mean_excess_c.toFixed(1)} °C</td>
                <td className="num">{e.cumulative_excess_cdays.toFixed(1)} °C·d</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {events.length > 10 && (
        <button type="button" className="btn-link" onClick={() => setShowAll((s) => !s)}>
          {showAll ? "Show top 10" : `Show all ${total} events`}
        </button>
      )}
    </>
  );
}

function HeatwaveAnnualTable({ a }: { a: Analysis }) {
  return (
    <div className="table-wrap tall">
      <table>
        <thead>
          <tr>
            <th>Year</th>
            <th>Events</th>
            <th>HW days</th>
            <th>Longest</th>
            <th>Peak Tmax</th>
            <th>Excess heat</th>
            <th>Mean Tmax</th>
          </tr>
        </thead>
        <tbody>
          {a.annual.map((r) => (
            <tr key={r.year} className={r.excluded ? "excluded" : ""}>
              <td>{r.year}</td>
              {r.excluded ? (
                <td colSpan={6} className="muted">
                  excluded: too much missing data
                </td>
              ) : (
                <>
                  <td className="num">{r.event_count}</td>
                  <td className="num">{r.heatwave_days}</td>
                  <td className="num">{r.longest_event_days}</td>
                  <td className="num">{r.peak_tmax_c != null ? r.peak_tmax_c.toFixed(1) : "—"}</td>
                  <td className="num">{r.cumulative_excess_cdays?.toFixed(1)}</td>
                  <td className="num">{r.mean_annual_tmax_c?.toFixed(1)}</td>
                </>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function HeatwaveResults({ a, fromCache }: { a: Analysis; fromCache: boolean }) {
  const [view, setView] = useState<"chart" | "table">("chart");
  return (
    <div className="results">
      <section className="card insight-card" id="overview" aria-live="polite">
        <div className="insight-head">
          <div>
            <p className="eyebrow">
              Heatwave analysis · {a.request.start_year}–{a.request.end_year}
            </p>
            <h2>{a.region_label}</h2>
          </div>
          <div className="exports">
            <a className="btn-secondary" href={api.exportUrl(a.id, "export.csv")} download>
              CSV
            </a>
            <a className="btn-secondary" href={api.exportUrl(a.id, "report.pdf")} download>
              PDF report
            </a>
          </div>
        </div>
        <VerdictBanner analysis={a} />
        <HeatwaveStatTiles a={a} />
        <HeatStripes annual={a.annual} />
      </section>

      <section className="card" id="annual">
        <div className="card-head">
          <div>
            <h3>Annual heatwave days</h3>
            <p className="muted">
              Days belonging to heatwaves (≥{a.threshold.min_duration_days} consecutive days above {a.threshold.label}).
            </p>
          </div>
          <div className="segmented small" role="radiogroup" aria-label="View">
            <button type="button" role="radio" aria-checked={view === "chart"} className={view === "chart" ? "on" : ""} onClick={() => setView("chart")}>
              Chart
            </button>
            <button type="button" role="radio" aria-checked={view === "table"} className={view === "table" ? "on" : ""} onClick={() => setView("table")}>
              Table
            </button>
          </div>
        </div>
        {view === "chart" ? <AnnualHeatwaveChart analysis={a} /> : <HeatwaveAnnualTable a={a} />}
      </section>

      <section className="card" id="indices">
        <h3>Frequency, duration and intensity</h3>
        <p className="muted">Dashed lines are Sen's slope trends; badges show Mann-Kendall significance.</p>
        <MetricGrid analysis={a} />
      </section>

      <FindingsCard findings={a.insights.findings} />

      <section className="card" id="seasonal">
        <h3>Seasonal cycle vs threshold</h3>
        <p className="muted">How the recent decade compares with the baseline climate, and where the heatwave threshold sits.</p>
        <ClimatologyChart analysis={a} />
      </section>

      <section className="card" id="events">
        <h3>Heatwave events</h3>
        <HeatwaveEventsTable events={a.events} total={a.event_total} />
      </section>

      <div className="two-col" id="method">
        <DataQualityCard a={a} fromCache={fromCache} />
        <section className="card">
          <h3>Method & caveats</h3>
          <p className="small">
            Source: {a.source.provider}, {a.source.dataset} ({a.source.variable}), {a.source.grid_points.length} grid cell
            {a.source.grid_points.length > 1 ? "s (spatially averaged)" : ""}. Trend: Mann-Kendall test with Sen's slope; OLS for
            comparison
            {a.trends.heatwave_days.ols
              ? ` (OLS ${formatSigned(a.trends.heatwave_days.ols.slope_per_decade, 2)} days/decade, R² ${a.trends.heatwave_days.ols.r_squared.toFixed(2)})`
              : ""}.
          </p>
          <ul className="caveats">
            {a.insights.caveats.map((c) => (
              <li key={c}>{c}</li>
            ))}
          </ul>
        </section>
      </div>
    </div>
  );
}

// ── Drought results ───────────────────────────────────────────────────────────

type DroughtSortKey = "start" | "duration_days" | "cumulative_deficit_mm";

function DroughtEventsTable({ events, total }: { events: DroughtEvent[]; total: number }) {
  const [sort, setSort] = useState<DroughtSortKey>("duration_days");
  const [showAll, setShowAll] = useState(false);
  const maxDuration = Math.max(1, ...events.map((e) => e.duration_days));
  const sorted = useMemo(() => {
    const copy = [...events];
    copy.sort((a, b) => (sort === "start" ? b.start.localeCompare(a.start) : (b[sort] as number) - (a[sort] as number)));
    return copy;
  }, [events, sort]);
  const rows = showAll ? sorted : sorted.slice(0, 10);
  const header = (key: DroughtSortKey, label: string) => (
    <th aria-sort={sort === key ? "descending" : "none"}>
      <button type="button" className={sort === key ? "sort on" : "sort"} onClick={() => setSort(key)}>
        {label}
      </button>
    </th>
  );
  if (events.length === 0) return <p className="muted">No drought spells detected in this period.</p>;
  return (
    <>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              {header("start", "Dates")}
              {header("duration_days", "Duration")}
              <th>Mean precip</th>
              {header("cumulative_deficit_mm", "Deficit")}
            </tr>
          </thead>
          <tbody>
            {rows.map((e) => (
              <tr key={e.start}>
                <td>
                  {e.start} → {e.end}
                </td>
                <td className="num">
                  <span className="dur">
                    <span className="dur-track" aria-hidden>
                      <span className="dur-bar" style={{ width: `${(100 * e.duration_days) / maxDuration}%` }} />
                    </span>
                    {e.duration_days} d
                  </span>
                </td>
                <td className="num">{e.mean_precip_mm.toFixed(1)} mm</td>
                <td className="num">{e.cumulative_deficit_mm.toFixed(1)} mm</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {events.length > 10 && (
        <button type="button" className="btn-link" onClick={() => setShowAll((s) => !s)}>
          {showAll ? "Show top 10" : `Show all ${total} events`}
        </button>
      )}
    </>
  );
}

function DroughtAnnualTable({ a }: { a: DroughtAnalysis }) {
  return (
    <div className="table-wrap tall">
      <table>
        <thead>
          <tr>
            <th>Year</th>
            <th>Spells</th>
            <th>Drought days</th>
            <th>Longest spell</th>
            <th>Deficit (mm)</th>
            <th>Total precip</th>
          </tr>
        </thead>
        <tbody>
          {a.annual.map((r) => (
            <tr key={r.year} className={r.excluded ? "excluded" : ""}>
              <td>{r.year}</td>
              {r.excluded ? (
                <td colSpan={5} className="muted">
                  excluded: too much missing data
                </td>
              ) : (
                <>
                  <td className="num">{r.event_count}</td>
                  <td className="num">{r.drought_days}</td>
                  <td className="num">{r.max_dry_spell}</td>
                  <td className="num">{r.cumulative_deficit_mm?.toFixed(1)}</td>
                  <td className="num">{r.total_annual_precip_mm?.toFixed(0)}</td>
                </>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function DroughtResults({ a, fromCache }: { a: DroughtAnalysis; fromCache: boolean }) {
  const [view, setView] = useState<"chart" | "table">("chart");
  const droughtTrend = a.trends["drought_days"];
  const precipTrend = a.trends["total_annual_precip_mm"];
  const comp = a.insights.period_comparison;

  return (
    <div className="results">
      <section className="card insight-card" id="overview" aria-live="polite">
        <div className="insight-head">
          <div>
            <p className="eyebrow">
              Drought analysis · {a.request.start_year}–{a.request.end_year}
            </p>
            <h2>{a.region_label}</h2>
          </div>
          <div className="exports">
            <a className="btn-secondary" href={api.exportUrl(a.id, "export.csv")} download>
              CSV
            </a>
          </div>
        </div>
        <div className="verdict">
          <p className="verdict-text">{a.insights.headline}</p>
        </div>
        <div className="tiles">
          <div className="tile">
            <span className="tile-label">Drought days, change</span>
            <span className="tile-value">
              {comp ? (comp.percent_change != null ? `${formatSigned(comp.percent_change, 0)}%` : formatSigned(comp.absolute_change)) : "—"}
            </span>
            <span className="tile-sub">
              {comp
                ? `${comp.early.mean.toFixed(1)} → ${comp.late.mean.toFixed(1)} days/yr`
                : "not enough data"}
            </span>
          </div>
          <div className="tile">
            <span className="tile-label">Drought trend</span>
            <span className="tile-value">{droughtTrend?.sens_slope_per_decade != null ? `${formatSigned(droughtTrend.sens_slope_per_decade)}` : "—"}</span>
            {droughtTrend && <TrendBadge trend={droughtTrend} />}
          </div>
          <div className="tile">
            <span className="tile-label">Dry spells detected</span>
            <span className="tile-value">{a.event_total.toLocaleString()}</span>
            <span className="tile-sub">
              {a.request.start_year}–{a.request.end_year}
            </span>
          </div>
          <div className="tile">
            <span className="tile-label">Threshold</span>
            <span className="tile-value">&lt;{a.threshold.dry_threshold_mm} mm/day</span>
            <span className="tile-sub">≥{a.threshold.min_duration_days} consecutive dry days</span>
          </div>
        </div>
      </section>

      <section className="card" id="annual">
        <div className="card-head">
          <div>
            <h3>Annual drought days</h3>
            <p className="muted">
              Days in dry spells of ≥{a.threshold.min_duration_days} consecutive days with precipitation &lt;{a.threshold.dry_threshold_mm} mm.
            </p>
          </div>
          <div className="segmented small" role="radiogroup" aria-label="View">
            <button type="button" role="radio" aria-checked={view === "chart"} className={view === "chart" ? "on" : ""} onClick={() => setView("chart")}>
              Chart
            </button>
            <button type="button" role="radio" aria-checked={view === "table"} className={view === "table" ? "on" : ""} onClick={() => setView("table")}>
              Table
            </button>
          </div>
        </div>
        {view === "chart" ? (
          <AnnualPrecipChart
            annual={a.annual.map((r) => ({ year: r.year, value: r.drought_days, excluded: r.excluded }))}
            trend={droughtTrend}
            yLabel="drought days / year"
            barColor="var(--series-drought, #d97706)"
          />
        ) : (
          <DroughtAnnualTable a={a} />
        )}
      </section>

      {precipTrend && (
        <section className="card">
          <h3>Annual precipitation trend</h3>
          <p className="muted">Total annual precipitation and its long-term trend.</p>
          <AnnualPrecipChart
            annual={a.annual.map((r) => ({ year: r.year, value: r.total_annual_precip_mm, excluded: r.excluded }))}
            trend={precipTrend}
            yLabel="mm / year"
            barColor="var(--series-rain, #0ea5e9)"
          />
        </section>
      )}

      <FindingsCard findings={a.insights.findings} />

      <section className="card" id="events">
        <h3>Dry spell events</h3>
        <DroughtEventsTable events={a.events} total={a.event_total} />
      </section>

      <div className="two-col" id="method">
        <DataQualityCard a={a} fromCache={fromCache} />
        <section className="card">
          <h3>Method & caveats</h3>
          <p className="small">
            Source: {a.source.provider}, {a.source.dataset} ({a.source.variable}), {a.source.grid_points.length} grid cell
            {a.source.grid_points.length > 1 ? "s (spatially averaged)" : ""}. A dry day is defined as precipitation &lt;{a.threshold.dry_threshold_mm} mm. Consecutive dry days
            of ≥{a.threshold.min_duration_days} days count as a drought spell. Trend: Mann-Kendall test with Sen's slope.
          </p>
          <ul className="caveats">
            {a.insights.caveats.map((c) => (
              <li key={c}>{c}</li>
            ))}
          </ul>
        </section>
      </div>
    </div>
  );
}

// ── Heavy rainfall results ────────────────────────────────────────────────────

type RainfallSortKey = "start" | "duration_days" | "peak_precip_mm" | "cumulative_precip_mm";

function RainfallEventsTable({ events, total }: { events: RainfallEvent[]; total: number }) {
  const [sort, setSort] = useState<RainfallSortKey>("cumulative_precip_mm");
  const [showAll, setShowAll] = useState(false);
  const maxDuration = Math.max(1, ...events.map((e) => e.duration_days));
  const sorted = useMemo(() => {
    const copy = [...events];
    copy.sort((a, b) => (sort === "start" ? b.start.localeCompare(a.start) : (b[sort] as number) - (a[sort] as number)));
    return copy;
  }, [events, sort]);
  const rows = showAll ? sorted : sorted.slice(0, 10);
  const header = (key: RainfallSortKey, label: string) => (
    <th aria-sort={sort === key ? "descending" : "none"}>
      <button type="button" className={sort === key ? "sort on" : "sort"} onClick={() => setSort(key)}>
        {label}
      </button>
    </th>
  );
  if (events.length === 0) return <p className="muted">No heavy rainfall events detected in this period.</p>;
  return (
    <>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              {header("start", "Dates")}
              {header("duration_days", "Duration")}
              {header("peak_precip_mm", "Peak (mm)")}
              <th>Mean (mm)</th>
              {header("cumulative_precip_mm", "Total (mm)")}
            </tr>
          </thead>
          <tbody>
            {rows.map((e) => (
              <tr key={e.start}>
                <td>
                  {e.start} → {e.end}
                </td>
                <td className="num">
                  <span className="dur">
                    <span className="dur-track" aria-hidden>
                      <span className="dur-bar" style={{ width: `${(100 * e.duration_days) / maxDuration}%` }} />
                    </span>
                    {e.duration_days} d
                  </span>
                </td>
                <td className="num">{e.peak_precip_mm.toFixed(1)}</td>
                <td className="num">{e.mean_precip_mm.toFixed(1)}</td>
                <td className="num">{e.cumulative_precip_mm.toFixed(1)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {events.length > 10 && (
        <button type="button" className="btn-link" onClick={() => setShowAll((s) => !s)}>
          {showAll ? "Show top 10" : `Show all ${total} events`}
        </button>
      )}
    </>
  );
}

function RainfallAnnualTable({ a }: { a: RainfallAnalysis }) {
  return (
    <div className="table-wrap tall">
      <table>
        <thead>
          <tr>
            <th>Year</th>
            <th>Events</th>
            <th>Heavy days</th>
            <th>Longest</th>
            <th>Rx1day (mm)</th>
            <th>Rx5day (mm)</th>
            <th>Total precip</th>
          </tr>
        </thead>
        <tbody>
          {a.annual.map((r) => (
            <tr key={r.year} className={r.excluded ? "excluded" : ""}>
              <td>{r.year}</td>
              {r.excluded ? (
                <td colSpan={6} className="muted">
                  excluded: too much missing data
                </td>
              ) : (
                <>
                  <td className="num">{r.event_count}</td>
                  <td className="num">{r.heavy_days}</td>
                  <td className="num">{r.max_event_days}</td>
                  <td className="num">{r.rx1day_mm?.toFixed(1)}</td>
                  <td className="num">{r.rx5day_mm?.toFixed(1)}</td>
                  <td className="num">{r.total_annual_precip_mm?.toFixed(0)}</td>
                </>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function RainfallResults({ a, fromCache }: { a: RainfallAnalysis; fromCache: boolean }) {
  const [view, setView] = useState<"chart" | "table">("chart");
  const heavyTrend = a.trends["heavy_days"];
  const rx1Trend = a.trends["rx1day_mm"];
  const comp = a.insights.period_comparison;

  return (
    <div className="results">
      <section className="card insight-card" id="overview" aria-live="polite">
        <div className="insight-head">
          <div>
            <p className="eyebrow">
              Heavy rainfall analysis · {a.request.start_year}–{a.request.end_year}
            </p>
            <h2>{a.region_label}</h2>
          </div>
          <div className="exports">
            <a className="btn-secondary" href={api.exportUrl(a.id, "export.csv")} download>
              CSV
            </a>
          </div>
        </div>
        <div className="verdict">
          <p className="verdict-text">{a.insights.headline}</p>
        </div>
        <div className="tiles">
          <div className="tile">
            <span className="tile-label">Heavy rain days, change</span>
            <span className="tile-value">
              {comp ? (comp.percent_change != null ? `${formatSigned(comp.percent_change, 0)}%` : formatSigned(comp.absolute_change)) : "—"}
            </span>
            <span className="tile-sub">
              {comp
                ? `${comp.early.mean.toFixed(1)} → ${comp.late.mean.toFixed(1)} days/yr`
                : "not enough data"}
            </span>
          </div>
          <div className="tile">
            <span className="tile-label">Heavy days trend</span>
            <span className="tile-value">{heavyTrend?.sens_slope_per_decade != null ? `${formatSigned(heavyTrend.sens_slope_per_decade)}` : "—"}</span>
            {heavyTrend && <TrendBadge trend={heavyTrend} />}
          </div>
          <div className="tile">
            <span className="tile-label">Events detected</span>
            <span className="tile-value">{a.event_total.toLocaleString()}</span>
            <span className="tile-sub">
              {a.request.start_year}–{a.request.end_year}
            </span>
          </div>
          <div className="tile">
            <span className="tile-label">Threshold</span>
            <span className="tile-value">{a.threshold.value_mm.toFixed(1)} mm/day</span>
            <span className="tile-sub">
              {a.threshold.percentile}th pct of wet days, {a.threshold.baseline[0]}–{a.threshold.baseline[1]}
            </span>
          </div>
        </div>
      </section>

      <section className="card" id="annual">
        <div className="card-head">
          <div>
            <h3>Annual heavy rainfall days</h3>
            <p className="muted">
              Days exceeding the {a.threshold.percentile}th percentile of wet-day precipitation ({a.threshold.value_mm.toFixed(1)} mm/day).
            </p>
          </div>
          <div className="segmented small" role="radiogroup" aria-label="View">
            <button type="button" role="radio" aria-checked={view === "chart"} className={view === "chart" ? "on" : ""} onClick={() => setView("chart")}>
              Chart
            </button>
            <button type="button" role="radio" aria-checked={view === "table"} className={view === "table" ? "on" : ""} onClick={() => setView("table")}>
              Table
            </button>
          </div>
        </div>
        {view === "chart" ? (
          <AnnualPrecipChart
            annual={a.annual.map((r) => ({ year: r.year, value: r.heavy_days, excluded: r.excluded }))}
            trend={heavyTrend}
            yLabel="heavy rain days / year"
            barColor="var(--series-rain, #0ea5e9)"
          />
        ) : (
          <RainfallAnnualTable a={a} />
        )}
      </section>

      {rx1Trend && (
        <section className="card">
          <h3>Single-day rainfall extremes (Rx1day)</h3>
          <p className="muted">Annual maximum daily precipitation — a standard WMO extreme index.</p>
          <AnnualPrecipChart
            annual={a.annual.map((r) => ({ year: r.year, value: r.rx1day_mm, excluded: r.excluded }))}
            trend={rx1Trend}
            yLabel="mm"
            barColor="var(--series-rain, #0ea5e9)"
          />
        </section>
      )}

      <FindingsCard findings={a.insights.findings} />

      <section className="card" id="events">
        <h3>Heavy rainfall events</h3>
        <RainfallEventsTable events={a.events} total={a.event_total} />
      </section>

      <div className="two-col" id="method">
        <DataQualityCard a={a} fromCache={fromCache} />
        <section className="card">
          <h3>Method & caveats</h3>
          <p className="small">
            Source: {a.source.provider}, {a.source.dataset} ({a.source.variable}), {a.source.grid_points.length} grid cell
            {a.source.grid_points.length > 1 ? "s (spatially averaged)" : ""}. Heavy day threshold: {a.threshold.percentile}th percentile of
            wet-day (≥{a.threshold.wet_threshold_mm} mm) precipitation in {a.threshold.baseline[0]}–{a.threshold.baseline[1]}. Trend: Mann-Kendall with Sen's slope.
          </p>
          <ul className="caveats">
            {a.insights.caveats.map((c) => (
              <li key={c}>{c}</li>
            ))}
          </ul>
        </section>
      </div>
    </div>
  );
}

// ── Shared annual bar chart for precip-based analyses ─────────────────────────

import type { ChartData, ChartOptions } from "chart.js";
import { Chart } from "react-chartjs-2";
import { baseOptions, useChartColors } from "../lib/chartTheme";

interface AnnualPrecipChartProps {
  annual: { year: number; value: number | null | undefined; excluded: boolean }[];
  trend: Trend | undefined;
  yLabel: string;
  barColor: string;
}

function AnnualPrecipChart({ annual, trend, yLabel, barColor }: AnnualPrecipChartProps) {
  const c = useChartColors();
  const years = annual.map((r) => String(r.year));

  const data: ChartData<"bar" | "line", (number | null)[], string> = {
    labels: years,
    datasets: [
      {
        type: "bar",
        label: yLabel,
        data: annual.map((r) => (r.excluded ? null : (r.value ?? null))),
        backgroundColor: barColor,
        borderRadius: { topLeft: 3, topRight: 3 },
        borderSkipped: "bottom",
        maxBarThickness: 24,
        categoryPercentage: 0.85,
        barPercentage: 0.9,
        order: 3,
      },
      ...(trend?.rolling_mean_10y
        ? [
            {
              type: "line" as const,
              label: "10-year rolling mean",
              data: trend.rolling_mean_10y as (number | null)[],
              borderColor: c.trend,
              backgroundColor: c.trend,
              borderWidth: 2,
              pointRadius: 0,
              pointHoverRadius: 5,
              tension: 0.3,
              spanGaps: true,
              order: 1,
            },
          ]
        : []),
      ...(trend?.trend_line
        ? [
            {
              type: "line" as const,
              label: "Trend (Sen's slope)",
              data: trend.trend_line as (number | null)[],
              borderColor: c.reference,
              backgroundColor: c.reference,
              borderWidth: 2,
              borderDash: [6, 4],
              pointRadius: 0,
              pointHoverRadius: 0,
              order: 2,
            },
          ]
        : []),
    ],
  };

  const opts = baseOptions(c);
  const options: ChartOptions<"bar" | "line"> = {
    ...opts,
    plugins: {
      ...opts.plugins,
      tooltip: {
        ...opts.plugins.tooltip,
        callbacks: {
          label: (ctx) => {
            const v = ctx.parsed.y;
            if (v == null) return `${ctx.dataset.label}: excluded`;
            return `${ctx.dataset.label}: ${v.toFixed(1)}`;
          },
        },
      },
    },
    scales: { ...opts.scales, y: { ...opts.scales.y, title: { display: true, text: yLabel, color: c.textMuted } } },
  };

  return (
    <div className="chart-wrap">
      <Chart type="bar" data={data} options={options} />
    </div>
  );
}

// ── Dispatch ──────────────────────────────────────────────────────────────────

export default function Results({ analysis, fromCache }: { analysis: AnyAnalysis; fromCache: boolean }) {
  if (analysis.hazard === "drought") return <DroughtResults a={analysis} fromCache={fromCache} />;
  if (analysis.hazard === "rainfall") return <RainfallResults a={analysis} fromCache={fromCache} />;
  return <HeatwaveResults a={analysis} fromCache={fromCache} />;
}

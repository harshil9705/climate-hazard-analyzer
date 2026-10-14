import { useMutation, useQuery } from "@tanstack/react-query";
import { lazy, Suspense, useEffect, useState } from "react";
import { API_DOCS_URL, ApiError, api } from "./api/client";
import type { AnyAnalysis, AnalysisRequest, DroughtParams, HazardType, HeatwaveParams, Preset, RainfallParams, Region } from "./api/types";
import { LoadingPanel } from "./components/Extras";
import RegionPicker from "./components/RegionPicker";
import type { PickMode } from "./components/RegionMap";
import { validateRequest } from "./lib/format";

// Leaflet and Chart.js are the heaviest dependencies; load them as separate chunks.
const RegionMap = lazy(() => import("./components/RegionMap"));
const Results = lazy(() => import("./components/Results"));

const FALLBACK_HEATWAVE_PARAMS: HeatwaveParams = {
  percentile: 95,
  min_duration_days: 3,
  threshold_method: "fixed",
  baseline_start: 1961,
  baseline_end: 1990,
};

const FALLBACK_DROUGHT_PARAMS: DroughtParams = {
  dry_threshold_mm: 1.0,
  min_duration_days: 7,
};

const FALLBACK_RAINFALL_PARAMS: RainfallParams = {
  percentile: 95.0,
  wet_threshold_mm: 1.0,
  min_duration_days: 1,
  baseline_start: 1961,
  baseline_end: 1990,
};

const EXAMPLES: { preset: string; label: string; years: [number, number]; note: string }[] = [
  { preset: "gujarat", label: "Central Gujarat", years: [1980, 2024], note: "regional box" },
  { preset: "phoenix", label: "Phoenix", years: [1980, 2024], note: "desert city" },
  { preset: "delhi-ncr", label: "Delhi NCR", years: [1990, 2024], note: "megacity" },
  { preset: "andalusia", label: "Andalusia", years: [1980, 2024], note: "Mediterranean" },
];

function readIdFromUrl(): string | null {
  const id = new URLSearchParams(window.location.search).get("id");
  return id && /^[0-9a-f]{24}$/.test(id) ? id : null;
}

export default function App() {
  const meta = useQuery({ queryKey: ["meta"], queryFn: api.meta, staleTime: Infinity, retry: 1 });

  const [region, setRegion] = useState<Region | null>(null);
  const [mode, setMode] = useState<PickMode>("point");
  const [startYear, setStartYear] = useState(1990);
  const [endYear, setEndYear] = useState(2020);
  const [hazard, setHazard] = useState<HazardType>("heatwave");
  const [heatwaveParams, setHeatwaveParams] = useState<HeatwaveParams>(FALLBACK_HEATWAVE_PARAMS);
  const [droughtParams, setDroughtParams] = useState<DroughtParams>(FALLBACK_DROUGHT_PARAMS);
  const [rainfallParams, setRainfallParams] = useState<RainfallParams>(FALLBACK_RAINFALL_PARAMS);
  const [result, setResult] = useState<{ analysis: AnyAnalysis; fromCache: boolean } | null>(null);
  const [sharedId] = useState(readIdFromUrl);

  useEffect(() => {
    if (meta.data) {
      setStartYear(meta.data.default_range[0]);
      setEndYear(meta.data.default_range[1]);
      setHeatwaveParams(meta.data.default_params);
    }
  }, [meta.data]);

  // Shareable links: ?id=<analysis id> loads a stored analysis straight from the database.
  const shared = useQuery({
    queryKey: ["analysis", sharedId],
    queryFn: () => api.getAnalysis(sharedId!),
    enabled: !!sharedId,
    retry: false,
  });
  useEffect(() => {
    if (shared.data) {
      const a = shared.data;
      setResult({ analysis: a, fromCache: true });
      setRegion(a.request.region);
      setMode(a.request.region.kind);
      setStartYear(a.request.start_year);
      setEndYear(a.request.end_year);
      setHazard(a.hazard);
    }
  }, [shared.data]);

  const run = useMutation({
    mutationFn: (body: AnalysisRequest) => api.createAnalysis(body),
    onSuccess: (analysis) => {
      setResult({ analysis, fromCache: false });
      const url = new URL(window.location.href);
      url.searchParams.set("id", analysis.id);
      window.history.replaceState(null, "", url);
    },
  });

  const minYear = meta.data?.min_year ?? 1940;
  const maxYear = meta.data?.max_year ?? new Date().getFullYear() - 1;
  const clientError = validateRequest({ region, start: startYear, end: endYear, minYear, maxYear });
  const years = Array.from({ length: maxYear - minYear + 1 }, (_, i) => minYear + i);

  const activeParams = hazard === "drought" ? droughtParams : hazard === "rainfall" ? rainfallParams : heatwaveParams;

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (clientError || !region) return;
    run.mutate({ region, hazard, start_year: startYear, end_year: endYear, params: activeParams });
  };

  const apiError = run.error instanceof ApiError ? run.error : null;

  const runExample = (ex: (typeof EXAMPLES)[number]) => {
    const p = meta.data?.presets.find((x: Preset) => x.id === ex.preset);
    if (!p) return;
    const { id: _id, ...r } = p;
    const reg = r as Region;
    setRegion(reg);
    setMode(reg.kind);
    setStartYear(ex.years[0]);
    setEndYear(ex.years[1]);
    setHazard("heatwave");
    run.mutate({ region: reg, hazard: "heatwave", start_year: ex.years[0], end_year: ex.years[1], params: heatwaveParams });
  };

  const periodPresets: { label: string; range: [number, number] }[] = [
    { label: "1961–1990", range: [1961, 1990] },
    { label: "1991–2020", range: [1991, 2020] },
    { label: "Last 30 yrs", range: [maxYear - 29, maxYear] },
    { label: "Last 45 yrs", range: [maxYear - 44, maxYear] },
  ];

  const submitLabel = hazard === "drought" ? "Analyse drought" : hazard === "rainfall" ? "Analyse rainfall" : "Analyse heatwaves";

  return (
    <div className="app">
      <header className="topbar">
        <div className="topbar-inner">
          <div className="brand">
            <span className="logo" aria-hidden>
              {/* <svg viewBox="0 0 32 32" width="30" height="30">
                <rect width="32" height="32" rx="8" fill="var(--series-heat)" />
                <path d="M16 6a3 3 0 0 0-3 3v10.2a5 5 0 1 0 6 0V9a3 3 0 0 0-3-3z" fill="#fff" />
              </svg> */}
            </span>
            <div>
              <h1>Climate Hazard Analyzer</h1>
              <p>Detect heatwave, drought &amp; rainfall trends from historical weather data</p>
            </div>
          </div>
          <div className="topbar-actions">
            <a className="btn-ghost" href={API_DOCS_URL} target="_blank" rel="noreferrer">
              API docs
            </a>
          </div>
        </div>
      </header>

      <main>
        <section className="setup">
          <form className="card controls" onSubmit={submit} noValidate>
            <h2 className="section-title">1. Pick a location</h2>
            <RegionPicker
              region={region}
              onChange={(r) => setRegion(r)}
              mode={mode}
              onModeChange={setMode}
              presets={meta.data?.presets ?? []}
            />

            <h2 className="section-title">2. Choose hazard &amp; time range</h2>
            <div className="field">
              <label htmlFor="hazard">Hazard type</label>
              <select id="hazard" value={hazard} onChange={(e) => setHazard(e.target.value as HazardType)}>
                <option value="heatwave">Heatwave</option>
                <option value="drought">Drought</option>
                <option value="rainfall">Heavy rainfall</option>
              </select>
            </div>
            <div className="row">
              <div className="field">
                <label htmlFor="start">From</label>
                <select id="start" value={startYear} onChange={(e) => setStartYear(Number(e.target.value))}>
                  {years.map((y) => (
                    <option key={y}>{y}</option>
                  ))}
                </select>
              </div>
              <div className="field">
                <label htmlFor="end">To</label>
                <select id="end" value={endYear} onChange={(e) => setEndYear(Number(e.target.value))}>
                  {years.map((y) => (
                    <option key={y}>{y}</option>
                  ))}
                </select>
              </div>
            </div>

            <div className="chips" role="group" aria-label="Period shortcuts">
              {periodPresets.map((p) => (
                <button
                  key={p.label}
                  type="button"
                  className={`chip${startYear === p.range[0] && endYear === p.range[1] ? " on" : ""}`}
                  onClick={() => {
                    setStartYear(Math.max(minYear, p.range[0]));
                    setEndYear(p.range[1]);
                  }}
                >
                  {p.label}
                </button>
              ))}
            </div>

            {hazard === "heatwave" && (
              <details className="advanced">
                <summary>
                  Heatwave definition{" "}
                  <span className="summary-meta">
                    ≥{heatwaveParams.min_duration_days} days above {heatwaveParams.percentile}th pct
                  </span>
                </summary>
                <div className="row">
                  <div className="field">
                    <label htmlFor="pct">Percentile</label>
                    <input
                      id="pct"
                      type="number"
                      min={80}
                      max={99.9}
                      step={0.5}
                      value={heatwaveParams.percentile}
                      onChange={(e) => setHeatwaveParams({ ...heatwaveParams, percentile: Number(e.target.value) })}
                    />
                  </div>
                  <div className="field">
                    <label htmlFor="dur">Min. days</label>
                    <input
                      id="dur"
                      type="number"
                      min={2}
                      max={10}
                      value={heatwaveParams.min_duration_days}
                      onChange={(e) => setHeatwaveParams({ ...heatwaveParams, min_duration_days: Number(e.target.value) })}
                    />
                  </div>
                </div>
                <div className="field">
                  <label htmlFor="method">Threshold type</label>
                  <select
                    id="method"
                    value={heatwaveParams.threshold_method}
                    onChange={(e) => setHeatwaveParams({ ...heatwaveParams, threshold_method: e.target.value as HeatwaveParams["threshold_method"] })}
                  >
                    <option value="fixed">Fixed regional threshold (absolute heat)</option>
                    <option value="calendar_day">Calendar-day threshold (unusual for the season)</option>
                  </select>
                </div>
                <div className="row">
                  <div className="field">
                    <label htmlFor="b0">Baseline from</label>
                    <select id="b0" value={heatwaveParams.baseline_start} onChange={(e) => setHeatwaveParams({ ...heatwaveParams, baseline_start: Number(e.target.value) })}>
                      {years.map((y) => <option key={y}>{y}</option>)}
                    </select>
                  </div>
                  <div className="field">
                    <label htmlFor="b1">Baseline to</label>
                    <select id="b1" value={heatwaveParams.baseline_end} onChange={(e) => setHeatwaveParams({ ...heatwaveParams, baseline_end: Number(e.target.value) })}>
                      {years.map((y) => <option key={y}>{y}</option>)}
                    </select>
                  </div>
                </div>
                <p className="hint">
                  The threshold comes from a fixed baseline period so that recent warming doesn't raise the bar for what counts as "extreme".
                </p>
              </details>
            )}

            {hazard === "drought" && (
              <details className="advanced">
                <summary>
                  Drought definition{" "}
                  <span className="summary-meta">
                    ≥{droughtParams.min_duration_days} days with &lt;{droughtParams.dry_threshold_mm} mm
                  </span>
                </summary>
                <div className="row">
                  <div className="field">
                    <label htmlFor="dry-thr">Dry day threshold (mm)</label>
                    <input
                      id="dry-thr"
                      type="number"
                      min={0}
                      max={50}
                      step={0.5}
                      value={droughtParams.dry_threshold_mm}
                      onChange={(e) => setDroughtParams({ ...droughtParams, dry_threshold_mm: Number(e.target.value) })}
                    />
                  </div>
                  <div className="field">
                    <label htmlFor="dry-dur">Min. spell length (days)</label>
                    <input
                      id="dry-dur"
                      type="number"
                      min={3}
                      max={90}
                      value={droughtParams.min_duration_days}
                      onChange={(e) => setDroughtParams({ ...droughtParams, min_duration_days: Number(e.target.value) })}
                    />
                  </div>
                </div>
                <p className="hint">A dry spell is a run of consecutive days with daily precipitation below the threshold.</p>
              </details>
            )}

            {hazard === "rainfall" && (
              <details className="advanced">
                <summary>
                  Heavy rainfall definition{" "}
                  <span className="summary-meta">
                    {rainfallParams.percentile}th pct of wet days, ≥{rainfallParams.min_duration_days} d
                  </span>
                </summary>
                <div className="row">
                  <div className="field">
                    <label htmlFor="rain-pct">Percentile</label>
                    <input
                      id="rain-pct"
                      type="number"
                      min={80}
                      max={99.9}
                      step={0.5}
                      value={rainfallParams.percentile}
                      onChange={(e) => setRainfallParams({ ...rainfallParams, percentile: Number(e.target.value) })}
                    />
                  </div>
                  <div className="field">
                    <label htmlFor="rain-dur">Min. event length (days)</label>
                    <input
                      id="rain-dur"
                      type="number"
                      min={1}
                      max={10}
                      value={rainfallParams.min_duration_days}
                      onChange={(e) => setRainfallParams({ ...rainfallParams, min_duration_days: Number(e.target.value) })}
                    />
                  </div>
                </div>
                <div className="row">
                  <div className="field">
                    <label htmlFor="rain-b0">Baseline from</label>
                    <select id="rain-b0" value={rainfallParams.baseline_start} onChange={(e) => setRainfallParams({ ...rainfallParams, baseline_start: Number(e.target.value) })}>
                      {years.map((y) => <option key={y}>{y}</option>)}
                    </select>
                  </div>
                  <div className="field">
                    <label htmlFor="rain-b1">Baseline to</label>
                    <select id="rain-b1" value={rainfallParams.baseline_end} onChange={(e) => setRainfallParams({ ...rainfallParams, baseline_end: Number(e.target.value) })}>
                      {years.map((y) => <option key={y}>{y}</option>)}
                    </select>
                  </div>
                </div>
                <p className="hint">The threshold is the Xth percentile of wet-day precipitation (days ≥ 1 mm) in the baseline period.</p>
              </details>
            )}

            {clientError && region && <p className="form-error">{clientError}</p>}
            <button type="submit" className="btn-primary" disabled={!!clientError || run.isPending}>
              {run.isPending ? (
                <>
                  <span className="spinner small" aria-hidden /> Analysing…
                </>
              ) : (
                submitLabel
              )}
            </button>
          </form>

          <div className="card map-card">
            <Suspense fallback={<div className="map placeholder">Loading map…</div>}>
              <RegionMap region={region} mode={mode} onChange={setRegion} gridPoints={result?.analysis.source.grid_points} />
            </Suspense>
          </div>
        </section>

        {meta.isError && (
          <div className="card error-card" role="alert">
            Cannot reach the analysis server. Please check that the backend is running.
          </div>
        )}
        {run.isError && (
          <div className="card error-card" role="alert">
            <strong>{apiError?.message ?? "Something went wrong."}</strong>
            {apiError?.details.length ? (
              <ul>
                {apiError.details.map((d) => (
                  <li key={d}>{d}</li>
                ))}
              </ul>
            ) : null}
          </div>
        )}
        {shared.isError && !result && (
          <div className="card error-card" role="alert">
            The shared analysis could not be found. It may have expired. Run it again below.
          </div>
        )}

        {run.isPending && <LoadingPanel isBox={region?.kind === "bbox"} />}
        {result ? (
          <Suspense fallback={<ResultsSkeleton />}>
            <div className={run.isPending ? "stale" : ""}>
              <Results analysis={result.analysis} fromCache={result.fromCache} />
            </div>
          </Suspense>
        ) : (
          !run.isPending && (
            <div className="card empty-state">
              <h2>How to use</h2>
              <p>
                Search for a city or click on the map → choose a hazard (heatwave, drought, or heavy rainfall) → select a year range → click Analyse.
              </p>
              <p style={{ color: "var(--text-muted)", fontSize: "0.85rem", marginTop: 4 }}>
                Or try one of these quick examples:
              </p>
              <div className="examples">
                {EXAMPLES.map((ex) => (
                  <button key={ex.preset} type="button" className="example" onClick={() => runExample(ex)} disabled={!meta.data}>
                    <span className="example-title">{ex.label}</span>
                    <span className="example-meta">
                      {ex.years[0]}–{ex.years[1]} · {ex.note}
                    </span>
                  </button>
                ))}
              </div>
            </div>
          )
        )}
      </main>

      <footer className="footer">
        {/* Data: Open-Meteo Historical Weather API (ECMWF ERA5, CC BY 4.0). Basemap © OpenStreetMap contributors. */}
      </footer>
    </div>
  );
}

function ResultsSkeleton() {
  return (
    <div className="results" aria-busy="true">
      <div className="card skeleton" style={{ height: 180 }} />
      <div className="card skeleton" style={{ height: 380 }} />
    </div>
  );
}

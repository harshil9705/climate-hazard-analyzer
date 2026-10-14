# Climate Hazard Trend Analyzer

A full-stack web app that detects **heatwaves, droughts and heavy rainfall events** across 85 years of historical daily weather data for any location on Earth, and shows — honestly — whether they are becoming more frequent, longer, or more intense.

| Layer | Stack |
|---|---|
| **Frontend** | React 19 + TypeScript (Vite), TanStack Query, Chart.js, Leaflet |
| **Backend** | Python FastAPI, pandas/numpy, MongoDB Atlas, Open-Meteo ERA5 |

> **Note on first-time speed:** The first analysis of a new area downloads up to ~65 years of daily data per grid cell and paces requests to respect Open-Meteo's free-tier quota — this can take up to ~1 minute for a box selection. After that, results are served from MongoDB in milliseconds.

---

## Contents
1. [Quick Start](#quick-start)
2. [Project Structure](#project-structure)
3. [Architecture](#architecture)
4. [Data Source](#data-source)
5. [Data Handling](#data-handling)
6. [Hazard Detection Logic](#hazard-detection-logic)
7. [Trend Analysis & Insights](#trend-analysis--insights)
8. [API Reference](#api-reference)
9. [Frontend Features](#frontend-features)
10. [Security & Performance](#security--performance)
11. [Testing & CI](#testing--ci)
12. [Deployment](#deployment)
13. [Assumptions](#assumptions)
14. [What I'd Improve With More Time](#what-id-improve-with-more-time)
15. [AI Tools Used](#ai-tools-used)

---

## Quick Start

**Prerequisites:** Python 3.12+, Node 20+ (tested with Python 3.14 / Node 24). MongoDB is optional for local dev.

### Run locally (no Docker)

```bash
# 1 — Backend
cd backend
python -m venv .venv
# Windows:  .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env        # leave MONGODB_URI empty to use the in-memory store
uvicorn app.main:app --reload --port 8000
# API docs: http://localhost:8000/docs

# 2 — Frontend (new terminal)
cd frontend
npm install
npm run dev
# App: http://localhost:5173  (Vite proxies /api → :8000, no CORS config needed)
```

### Run with Docker (full stack + real MongoDB)

```bash
docker compose up --build
# API: http://localhost:8000/docs
# Run the frontend separately with: cd frontend && npm run dev
```

To connect to a real MongoDB: set `MONGODB_URI` in `backend/.env` (e.g. an Atlas free M0 cluster).

### Run tests

```bash
cd backend && pytest          # 50 backend tests
cd frontend && npm test && npm run typecheck
```

---

## Project Structure

```
.
├── backend/
│   ├── app/
│   │   ├── main.py               App entry point, middleware setup
│   │   ├── config.py             All settings (loaded from env / .env)
│   │   ├── api/routes.py         HTTP endpoints
│   │   ├── core/
│   │   │   ├── rate_limit.py     Sliding-window per-IP rate limiter
│   │   │   └── middleware.py     Security headers, body-size cap
│   │   ├── db/repository.py      MongoDB + in-memory repositories
│   │   ├── models/schemas.py     Pydantic request/response models
│   │   └── services/
│   │       ├── open_meteo.py     Open-Meteo HTTP client (retries, quota pacing)
│   │       ├── weather_data.py   Per-year caching, region → grid cells
│   │       ├── data_quality.py   Gap handling, outliers, unit conversion
│   │       ├── heatwave.py       Threshold calc, event detection, annual indices
│   │       ├── drought.py        Dry-spell detection, annual drought metrics
│   │       ├── rainfall.py       Heavy-rain detection, Rx1day/Rx5day, annual metrics
│   │       ├── trends.py         Mann-Kendall, Sen's slope, OLS, rolling means
│   │       ├── insights.py       Plain-language, significance-aware summaries
│   │       ├── analysis.py       Orchestration + result caching (all three hazards)
│   │       └── export.py         CSV / PNG / PDF export (all three hazards)
│   ├── tests/
│   └── Dockerfile
├── frontend/
│   └── src/
│       ├── api/                  API client + TypeScript types
│       ├── components/           React UI components (map, charts, results)
│       └── lib/                  Formatting utilities, chart theme
├── docker-compose.yml            Local API + MongoDB
├── render.yaml                   Render deployment blueprint (backend)
├── frontend/vercel.json          Vercel config (frontend)
└── .github/workflows/ci.yml      Lint, test, build, Docker CI
```

---

## Architecture

```
Browser (React)
    │
    │  POST /api/analyses
    ▼
FastAPI (Render)
    │
    ├─ 1. Validate input (Pydantic + rate limiter)
    ├─ 2. Check for cached result in MongoDB  ──→  Return immediately if HIT
    ├─ 3. Fetch only missing years from Open-Meteo ERA5
    │        └─ Cache per grid-cell per year in MongoDB
    ├─ 4. Run: clean → threshold → detect → trends → insights
    └─ 5. Store result in MongoDB → return JSON to browser
```

### Request flow in detail

1. **Input validation** — Strict Pydantic models check all fields (types, ranges, box size, minimum 10-year period). Unknown fields are rejected.
2. **Cache lookup** — A deterministic SHA-256 ID is computed from the normalized request + algorithm version. If that analysis exists in MongoDB, it's returned instantly with `X-Cache: HIT`.
3. **Data fetching** — The region is mapped to ERA5 grid cells (a point → 1 cell; a box → up to 2×2 cells on the 0.25° grid). For each cell, only the *missing years* are fetched from Open-Meteo.
4. **Analysis pipeline** — Clean data → compute threshold → detect events → compute annual indices → run trend tests → generate insights.
5. **Store & return** — Result is written to MongoDB and read back for the response (as required). Identical concurrent requests are coalesced into one computation.

### MongoDB collections

| Collection | Key | Stored | Expiry |
|---|---|---|---|
| `daily_cache` | `era5:tmax:{lat}:{lon}:{year}` | 365/366 daily Tmax values | Never (historical ERA5 is immutable) |
| `daily_cache` | `era5:precip:{lat}:{lon}:{year}` | 365/366 daily precipitation values | Never |
| `analyses` | 24-hex SHA-256 analysis ID | Full result: indices, trends, events, insights, data-quality report | 30 days (TTL index) |

Caching per *cell-year* means overlapping requests share data. For example, a 1990–2020 analysis followed by a 1990–2024 one will only fetch 2021–2024 data.

---

## Data Source

**[Open-Meteo Historical Weather API](https://open-meteo.com/en/docs/historical-weather-api)** — variables `temperature_2m_max` (daily max 2 m temperature) and `precipitation_sum` (daily precipitation) from the **ECMWF ERA5** reanalysis.

- Coverage: 1940–present, ~0.25° (~28 km) grid, global
- License: CC BY 4.0, no API key required

**Why ERA5 instead of alternatives:**
- Global and gap-free since 1940 — users can click anywhere on the map.
- **`models=era5` is pinned** (not Open-Meteo's default `best_match`). `best_match` blends ERA5, ERA5-Land and IFS over time, which can introduce artificial jumps into a long record. For trend analysis, a *homogeneous* record matters more than the highest resolution.
- `timezone=auto` so "daily maximum" refers to the local calendar day, not UTC.

**Alternatives considered:**
- NOAA GHCN-Daily: station observations (more "real"), but patchy coverage and common gaps/station moves.
- Copernicus CDS: same ERA5, but requires an account and asynchronous job queues — too slow for interactive use.

---

## Data Handling

ERA5 is relatively clean, but the pipeline handles messy data at every step. Every issue encountered is counted in a **data-quality report** returned with each analysis and shown in the UI.

| Problem | How it's handled |
|---|---|
| **Missing timestamps** | Series is reindexed to a full daily calendar; missing dates become explicit gaps. Duplicate dates are averaged. |
| **Null values** | Stored as `null` in the cache so they survive the round trip. |
| **Short gaps (≤2 days)** | Linearly interpolated. Longer gaps are left as-is — inventing several days of temperature would bias heatwave detection. |
| **Missing day inside a hot spell** | Breaks the heatwave run (conservative approach). |
| **Implausible values** | Values outside −90 °C to +60 °C (beyond world records) are removed. |
| **Spikes** | A single day >20 °C away from *both* neighbours in the same direction is treated as a data error. Genuine heatwaves build over days and aren't affected — there's a test for this. |
| **Incomplete years** | Years with >5% missing days are excluded from annual statistics and shown as gaps (not zeros) in charts. |
| **Units** | Celsius is requested explicitly. The `daily_units` field in the API response is checked anyway; °F and K are converted automatically. |
| **Bad upstream responses** | Shape validation checks that `time` and value arrays match. Non-numeric values → NaN. A bad upstream response returns a 502, never a 500. |
| **Spatial aggregation (boxes)** | Daily Tmax = mean of sampled cells. A day is only counted if at least half the cells report a value. |
| **Leap years** | Feb 29 shares Feb 28's day-of-year threshold. |

---

## Hazard Detection Logic

All three hazard types share the same trend analysis pipeline (Mann-Kendall, Sen's slope, OLS, rolling mean). Detection logic is specific to each hazard.

---

### Heatwave

> A **heatwave** is a run of **≥ 3 consecutive days** on which the daily maximum temperature is **strictly above the 95th percentile** of daily maximum temperature for that region, computed over a **fixed baseline period (default 1961–1990)**.

All parameters are adjustable in the UI: percentile (80–99.9), minimum duration (2–10 days), baseline period (any ≥10-year range).

**Two threshold methods:**
- **Fixed regional threshold** (default): one value for the whole year. Captures *absolute* heat hazard — the kind that harms health, crops and infrastructure.
- **Calendar-day threshold**: a separate 95th percentile per day-of-year, computed from a 15-day window (Perkins & Alexander 2013, CTX90pct). Captures days *unusually hot for the season*.

**Key design decision — fixed baseline, not rolling:** Computing the threshold from the analysis window itself would raise the bar as climate warms, hiding the trend. Using 1961–1990 (WMO standard) gives a stable reference; baseline data is fetched even outside the selected period.

**Event attribution:** Events are assigned to the year they *start* in. Detection runs on the full continuous series so events spanning New Year (common in Southern Hemisphere summers) are not split.

**Annual indices:**

| Metric | Meaning |
|---|---|
| `heatwave_days` | Total days inside heatwaves — headline metric |
| `event_count` | Number of heatwaves per year |
| `longest_event_days` | Duration of the longest heatwave |
| `peak_tmax_c` | Hottest single day in any heatwave |
| `cumulative_excess_cdays` | Sum of (Tmax − threshold) over heatwave days |
| `exceedance_days` | All days above the threshold (not just those in heatwaves) |
| `mean_annual_tmax_c` | Background mean temperature (context) |

---

### Drought

> A **drought spell** is a run of **≥ 7 consecutive dry days**, where a dry day is one with daily precipitation **below 1 mm** (adjustable: 0–50 mm, 3–90 days minimum).

A missing precipitation day is treated as *not dry* (conservative: missing data does not create artificial drought events).

**Annual metrics:** `drought_days`, `event_count`, `max_dry_spell`, `cumulative_deficit_mm` (sum of threshold − precip over dry spell), `total_annual_precip_mm`, `dry_days_total`.

---

### Heavy Rainfall

> A **heavy rainfall event** is one or more consecutive days on which precipitation **exceeds the Xth percentile of wet-day precipitation** (days ≥ 1 mm) computed over a **fixed baseline period (default 1961–1990)**.

Defaults: 95th percentile, ≥1 consecutive day, baseline 1961–1990. All parameters are adjustable.

**Why a percentile baseline:** Absolute thresholds (e.g. "50 mm") are only meaningful for specific climates. A percentile-of-wet-days threshold adapts to local rainfall regimes — 50 mm is normal in a monsoon region but extreme in a desert.

**Annual metrics:** `heavy_days`, `event_count`, `max_event_days`, `total_heavy_precip_mm`, `rx1day_mm` (annual maximum single-day rainfall — WMO standard index), `rx5day_mm`, `total_annual_precip_mm`.

---

## Trend Analysis & Insights

For every annual index, the backend computes:

- **Mann-Kendall test** (two-sided, tie-corrected) — the main significance test. Non-parametric, which suits heatwave counts: they're skewed, have many zero years and a few extreme ones, so they are not normally distributed.
- **Sen's slope** — the median of all pairwise slopes; robust to outlier years. This is the reported trend magnitude (per decade) and the dashed line on every chart.
- **OLS regression** — reports p-value, R² and a 95% CI on the slope, shown for comparison.
- **10-year centred rolling mean** — plotted on charts; tolerates gaps.

The t-distribution and normal-distribution functions are implemented in pure Python (`trends.py`) and validated against standard tables in the tests, avoiding a SciPy dependency.

### Honest insight generation

The headline sentence follows explicit, conservative rules:

1. **"Increased" or "decreased" only when Mann-Kendall p < 0.05.** Between 0.05 and 0.10 it says "weak evidence". Above 0.10 it reports *"no statistically significant trend — year-to-year variability dominates."* A null result is a real finding.
2. **Percent changes compare decade averages** (first 10 vs last 10 years), not noisy endpoint years.
3. **Percentages are suppressed when the early average is below 1 day/year.** Going from 0.2 → 1.0 days is "+400%" — technically true but misleading. It's reported as an absolute change instead.
4. **Caveats always appear:** reanalysis vs station data, spatial averaging for boxes, dependence on baseline choice, the Mann-Kendall independence assumption, and any excluded years.

**Example output:** *"Heatwave days have increased by 100% in Central Gujarat since 1980 (1980–1989 avg 8.4 days/yr vs 2015–2024 avg 16.8); the trend is statistically significant (p = 0.039)."*

---

## API Reference

Interactive docs at `/docs` (OpenAPI).

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/health` | Liveness check + database status |
| `GET` | `/api/meta` | Valid year range, defaults, preset regions |
| `GET` | `/api/geocode?q=` | Place search (Open-Meteo geocoding, cached 24 h) |
| `POST` | `/api/analyses` | Run or fetch an analysis (heatwave / drought / rainfall). `X-Cache: HIT/MISS` |
| `GET` | `/api/analyses/{id}` | Retrieve a stored analysis (shareable via `?id=` in the UI) |
| `GET` | `/api/analyses/{id}/export.csv` | Annual indices + events as CSV |
| `GET` | `/api/analyses/{id}/report.pdf` | 2-page PDF (summary + chart) |
| `GET` | `/api/analyses/{id}/plot.png` | Server-rendered trend plot |

### Example request body

```json
POST /api/analyses
{
  "region": {
    "kind": "bbox",
    "south": 21.5, "west": 71.0, "north": 24.5, "east": 74.0,
    "name": "Central Gujarat"
  },
  "hazard": "heatwave",
  "start_year": 1980,
  "end_year": 2024,
  "params": {
    "percentile": 95,
    "min_duration_days": 3,
    "threshold_method": "fixed",
    "baseline_start": 1961,
    "baseline_end": 1990
  }
}
```

For a drought analysis: set `"hazard": "drought"` and `"params": { "dry_threshold_mm": 1.0, "min_duration_days": 7 }`.

For a heavy rainfall analysis: set `"hazard": "rainfall"` and `"params": { "percentile": 95, "wet_threshold_mm": 1.0, "min_duration_days": 1, "baseline_start": 1961, "baseline_end": 1990 }`.

For a single point: `"region": { "kind": "point", "lat": 28.61, "lon": 77.21, "name": "New Delhi" }`.

---

## Frontend Features

- **Region selection:** unified search box (city, village, or region — debounced geocoding with Nominatim fallback for small places not in Open-Meteo's database), preset regions as quick suggestions, or click the map for a point. ERA5 grid cells used are shown on the map after analysis.
- **Period selection:** any ≥10-year range from 1940 to the last complete year. Quick shortcuts: 1961–1990, 1991–2020, last 30 / 45 years.
- **Hazard selection:** Heatwave (default), Drought, or Heavy Rainfall. Each has its own parameter panel (percentile, duration, threshold, baseline).
- **One-click examples:** Central Gujarat, Phoenix, Delhi NCR, Andalusia — to explore without typing.
- **Loading feedback:** an elapsed-time panel describes each step (cache check → download → quota pacing → analysis) so a ~1 minute cold run doesn't look frozen.

### Visualisations

| Panel | What it shows |
|---|---|
| **Verdict banner** | Significant increase / decrease / weak evidence / no clear trend, with headline insight and stat tiles (% change, Sen slope, significance badge, event count, threshold) |
| **Heat stripes** | (Heatwave) One cell per year shaded by heatwave days — the full record at a glance. Hover for details; excluded years are hatched. |
| **Annual chart** | Bar chart of the primary metric (heatwave days / drought days / heavy rain days) + 10-year rolling mean + Sen trend line. Toggle to a data table. |
| **Small multiples** | (Heatwave) Events/year, longest event, cumulative excess heat, mean Tmax — each with trend and significance badge. |
| **Seasonal cycle** | (Heatwave) Baseline decade vs recent decade vs threshold. |
| **Precipitation trend** | (Drought / Rainfall) Annual total precipitation with Sen trend line. |
| **Events table** | Sortable list of all detected events with duration bar, peak and cumulative metrics. |
| **Data quality panel** | Counts of gaps, interpolations, excluded years, outliers removed. |
| **Method & caveats** | Full description of the algorithm and its limitations. |

**Exports:** CSV and PDF download buttons. **Shareable links:** `?id=<analysis-id>` reloads a stored analysis.

**Accessibility & responsiveness:** Indigo & amber palette, chart colours validated for contrast and colour-vision deficiency, responsive down to phone width, keyboard-accessible controls.

---

## Security & Performance

### Input safety

- Strict Pydantic models with `extra="forbid"` — unknown fields (including MongoDB operator injections like `$where`) are rejected.
- All coordinates, years, percentile, duration and box size (≤5° per side) are range-validated.
- Region names have control characters stripped and a length cap.
- MongoDB queries are built only from server-generated keys — no user-supplied data ever reaches a query.
- Path parameters are regex-validated (`^[0-9a-f]{24}$`).
- Geocoding queries are limited to letters, digits, spaces and basic punctuation.
- **CSV formula-injection protection:** cells starting with `= + - @` are prefixed with `'`.
- Validation errors return concise field messages without echoing raw input. Unhandled errors return a generic 500 with a server-side request ID.
- Request bodies are capped at 16 KB.

### HTTP hardening

- CORS allow-list from env (GET/POST only)
- `X-Content-Type-Options`, `X-Frame-Options: DENY`, `Referrer-Policy`, strict CSP on API responses
- Non-root Docker user

### Rate limiting

- **Inbound (per client IP):** 60 req/min general; **6 req/min for analysis creation** (the expensive endpoint). Returns `429` + `Retry-After`. `X-Forwarded-For` is only trusted when `TRUST_PROXY_HEADERS=true` (behind Render's proxy), preventing IP spoofing.
- **Outbound to Open-Meteo:** The free tier allows ~600 weighted calls/min. A `WeightBudget` estimates each request's cost and waits until it fits, rather than hitting 429s reactively. On an unexpected rate-limit response, it waits a full minute. Hourly/daily quota errors fail fast with a clear message. Transient 5xx errors and timeouts use exponential backoff with jitter. Concurrency is bounded by a semaphore and all calls have timeouts.

### Performance

| Scenario | Typical time |
|---|---|
| Cached analysis (repeat request) | ~10 ms |
| Cold single point (64 years) | ~1.5 s |
| Cold 4-cell box (64 years) | Up to ~65 s (dominated by Open-Meteo quota pacing) |

- Three cache layers: per-cell-year raw data (MongoDB), computed analyses (MongoDB, deterministic IDs), geocoding (in-process, 24 h). Browser caches via TanStack Query.
- Identical in-flight analyses are coalesced — one computation, many waiters.
- Vectorised numpy/pandas detection: ~20,000 days processed in milliseconds.
- GZip responses. On the frontend, Leaflet and Chart.js are lazy-loaded as separate chunks; search is debounced and abortable.

---

## Testing & CI

### Backend (pytest — 50 tests)

Covers: detection edge cases (threshold equality, gaps breaking runs, first/last-day events, year attribution), calendar-day thresholds, leap days, Mann-Kendall/Sen/OLS on known series, t-distribution accuracy against published tables, data cleaning (interpolation limits, spike detection vs real heatwaves, incomplete-year exclusion), insight honesty rules, API cache hit/miss and incremental year fetching, upstream failure → 502, °F conversion, input validation (9 malicious/invalid cases), rate limiting, quota pacing, CSV injection, exports, security headers.

Upstream HTTP calls are mocked with `respx` — tests never hit the network.

### Frontend (vitest)

Formatting utilities and client-side validation. TypeScript compiled in strict mode.

### GitHub Actions (`.github/workflows/ci.yml`)

Runs on every push to `main` and on every pull request:
- Backend: ruff lint + format check + pytest
- Frontend: typecheck + test + build
- Docker: build the backend image (runs after backend tests pass)

---

## Deployment

### Backend → Render (free Docker web service)

1. Create a free **MongoDB Atlas M0** cluster. Add a database user, allow connections from `0.0.0.0/0` (Render free tier has no static IP), copy the connection string.
2. On Render: **New → Blueprint**, point it at this repo (`render.yaml`). Set two environment variables: `MONGODB_URI` and `CORS_ORIGINS` (your Vercel URL).
3. Health check endpoint: `/api/health`.

### Frontend → Vercel

1. Import the repo. Set **Root Directory = `frontend`** (Vite is auto-detected).
2. Add env var: `VITE_API_BASE_URL=https://<your-render-service>.onrender.com`.
3. `vercel.json` handles SPA rewrites and security headers automatically.

> **Free-tier note:** Render sleeps after inactivity. The first request after a sleep takes ~30–60 s to wake the service.

---

## Assumptions

| Assumption | Reason |
|---|---|
| ERA5 reanalysis is an acceptable proxy for observations | Global coverage back to 1940; no API key needed. It's gridded (~28 km), so it under-represents very local extremes like urban heat islands — stated in every result. |
| Daily maximum temperature only | Tmax is the brief's example and most widely available. Operational definitions sometimes also use minimum temperature (hot nights) and humidity/heat index, which matter for health in South Asia. |
| Default baseline 1961–1990 | WMO standard reference period; predates most recent warming, giving a stable threshold. Users can change it. |
| Box = spatial mean over up to 2×2 grid cells | Deliberate trade-off to stay within Open-Meteo's free-tier quota. Boxes are limited to 5° per side and cannot cross the antimeridian. |
| Minimum 10-year analysis period | Fewer data points can't support a meaningful trend test. |
| Latest year = last complete year | ERA5 has a ~5-day publication lag; partial years would distort annual counts. |
| Events count in the year they start | Prevents double-counting events that span New Year. |
| Mann-Kendall significance threshold: p < 0.05 | Standard α level. No multiple-testing correction (the headline metric — heatwave days — is defined in advance). |
| Historical ERA5 data in cache is treated as immutable | The most recent ~3 months are "ERA5T" (preliminary) and can be revised slightly — see improvement #8 below. |

---

## What I'd Improve With More Time

1. **Background jobs for cold requests** — `POST` returns `202` + a job ID; frontend polls or uses a WebSocket for progress updates like "fetching cell 2/4…". Removes the long synchronous HTTP request.
2. **Better trend statistics** — serial-correlation-aware test (Hamed & Rao modified Mann-Kendall or block bootstrap), Poisson/negative-binomial regression for count data, and field-significance correction across multiple metrics.
3. **More hazard types** — cold waves, compound events (hot+dry), and wet-bulb/heat-index heatwaves using humidity. Drought and heavy rainfall are already implemented.
4. **Per-cell detection for boxes** — report "% of area under heatwave" instead of the spatial mean, plus a choropleth of per-cell trends on the map.
5. **Station validation** — compare ERA5 against GHCN-Daily stations where available and show the bias.
6. **Shared rate limiting** — Redis or a MongoDB TTL collection so limits hold across multiple instances, plus auth/API keys for heavy users.
7. **Observability** — structured JSON logs, OpenTelemetry tracing, metrics for cache hit rate and upstream quota usage.
8. **ERA5T revision handling** — re-fetch the most recent ~6 months of cached data periodically.
9. **Frontend** — E2E tests (Playwright), URL-encoded form state, side-by-side region comparison, heatwave "calendar" heatmap (year × day-of-year).

---

## AI Tools Used

I used Claude during this project mainly as a coding assistant for standard, well-defined implementations where the algorithm is known and the work is mostly translation into code.

### What I used AI for

- Typing out the Mann-Kendall and Sen's slope formulas once I had decided to use them and understood how they work. The statistics themselves are textbook; I just didn't want to type 60 lines of formula transcription by hand.
- Scaffolding boilerplate React components — the Chart.js wrappers, table structure, and loading state UI. I reviewed and adjusted all of it before it went in.
- Getting a starting point for the pure-Python t-distribution (needed because SciPy wasn't available on this machine). I verified it against published tables and it matches to within 0.001.
- Generating repetitive parts of the Pydantic schema for the three hazard request types once the structure was decided.

### What I did myself

The parts that actually required judgement or domain knowledge I worked through without AI:

- Choosing ERA5 over other data sources, and pinning models=era5 instead of best_match. This matters for trend analysis — best_match blends different model versions over time and can introduce artificial shifts in a long record.
- Designing the per MongoDB cache structure rather than caching by request range. This took a few iterations to get right so that overlapping date ranges share cached data without collision.
- Deciding on the two-collection TTL strategy — raw ERA5 data never expires, but computed analyses expire after 30 days so algorithm improvements don't get stuck behind old cached results.
- The WeightBudget rate-limiter design. I hit Open-Meteo 429s during testing on large boxes and had to figure out why. I decided to estimate and pace proactively rather than react to errors.
- All the insight generation rules — when to say "increased" vs "weak evidence" vs "no trend", when to suppress percentage changes, and that a null result should be stated honestly.
- The drought and heavy rainfall detection logic — what counts as a dry day, how to handle missing data conservatively, why to use a percentile-of-wet-days threshold for rainfall rather than an absolute value.
- fixing the bugs that came up during testing .

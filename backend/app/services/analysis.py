"""Orchestrates heatwave, drought, and rainfall analyses: ingest -> clean -> detect -> trends -> insights -> store."""

import asyncio
import hashlib
import json
import logging
from datetime import UTC, datetime

import numpy as np
import pandas as pd

from app.config import ALGORITHM_VERSION, Settings
from app.db.repository import Repository
from app.models.schemas import AnalysisRequest, BBoxRegion
from app.services.data_quality import clean_daily_series, clean_precip_series
from app.services.drought import annual_drought_metrics, detect_dry_spells
from app.services.heatwave import annual_metrics, compute_threshold, detect_heatwaves, noleap_doy
from app.services.insights import build_drought_insights, build_insights, build_rainfall_insights
from app.services.rainfall import annual_rainfall_metrics, compute_rainfall_threshold, detect_heavy_rain
from app.services.trends import analyze_trend, rolling_mean
from app.services.weather_data import WeatherDataService

logger = logging.getLogger(__name__)

TREND_METRICS = (
    "heatwave_days",
    "event_count",
    "longest_event_days",
    "cumulative_excess_cdays",
    "mean_heatwave_tmax_c",
    "mean_annual_tmax_c",
    "exceedance_days",
)

DROUGHT_TREND_METRICS = (
    "drought_days",
    "event_count",
    "max_dry_spell",
    "cumulative_deficit_mm",
    "total_annual_precip_mm",
    "dry_days_total",
)

RAINFALL_TREND_METRICS = (
    "heavy_days",
    "event_count",
    "max_event_days",
    "total_heavy_precip_mm",
    "rx1day_mm",
    "rx5day_mm",
    "total_annual_precip_mm",
)

MAX_EVENTS_RETURNED = 1000


class AnalysisError(ValueError):
    """The request is valid but cannot be analysed with the available data."""


def analysis_id(req: AnalysisRequest, settings: Settings) -> str:
    """Returns a deterministic SHA-256 id for the request so identical analyses can be cached."""
    region = req.region.model_dump(exclude={"name"})
    for k, v in region.items():
        if isinstance(v, float):
            region[k] = round(v, 4)
    canonical = {
        "region": region,
        "hazard": req.hazard,
        "start": req.start_year,
        "end": req.end_year,
        "params": req.params.model_dump(),
        "model": settings.open_meteo_model,
        "algo": ALGORITHM_VERSION,
    }
    raw = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


def region_label(req: AnalysisRequest) -> str:
    r = req.region
    if r.name:
        return r.name
    if isinstance(r, BBoxRegion):
        return f"the box {r.south:.2f}–{r.north:.2f}°N, {r.west:.2f}–{r.east:.2f}°E"
    return f"{r.lat:.2f}°, {r.lon:.2f}°"


class AnalysisService:
    def __init__(self, weather: WeatherDataService, repo: Repository, settings: Settings) -> None:
        self._weather = weather
        self._repo = repo
        self._settings = settings
        self._inflight: dict[str, asyncio.Future] = {}

    async def get(self, aid: str) -> dict | None:
        return await self._repo.get_analysis(aid)

    async def get_or_create(self, req: AnalysisRequest) -> tuple[dict, bool]:
        """Returns (analysis document, served_from_cache)."""
        aid = analysis_id(req, self._settings)
        existing = await self._repo.get_analysis(aid)
        if existing is not None:
            return existing, True

        # Coalesce concurrent identical requests into one computation.
        if aid in self._inflight:
            await asyncio.shield(self._inflight[aid])
            doc = await self._repo.get_analysis(aid)
            if doc is not None:
                return doc, True

        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self._inflight[aid] = fut
        try:
            doc = await self._compute(aid, req)
            await self._repo.put_analysis(doc)
            fut.set_result(True)
        except BaseException as exc:
            fut.set_exception(exc)
            fut.exception()  # mark retrieved so asyncio does not log "never retrieved"
            raise
        finally:
            self._inflight.pop(aid, None)
        # Serve what is now in the database, as the API contract requires.
        stored = await self._repo.get_analysis(aid)
        return (stored or doc), False

    async def _compute(self, aid: str, req: AnalysisRequest) -> dict:
        if req.hazard == "drought":
            return await self._compute_drought(aid, req)
        if req.hazard == "rainfall":
            return await self._compute_rainfall(aid, req)
        return await self._compute_heatwave(aid, req)

    async def _compute_heatwave(self, aid: str, req) -> dict:
        p = req.params
        fetch_start = min(req.start_year, p.baseline_start)
        fetch_end = max(req.end_year, p.baseline_end)

        raw, cache_stats, _ = await self._weather.get_region_tmax(
            req.region, fetch_start, fetch_end, self._settings.max_grid_points_per_axis
        )
        tmax, quality = clean_daily_series(raw)
        if tmax.dropna().empty:
            raise AnalysisError("no temperature data available for this region")

        try:
            threshold = compute_threshold(tmax, p.percentile, p.threshold_method, p.baseline_start, p.baseline_end)
        except ValueError as exc:
            raise AnalysisError(str(exc)) from exc

        events = detect_heatwaves(tmax, threshold, p.min_duration_days)
        excluded = set(quality.excluded_years)
        annual = annual_metrics(tmax, events, threshold, req.start_year, req.end_year, excluded)
        in_range = [e for e in events if req.start_year <= e.start.year <= req.end_year]

        years = [r["year"] for r in annual]
        trends = {}
        for key in TREND_METRICS:
            series = [None if r["excluded"] else r[key] for r in annual]
            trends[key] = {**analyze_trend(years, series), "rolling_mean_10y": rolling_mean(series, 10)}

        threshold_label = (
            f"{threshold.fixed_value:.1f} °C ({p.percentile:g}th percentile of {p.baseline_start}–{p.baseline_end} daily Tmax)"
            if threshold.fixed_value is not None
            else f"calendar-day {p.percentile:g}th percentile of {p.baseline_start}–{p.baseline_end} daily Tmax"
        )
        quality_dict = quality.to_dict()
        insights = build_insights(region_label(req), req.start_year, req.end_year, annual, trends, threshold_label, quality_dict)
        if isinstance(req.region, BBoxRegion):
            insights["caveats"].insert(
                1,
                f"Regional values are the spatial mean of {len(cache_stats.points)} grid cells; averaging smooths "
                "local extremes, so a heatwave affecting only part of the box may not be counted.",
            )

        return {
            "_id": aid,
            "id": aid,
            "hazard": req.hazard,
            "request": req.model_dump(),
            "region_label": region_label(req),
            "generated_at": datetime.now(UTC).isoformat(),
            "algorithm_version": ALGORITHM_VERSION,
            "source": {
                "provider": "Open-Meteo Historical Weather API",
                "dataset": f"ECMWF {self._settings.open_meteo_model.upper()} reanalysis",
                "variable": "temperature_2m_max (daily, local time)",
                "units": "°C",
                "grid_points": cache_stats.points,
                "fetched_years": [fetch_start, fetch_end],
            },
            "threshold": {
                "method": threshold.method,
                "percentile": threshold.percentile,
                "baseline": [threshold.baseline_start, threshold.baseline_end],
                "value_c": round(threshold.fixed_value, 2) if threshold.fixed_value is not None else None,
                "label": threshold_label,
                "min_duration_days": p.min_duration_days,
            },
            "climatology": _climatology(tmax, threshold, req, p.baseline_start, p.baseline_end),
            "annual": annual,
            "trends": trends,
            "events": [e.to_dict() for e in sorted(in_range, key=lambda e: e.start)][:MAX_EVENTS_RETURNED],
            "event_total": len(in_range),
            "insights": insights,
            "data_quality": quality_dict,
            "cache": {
                "years_requested": cache_stats.years_requested,
                "years_from_cache": cache_stats.years_from_cache,
                "years_fetched": cache_stats.years_fetched,
                "upstream_calls": cache_stats.upstream_calls,
            },
        }

    async def _compute_drought(self, aid: str, req) -> dict:
        p = req.params
        fetch_start = req.start_year
        fetch_end = req.end_year

        raw, cache_stats, _ = await self._weather.get_region_precip(
            req.region, fetch_start, fetch_end, self._settings.max_grid_points_per_axis
        )
        precip, quality = clean_precip_series(raw)
        if precip.dropna().empty:
            raise AnalysisError("no precipitation data available for this region")

        events = detect_dry_spells(precip, p.dry_threshold_mm, p.min_duration_days)
        excluded = set(quality.excluded_years)
        annual = annual_drought_metrics(precip, events, p.dry_threshold_mm, req.start_year, req.end_year, excluded)
        in_range = [e for e in events if req.start_year <= e.start.year <= req.end_year]

        years = [r["year"] for r in annual]
        trends = {}
        for key in DROUGHT_TREND_METRICS:
            series = [None if r["excluded"] else r[key] for r in annual]
            trends[key] = {**analyze_trend(years, series), "rolling_mean_10y": rolling_mean(series, 10)}

        threshold_label = f"daily precipitation < {p.dry_threshold_mm:.1f} mm"
        quality_dict = quality.to_dict()
        insights = build_drought_insights(
            region_label(req),
            req.start_year,
            req.end_year,
            annual,
            trends,
            threshold_label,
            quality_dict,
        )
        if isinstance(req.region, BBoxRegion):
            insights["caveats"].insert(1, f"Regional values are the spatial mean of {len(cache_stats.points)} grid cells.")

        return {
            "_id": aid,
            "id": aid,
            "hazard": req.hazard,
            "request": req.model_dump(),
            "region_label": region_label(req),
            "generated_at": datetime.now(UTC).isoformat(),
            "algorithm_version": ALGORITHM_VERSION,
            "source": {
                "provider": "Open-Meteo Historical Weather API",
                "dataset": f"ECMWF {self._settings.open_meteo_model.upper()} reanalysis",
                "variable": "precipitation_sum (daily total)",
                "units": "mm",
                "grid_points": cache_stats.points,
                "fetched_years": [fetch_start, fetch_end],
            },
            "threshold": {
                "dry_threshold_mm": p.dry_threshold_mm,
                "min_duration_days": p.min_duration_days,
                "label": threshold_label,
            },
            "climatology": _precip_climatology(precip, req),
            "annual": annual,
            "trends": trends,
            "events": [e.to_dict() for e in sorted(in_range, key=lambda e: e.start)][:MAX_EVENTS_RETURNED],
            "event_total": len(in_range),
            "insights": insights,
            "data_quality": quality_dict,
            "cache": {
                "years_requested": cache_stats.years_requested,
                "years_from_cache": cache_stats.years_from_cache,
                "years_fetched": cache_stats.years_fetched,
                "upstream_calls": cache_stats.upstream_calls,
            },
        }

    async def _compute_rainfall(self, aid: str, req) -> dict:
        p = req.params
        fetch_start = min(req.start_year, p.baseline_start)
        fetch_end = max(req.end_year, p.baseline_end)

        raw, cache_stats, _ = await self._weather.get_region_precip(
            req.region, fetch_start, fetch_end, self._settings.max_grid_points_per_axis
        )
        precip, quality = clean_precip_series(raw)
        if precip.dropna().empty:
            raise AnalysisError("no precipitation data available for this region")

        try:
            threshold_mm = compute_rainfall_threshold(precip, p.percentile, p.wet_threshold_mm, p.baseline_start, p.baseline_end)
        except ValueError as exc:
            raise AnalysisError(str(exc)) from exc

        events = detect_heavy_rain(precip, threshold_mm, p.min_duration_days)
        excluded = set(quality.excluded_years)
        annual = annual_rainfall_metrics(precip, events, threshold_mm, req.start_year, req.end_year, excluded)
        in_range = [e for e in events if req.start_year <= e.start.year <= req.end_year]

        years = [r["year"] for r in annual]
        trends = {}
        for key in RAINFALL_TREND_METRICS:
            series = [None if r["excluded"] else r[key] for r in annual]
            trends[key] = {**analyze_trend(years, series), "rolling_mean_10y": rolling_mean(series, 10)}

        threshold_label = (
            f"{threshold_mm:.1f} mm/day ({p.percentile:g}th percentile of wet-day precip, {p.baseline_start}–{p.baseline_end})"
        )
        quality_dict = quality.to_dict()
        insights = build_rainfall_insights(
            region_label(req),
            req.start_year,
            req.end_year,
            annual,
            trends,
            threshold_label,
            quality_dict,
        )
        if isinstance(req.region, BBoxRegion):
            insights["caveats"].insert(1, f"Regional values are the spatial mean of {len(cache_stats.points)} grid cells.")

        return {
            "_id": aid,
            "id": aid,
            "hazard": req.hazard,
            "request": req.model_dump(),
            "region_label": region_label(req),
            "generated_at": datetime.now(UTC).isoformat(),
            "algorithm_version": ALGORITHM_VERSION,
            "source": {
                "provider": "Open-Meteo Historical Weather API",
                "dataset": f"ECMWF {self._settings.open_meteo_model.upper()} reanalysis",
                "variable": "precipitation_sum (daily total)",
                "units": "mm",
                "grid_points": cache_stats.points,
                "fetched_years": [fetch_start, fetch_end],
            },
            "threshold": {
                "percentile": p.percentile,
                "wet_threshold_mm": p.wet_threshold_mm,
                "value_mm": round(threshold_mm, 2),
                "baseline": [p.baseline_start, p.baseline_end],
                "min_duration_days": p.min_duration_days,
                "label": threshold_label,
            },
            "climatology": _precip_climatology(precip, req),
            "annual": annual,
            "trends": trends,
            "events": [e.to_dict() for e in sorted(in_range, key=lambda e: e.start)][:MAX_EVENTS_RETURNED],
            "event_total": len(in_range),
            "insights": insights,
            "data_quality": quality_dict,
            "cache": {
                "years_requested": cache_stats.years_requested,
                "years_from_cache": cache_stats.years_from_cache,
                "years_fetched": cache_stats.years_fetched,
                "upstream_calls": cache_stats.upstream_calls,
            },
        }


def _climatology(tmax: pd.Series, threshold, req, b0: int, b1: int) -> dict:
    """Mean seasonal cycle for the baseline vs the most recent decade, plus the threshold curve."""
    doy = noleap_doy(tmax.index)
    frame = pd.DataFrame({"t": tmax.to_numpy(), "doy": doy, "year": tmax.index.year})

    def profile(y0: int, y1: int) -> list[float | None]:
        sub = frame[(frame.year >= y0) & (frame.year <= y1)]
        means = sub.groupby("doy")["t"].mean().reindex(range(1, 366))
        # light 7-day circular smoothing to make the seasonal cycle readable
        arr = means.to_numpy()
        padded = np.concatenate([arr[-3:], arr, arr[:3]])
        smooth = pd.Series(padded).rolling(7, center=True, min_periods=4).mean().to_numpy()[3:-3]
        return [None if np.isnan(v) else round(float(v), 2) for v in smooth]

    recent_start = max(req.start_year, req.end_year - 9)
    return {
        "baseline_label": f"{b0}–{b1}",
        "recent_label": f"{recent_start}–{req.end_year}",
        "baseline_mean": profile(b0, b1),
        "recent_mean": profile(recent_start, req.end_year),
        "threshold": [round(float(v), 2) for v in threshold.by_day_of_year],
    }


def _precip_climatology(precip: pd.Series, req) -> dict:
    """Mean seasonal precipitation cycle: baseline vs recent decade."""
    doy = noleap_doy(precip.index)
    frame = pd.DataFrame({"p": precip.to_numpy(), "doy": doy, "year": precip.index.year})
    b0 = getattr(req.params, "baseline_start", req.start_year)
    b1 = getattr(req.params, "baseline_end", req.end_year)

    def profile(y0: int, y1: int) -> list[float | None]:
        sub = frame[(frame.year >= y0) & (frame.year <= y1)]
        means = sub.groupby("doy")["p"].mean().reindex(range(1, 366))
        arr = means.to_numpy()
        padded = np.concatenate([arr[-3:], arr, arr[:3]])
        smooth = pd.Series(padded).rolling(7, center=True, min_periods=4).mean().to_numpy()[3:-3]
        return [None if np.isnan(v) else round(float(v), 2) for v in smooth]

    recent_start = max(req.start_year, req.end_year - 9)
    return {
        "baseline_label": f"{b0}–{b1}",
        "recent_label": f"{recent_start}–{req.end_year}",
        "baseline_mean": profile(b0, b1),
        "recent_mean": profile(recent_start, req.end_year),
    }

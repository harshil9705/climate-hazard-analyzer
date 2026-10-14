"""Fetches and caches daily temperature data from Open-Meteo, handles region sampling."""

import logging
import math
from dataclasses import dataclass, field
from datetime import UTC, date, datetime

import numpy as np
import pandas as pd

from app.db.repository import Repository, daily_doc_id
from app.models.schemas import BBoxRegion, PointRegion
from app.services.open_meteo import OpenMeteoClient

logger = logging.getLogger(__name__)

# ERA5 native grid spacing. Snapping requests to it means nearby requests share cache entries.
GRID_DEG = 0.25
VARIABLE = "tmax"
PRECIP_VARIABLE = "precip"


@dataclass
class CacheStats:
    years_requested: int = 0
    years_from_cache: int = 0
    years_fetched: int = 0
    upstream_calls: int = 0
    points: list[dict] = field(default_factory=list)

    def merge(self, other: "CacheStats") -> None:
        self.years_requested += other.years_requested
        self.years_from_cache += other.years_from_cache
        self.years_fetched += other.years_fetched
        self.upstream_calls += other.upstream_calls


def snap(value: float) -> float:
    return round(round(value / GRID_DEG) * GRID_DEG, 4)


def region_points(region: PointRegion | BBoxRegion, max_per_axis: int) -> list[tuple[float, float]]:
    """Grid cells used to represent a region (deduplicated, snapped to the ERA5 grid)."""
    if isinstance(region, PointRegion):
        return [(snap(region.lat), snap(region.lon))]

    def axis(lo: float, hi: float) -> list[float]:
        n = min(max_per_axis, max(1, math.ceil((hi - lo) / GRID_DEG)))
        if n == 1:
            return [snap((lo + hi) / 2)]
        # cell centres of n equal slices, so the samples sit inside the box
        step = (hi - lo) / n
        return [snap(lo + step * (i + 0.5)) for i in range(n)]

    pts = {(la, lo) for la in axis(region.south, region.north) for lo in axis(region.west, region.east)}
    return sorted(pts)


def series_key(lat: float, lon: float, model: str) -> str:
    return f"{model}:{VARIABLE}:{lat:.2f}:{lon:.2f}"


def precip_series_key(lat: float, lon: float, model: str) -> str:
    return f"{model}:{PRECIP_VARIABLE}:{lat:.2f}:{lon:.2f}"


def _contiguous_ranges(years: list[int]) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    for y in sorted(years):
        if ranges and y == ranges[-1][1] + 1:
            ranges[-1] = (ranges[-1][0], y)
        else:
            ranges.append((y, y))
    return ranges


class WeatherDataService:
    def __init__(self, client: OpenMeteoClient, repo: Repository, model: str) -> None:
        self._client = client
        self._repo = repo
        self._model = model

    async def get_point_tmax(self, lat: float, lon: float, start_year: int, end_year: int) -> tuple[pd.Series, CacheStats]:
        key = series_key(lat, lon, self._model)
        years = list(range(start_year, end_year + 1))
        stats = CacheStats(years_requested=len(years))

        cached = await self._repo.get_daily_years(key, years)
        stats.years_from_cache = len(cached)
        missing = [y for y in years if y not in cached.keys()]

        for lo, hi in _contiguous_ranges(missing):
            fetched = await self._client.fetch_daily_tmax(lat, lon, date(lo, 1, 1), date(hi, 12, 31))
            stats.upstream_calls += 1
            docs = []
            for y in range(lo, hi + 1):
                doc = _year_doc(key, lat, lon, y, fetched, self._model)
                docs.append(doc)
                cached[y] = doc
            await self._repo.put_daily_years(docs)
            stats.years_fetched += hi - lo + 1

        parts = [_doc_to_series(cached[y]) for y in years]
        return pd.concat(parts).sort_index(), stats

    async def get_region_tmax(
        self, region: PointRegion | BBoxRegion, start_year: int, end_year: int, max_per_axis: int
    ) -> tuple[pd.Series, CacheStats, pd.DataFrame]:
        """Spatial mean of daily Tmax across the sampled grid cells.

        Points are fetched sequentially on purpose: it keeps us well inside Open-Meteo's
        per-minute quota, and after the first request most data comes from cache anyway.
        """
        points = region_points(region, max_per_axis)
        total = CacheStats()
        columns = {}
        for lat, lon in points:
            s, st = await self.get_point_tmax(lat, lon, start_year, end_year)
            total.merge(st)
            total.points.append({"lat": lat, "lon": lon})
            columns[f"{lat:.2f},{lon:.2f}"] = s
        frame = pd.DataFrame(columns)
        # Require at least half of the cells to report a value for a day to count.
        valid = frame.notna().sum(axis=1)
        mean = frame.mean(axis=1, skipna=True).where(valid >= math.ceil(frame.shape[1] / 2))
        return mean, total, frame

    async def get_point_precip(self, lat: float, lon: float, start_year: int, end_year: int) -> tuple[pd.Series, CacheStats]:
        key = precip_series_key(lat, lon, self._model)
        years = list(range(start_year, end_year + 1))
        stats = CacheStats(years_requested=len(years))

        cached = await self._repo.get_daily_years(key, years)
        stats.years_from_cache = len(cached)
        missing = [y for y in years if y not in cached.keys()]

        for lo, hi in _contiguous_ranges(missing):
            fetched = await self._client.fetch_daily_precip(lat, lon, date(lo, 1, 1), date(hi, 12, 31))
            stats.upstream_calls += 1
            docs = []
            for y in range(lo, hi + 1):
                doc = _precip_year_doc(key, lat, lon, y, fetched, self._model)
                docs.append(doc)
                cached[y] = doc
            await self._repo.put_daily_years(docs)
            stats.years_fetched += hi - lo + 1

        parts = [_doc_to_series(cached[y]) for y in years]
        return pd.concat(parts).sort_index(), stats

    async def get_region_precip(
        self, region: PointRegion | BBoxRegion, start_year: int, end_year: int, max_per_axis: int
    ) -> tuple[pd.Series, CacheStats, pd.DataFrame]:
        points = region_points(region, max_per_axis)
        total = CacheStats()
        columns = {}
        for lat, lon in points:
            s, st = await self.get_point_precip(lat, lon, start_year, end_year)
            total.merge(st)
            total.points.append({"lat": lat, "lon": lon})
            columns[f"{lat:.2f},{lon:.2f}"] = s
        frame = pd.DataFrame(columns)
        valid = frame.notna().sum(axis=1)
        mean = frame.mean(axis=1, skipna=True).where(valid >= math.ceil(frame.shape[1] / 2))
        return mean, total, frame


def _precip_year_doc(key: str, lat: float, lon: float, year: int, fetched: pd.Series, model: str) -> dict:
    idx = pd.date_range(f"{year}-01-01", f"{year}-12-31", freq="D")
    values = fetched.reindex(idx).to_numpy(dtype=float)
    return {
        "_id": daily_doc_id(key, year),
        "series_key": key,
        "lat": lat,
        "lon": lon,
        "year": year,
        "variable": PRECIP_VARIABLE,
        "units": "mm",
        "source": "open-meteo-archive",
        "model": model,
        "values": [None if np.isnan(v) else round(float(v), 2) for v in values],
        "fetched_at": datetime.now(UTC),
    }


def _year_doc(key: str, lat: float, lon: float, year: int, fetched: pd.Series, model: str) -> dict:
    idx = pd.date_range(f"{year}-01-01", f"{year}-12-31", freq="D")
    values = fetched.reindex(idx).to_numpy(dtype=float)
    return {
        "_id": daily_doc_id(key, year),
        "series_key": key,
        "lat": lat,
        "lon": lon,
        "year": year,
        "variable": VARIABLE,
        "units": "degC",
        "source": "open-meteo-archive",
        "model": model,
        # Missing days stored as null so gaps survive the round-trip through the cache.
        "values": [None if np.isnan(v) else round(float(v), 2) for v in values],
        "fetched_at": datetime.now(UTC),
    }


def _doc_to_series(doc: dict) -> pd.Series:
    year = int(doc["year"])
    idx = pd.date_range(f"{year}-01-01", f"{year}-12-31", freq="D")
    vals = np.array([np.nan if v is None else v for v in doc["values"]], dtype=float)
    if len(vals) != len(idx):  # defensive: corrupt cache entry
        vals = np.resize(np.append(vals, [np.nan] * len(idx)), len(idx))
    return pd.Series(vals, index=idx)

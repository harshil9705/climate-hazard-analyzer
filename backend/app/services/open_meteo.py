"""Thin, defensive client for the Open-Meteo historical (ERA5) and geocoding APIs."""

import asyncio
import logging
import random
import time
from datetime import date

import httpx
import numpy as np
import pandas as pd

from app.config import Settings
from app.models.schemas import GeocodeResult

logger = logging.getLogger(__name__)

RETRYABLE_STATUS = {429, 500, 502, 503, 504}
MAX_RETRY_AFTER_S = 30.0
MINUTE_LIMIT_WAIT_S = 61.0


class UpstreamError(RuntimeError):
    """Raised when the upstream data provider fails or returns unusable data."""


class UpstreamQuotaError(UpstreamError):
    """The provider's hourly/daily quota is exhausted; retrying now will not help."""


def estimate_weight(days: int, variables: int = 1, locations: int = 1) -> float:
    """Open-Meteo counts a request as several "calls" depending on its size.

    Documented rule of thumb: >10 variables or >2 weeks of data count as multiple calls. Weight here is
    proportional to (days / 14) * (variables / 10), never below 1 per location.
    """
    return max(1.0, (days / 14.0) * (variables / 10.0)) * locations


class WeightBudget:
    """Tracks API call weight over a sliding 60s window to avoid hitting the rate limit."""

    def __init__(self, per_minute: float, window_s: float = 60.0) -> None:
        self._limit = per_minute
        self._window = window_s
        self._spent: list[tuple[float, float]] = []
        self._lock = asyncio.Lock()

    async def acquire(self, weight: float) -> float:
        """Blocks until `weight` fits in the budget. Returns seconds waited."""
        weight = min(weight, self._limit)  # a single oversized request still gets to run alone
        waited = 0.0
        async with self._lock:
            while True:
                now = time.monotonic()
                self._spent = [(t, w) for t, w in self._spent if now - t < self._window]
                used = sum(w for _, w in self._spent)
                if used + weight <= self._limit:
                    self._spent.append((now, weight))
                    return waited
                delay = self._window - (now - self._spent[0][0]) + 0.5
                logger.info("Upstream budget full (%.0f/%.0f), waiting %.1fs", used, self._limit, delay)
                await asyncio.sleep(delay)
                waited += delay

    def penalise(self) -> None:
        """After an unexpected minutely 429, treat the whole window as spent."""
        self._spent = [(time.monotonic(), self._limit)]


class OpenMeteoClient:
    def __init__(self, http: httpx.AsyncClient, settings: Settings) -> None:
        self._http = http
        self._settings = settings
        # Bound concurrent upstream calls, and pace them by estimated weight (free tier is ~600 calls/min).
        self._semaphore = asyncio.Semaphore(settings.upstream_concurrency)
        self._budget = WeightBudget(settings.upstream_weight_per_minute)
        self._archive_url = settings.open_meteo_archive_url
        if settings.open_meteo_api_key:
            self._archive_url = settings.open_meteo_archive_url.replace("://archive-api.", "://customer-archive-api.")

    async def _get_json(self, url: str, params: dict, weight: float = 1.0) -> dict:
        if self._settings.open_meteo_api_key:
            params = {**params, "apikey": self._settings.open_meteo_api_key}
        attempts = self._settings.upstream_max_retries + 1
        for attempt in range(1, attempts + 1):
            await self._budget.acquire(weight)
            try:
                async with self._semaphore:
                    resp = await self._http.get(url, params=params, timeout=self._settings.http_timeout_s)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                if attempt == attempts:
                    raise UpstreamError("weather data provider is unreachable") from exc
                await asyncio.sleep(self._backoff(attempt))
                continue

            if resp.status_code == 429:
                reason = _safe_reason(resp).lower()
                if "hourly" in reason or "daily" in reason or "monthly" in reason:
                    logger.error("Open-Meteo quota exhausted: %s", reason)
                    raise UpstreamQuotaError("weather data provider quota exhausted, please try again later")
                if attempt < attempts:
                    self._budget.penalise()
                    delay = self._retry_after(resp) or (MINUTE_LIMIT_WAIT_S if "minute" in reason else self._backoff(attempt))
                    logger.warning("Open-Meteo 429 (%s), retrying in %.0fs", reason or "rate limited", delay)
                    await asyncio.sleep(delay)
                    continue
            elif resp.status_code in RETRYABLE_STATUS and attempt < attempts:
                delay = self._retry_after(resp) or self._backoff(attempt)
                logger.warning("Open-Meteo %s, retrying in %.1fs (attempt %d)", resp.status_code, delay, attempt)
                await asyncio.sleep(delay)
                continue
            if resp.status_code != 200:
                logger.error("Open-Meteo error %s: %s", resp.status_code, _safe_reason(resp))
                raise UpstreamError(f"weather data provider returned {resp.status_code}")
            try:
                return resp.json()
            except ValueError as exc:
                raise UpstreamError("weather data provider returned invalid JSON") from exc
        raise UpstreamError("weather data provider failed")  # pragma: no cover

    @staticmethod
    def _backoff(attempt: int) -> float:
        return min(2**attempt, 20) + random.uniform(0, 1)

    @staticmethod
    def _retry_after(resp: httpx.Response) -> float | None:
        value = resp.headers.get("Retry-After")
        if not value:
            return None
        try:
            return min(float(value), MAX_RETRY_AFTER_S)
        except ValueError:
            return None

    async def fetch_daily_tmax(self, lat: float, lon: float, start: date, end: date) -> pd.Series:
        """Daily maximum 2 m temperature in deg C, indexed by local calendar date."""
        params = {
            "latitude": f"{lat:.4f}",
            "longitude": f"{lon:.4f}",
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "daily": "temperature_2m_max",
            "temperature_unit": "celsius",
            "timezone": "auto",  # daily max over the *local* day, not the UTC day
            "models": self._settings.open_meteo_model,
        }
        payload = await self._get_json(self._archive_url, params, weight=estimate_weight((end - start).days + 1))
        return parse_daily_tmax(payload)

    async def fetch_daily_precip(self, lat: float, lon: float, start: date, end: date) -> pd.Series:
        """Daily precipitation sum in mm, indexed by local calendar date."""
        params = {
            "latitude": f"{lat:.4f}",
            "longitude": f"{lon:.4f}",
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "daily": "precipitation_sum",
            "timezone": "auto",
            "models": self._settings.open_meteo_model,
        }
        payload = await self._get_json(self._archive_url, params, weight=estimate_weight((end - start).days + 1))
        return parse_daily_precip(payload)

    async def geocode(self, query: str, count: int = 8) -> list[GeocodeResult]:
        params = {"name": query, "count": count, "language": "en", "format": "json"}
        payload = await self._get_json(self._settings.open_meteo_geocoding_url, params)
        results = []
        for item in payload.get("results") or []:
            try:
                results.append(
                    GeocodeResult(
                        name=str(item["name"]),
                        lat=float(item["latitude"]),
                        lon=float(item["longitude"]),
                        country=item.get("country"),
                        admin1=item.get("admin1"),
                        population=item.get("population"),
                    )
                )
            except (KeyError, TypeError, ValueError):
                continue
        return results

    async def geocode_nominatim(self, query: str, count: int = 8) -> list[GeocodeResult]:
        """Fallback geocoder using Nominatim (OpenStreetMap). Better coverage of small villages."""
        params = {
            "q": query,
            "format": "jsonv2",
            "limit": count,
            "addressdetails": 1,
            "accept-language": "en",
        }
        try:
            resp = await self._http.get(
                "https://nominatim.openstreetmap.org/search",
                params=params,
                headers={"User-Agent": "ClimateHazardAnalyzer/1.0"},
                timeout=10.0,
            )
            if resp.status_code != 200:
                return []
            items = resp.json()
        except (httpx.HTTPError, ValueError, KeyError):
            return []

        results = []
        seen: set[tuple[float, float]] = set()
        for item in items:
            try:
                lat = round(float(item["lat"]), 4)
                lon = round(float(item["lon"]), 4)
                if (lat, lon) in seen:
                    continue
                seen.add((lat, lon))
                addr = item.get("address", {})
                name = (
                    addr.get("village")
                    or addr.get("town")
                    or addr.get("city")
                    or addr.get("hamlet")
                    or addr.get("suburb")
                    or item.get("display_name", "").split(",")[0]
                )
                country = addr.get("country")
                admin1 = addr.get("state") or addr.get("county")
                results.append(GeocodeResult(name=str(name), lat=lat, lon=lon, country=country, admin1=admin1, population=None))
            except (KeyError, TypeError, ValueError):
                continue
        return results


def parse_daily_tmax(payload: dict) -> pd.Series:
    daily = payload.get("daily")
    if not isinstance(daily, dict):
        raise UpstreamError("response is missing daily data")
    times = daily.get("time")
    values = daily.get("temperature_2m_max")
    if not isinstance(times, list) or not isinstance(values, list) or len(times) != len(values):
        raise UpstreamError("daily data is malformed")

    index = pd.to_datetime(times, errors="coerce")
    series = pd.Series(pd.to_numeric(pd.Series(values), errors="coerce").to_numpy(dtype=float), index=index)
    series = series[~series.index.isna()]
    series = series[~series.index.duplicated(keep="first")].sort_index()

    unit = (payload.get("daily_units") or {}).get("temperature_2m_max", "°C")
    if "F" in unit:
        series = (series - 32.0) * 5.0 / 9.0
    elif "K" in unit:
        series = series - 273.15
    return series.astype(np.float64)


def parse_daily_precip(payload: dict) -> pd.Series:
    daily = payload.get("daily")
    if not isinstance(daily, dict):
        raise UpstreamError("response is missing daily data")
    times = daily.get("time")
    values = daily.get("precipitation_sum")
    if not isinstance(times, list) or not isinstance(values, list) or len(times) != len(values):
        raise UpstreamError("daily precipitation data is malformed")

    index = pd.to_datetime(times, errors="coerce")
    series = pd.Series(pd.to_numeric(pd.Series(values), errors="coerce").to_numpy(dtype=float), index=index)
    series = series[~series.index.isna()]
    series = series[~series.index.duplicated(keep="first")].sort_index()
    return series.astype(np.float64)


def _safe_reason(resp: httpx.Response) -> str:
    try:
        return str(resp.json().get("reason", ""))[:200]
    except ValueError:
        return resp.text[:200]

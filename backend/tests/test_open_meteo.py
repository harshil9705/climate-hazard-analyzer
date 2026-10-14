import asyncio
from datetime import date

import httpx
import pytest
import respx

from app.config import Settings
from app.models.schemas import BBoxRegion
from app.services import open_meteo
from app.services.open_meteo import OpenMeteoClient, UpstreamQuotaError, WeightBudget, estimate_weight
from app.services.weather_data import region_points

ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"


def test_estimate_weight_scales_with_period():
    assert estimate_weight(7) == 1.0
    assert estimate_weight(365 * 64) == pytest.approx(166.9, abs=0.5)
    assert estimate_weight(365, locations=4) == pytest.approx(4 * 365 / 140)


async def test_weight_budget_waits_when_full(monkeypatch):
    slept = []

    async def fake_sleep(s):
        slept.append(s)
        budget._spent = []  # simulate the window rolling over

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    budget = WeightBudget(per_minute=100)
    assert await budget.acquire(60) == 0
    waited = await budget.acquire(60)
    assert waited > 0 and len(slept) == 1


@respx.mock
async def test_daily_quota_429_is_not_retried():
    route = respx.get(ARCHIVE).mock(
        return_value=httpx.Response(429, json={"error": True, "reason": "Daily API request limit exceeded."})
    )
    client = OpenMeteoClient(httpx.AsyncClient(), Settings(upstream_max_retries=3))
    with pytest.raises(UpstreamQuotaError):
        await client.fetch_daily_tmax(10, 10, date(2000, 1, 1), date(2000, 12, 31))
    assert route.call_count == 1


@respx.mock
async def test_minutely_429_waits_then_retries(monkeypatch):
    slept = []

    async def fake_sleep(s):
        slept.append(s)
        client._budget._spent = []  # simulate the minute window rolling over

    monkeypatch.setattr(open_meteo.asyncio, "sleep", fake_sleep)
    ok = {"daily_units": {"temperature_2m_max": "°C"}, "daily": {"time": ["2000-01-01"], "temperature_2m_max": [20.0]}}
    respx.get(ARCHIVE).mock(
        side_effect=[
            httpx.Response(
                429, json={"error": True, "reason": "Minutely API request limit exceeded. Please try again in one minute."}
            ),
            httpx.Response(200, json=ok),
        ]
    )
    client = OpenMeteoClient(httpx.AsyncClient(), Settings(upstream_max_retries=2))

    s = await client.fetch_daily_tmax(10, 10, date(2000, 1, 1), date(2000, 1, 1))
    assert s.iloc[0] == 20.0
    assert max(slept) >= 60


def test_bbox_is_sampled_with_bounded_grid():
    pts = region_points(BBoxRegion(south=21.5, west=71, north=24.5, east=74), max_per_axis=2)
    assert len(pts) == 4
    assert all(21.5 <= la <= 24.5 and 71 <= lo <= 74 for la, lo in pts)
    assert all((la * 4).is_integer() and (lo * 4).is_integer() for la, lo in pts)  # snapped to 0.25 deg grid

"""API tests with the upstream provider mocked (respx) and an in-memory repository."""

import httpx
import pytest
import respx

from app.config import Settings
from app.core.rate_limit import limiter
from app.db.repository import MemoryRepository
from app.main import create_app
from tests.conftest import open_meteo_payload, synthetic_tmax

ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"
GEOCODE = "https://geocoding-api.open-meteo.com/v1/search"
BODY = {"region": {"kind": "point", "lat": 28.61, "lon": 77.21, "name": "New Delhi"}, "start_year": 1990, "end_year": 2020}


def _archive_handler(request: httpx.Request) -> httpx.Response:
    p = request.url.params
    series = synthetic_tmax(int(p["start_date"][:4]), int(p["end_date"][:4]), warming_per_year=0.05)
    return httpx.Response(200, json=open_meteo_payload(series))


@pytest.fixture
async def client():
    limiter.reset()
    settings = Settings(mongodb_uri="", analysis_rate_limit_per_minute=50, rate_limit_per_minute=100, upstream_max_retries=1)
    repo = MemoryRepository()
    app = create_app(settings=settings, repo=repo, http=httpx.AsyncClient())
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
            yield c


@respx.mock
async def test_analysis_is_computed_then_served_from_cache(client):
    route = respx.get(ARCHIVE).mock(side_effect=_archive_handler)
    r1 = await client.post("/api/analyses", json=BODY)
    assert r1.status_code == 200, r1.text
    assert r1.headers["x-cache"] == "MISS"
    data = r1.json()
    assert data["threshold"]["baseline"] == [1961, 1990]
    assert len(data["annual"]) == 31
    assert data["insights"]["headline"]
    assert data["cache"]["upstream_calls"] == 1

    r2 = await client.post("/api/analyses", json=BODY)
    assert r2.headers["x-cache"] == "HIT"
    assert route.call_count == 1

    r3 = await client.get(f"/api/analyses/{data['id']}")
    assert r3.status_code == 200 and r3.json()["id"] == data["id"]


@respx.mock
async def test_overlapping_request_only_fetches_missing_years(client):
    route = respx.get(ARCHIVE).mock(side_effect=_archive_handler)
    await client.post("/api/analyses", json=BODY)
    r = await client.post("/api/analyses", json={**BODY, "end_year": 2023})
    assert r.status_code == 200
    assert r.json()["cache"]["years_fetched"] == 3  # 2021-2023 only
    last_params = route.calls.last.request.url.params
    assert last_params["start_date"] == "2021-01-01"


@respx.mock
async def test_upstream_failure_maps_to_502(client):
    respx.get(ARCHIVE).mock(return_value=httpx.Response(500))
    r = await client.post("/api/analyses", json=BODY)
    assert r.status_code == 502


@respx.mock
async def test_malformed_upstream_payload_maps_to_502(client):
    respx.get(ARCHIVE).mock(return_value=httpx.Response(200, json={"daily": {"time": ["2000-01-01"], "temperature_2m_max": []}}))
    r = await client.post("/api/analyses", json=BODY)
    assert r.status_code == 502


@respx.mock
async def test_fahrenheit_payload_is_converted(client):
    def handler(request):
        p = request.url.params
        s = synthetic_tmax(int(p["start_date"][:4]), int(p["end_date"][:4])) * 9 / 5 + 32
        payload = open_meteo_payload(s)
        payload["daily_units"]["temperature_2m_max"] = "°F"
        return httpx.Response(200, json=payload)

    respx.get(ARCHIVE).mock(side_effect=handler)
    r = await client.post("/api/analyses", json=BODY)
    assert r.status_code == 200
    assert 25 < r.json()["threshold"]["value_c"] < 45


@pytest.mark.parametrize(
    "patch",
    [
        {"start_year": 1800},
        {"end_year": 2999},
        {"start_year": 2015, "end_year": 2020},
        {"region": {"kind": "point", "lat": 95, "lon": 0}},
        {"region": {"kind": "bbox", "south": 10, "west": 10, "north": 9, "east": 11}},
        {"region": {"kind": "bbox", "south": 0, "west": 0, "north": 20, "east": 2}},
        {"region": {"kind": "point", "lat": 1, "lon": 1, "$where": "1"}},
        {"params": {"percentile": 50}},
        {"hazard": "tornado"},
    ],
)
async def test_invalid_input_is_rejected(client, patch):
    r = await client.post("/api/analyses", json={**BODY, **patch})
    assert r.status_code == 422
    assert r.json()["detail"] == "Invalid request"


async def test_invalid_analysis_id_is_rejected(client):
    assert (await client.get("/api/analyses/../../etc")).status_code == 404
    assert (await client.get("/api/analyses/not-an-id")).status_code == 422
    assert (await client.get("/api/analyses/" + "a" * 24)).status_code == 404


async def test_oversized_body_rejected(client):
    r = await client.post("/api/analyses", content=b"x" * 20000, headers={"content-type": "application/json"})
    assert r.status_code == 413


@respx.mock
async def test_rate_limit_returns_429_with_retry_after():
    limiter.reset()
    settings = Settings(mongodb_uri="", analysis_rate_limit_per_minute=2)
    app = create_app(settings=settings, repo=MemoryRepository(), http=httpx.AsyncClient())
    respx.get(ARCHIVE).mock(side_effect=_archive_handler)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
            codes = [(await c.post("/api/analyses", json=BODY)).status_code for _ in range(3)]
            assert codes == [200, 200, 429]
            r = await c.post("/api/analyses", json=BODY)
            assert int(r.headers["retry-after"]) > 0


@respx.mock
async def test_geocode_validates_and_caches(client):
    route = respx.get(GEOCODE).mock(
        return_value=httpx.Response(
            200, json={"results": [{"name": "Pune", "latitude": 18.52, "longitude": 73.85, "country": "India"}, {"bad": 1}]}
        )
    )
    r1 = await client.get("/api/geocode", params={"q": "Pune"})
    r2 = await client.get("/api/geocode", params={"q": "  pune "})
    assert r1.status_code == 200 and r1.json()[0]["name"] == "Pune" and len(r1.json()) == 1
    assert r2.headers["x-cache"] == "HIT" and route.call_count == 1
    assert (await client.get("/api/geocode", params={"q": "<script>"})).status_code == 422


@respx.mock
async def test_exports(client):
    respx.get(ARCHIVE).mock(side_effect=_archive_handler)
    aid = (await client.post("/api/analyses", json={**BODY, "region": {**BODY["region"], "name": "=HYPERLINK(evil)"}})).json()[
        "id"
    ]
    csv = await client.get(f"/api/analyses/{aid}/export.csv")
    assert csv.status_code == 200 and "year,excluded,event_count" in csv.text
    assert "'=HYPERLINK" in csv.text  # formula injection neutralised
    pdf = await client.get(f"/api/analyses/{aid}/report.pdf")
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"


async def test_security_headers_present(client):
    r = await client.get("/api/health")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"

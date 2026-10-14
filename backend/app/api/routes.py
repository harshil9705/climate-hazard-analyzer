import re
import time
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, Response
from fastapi.responses import JSONResponse

from app.config import MIN_YEAR, last_complete_year
from app.core.rate_limit import rate_limit
from app.models.schemas import AnalysisRequest, GeocodeResult
from app.services import export
from app.services.analysis import AnalysisError, AnalysisService
from app.services.open_meteo import OpenMeteoClient, UpstreamError

router = APIRouter(prefix="/api")

default_limit = Depends(rate_limit("default", "rate_limit_per_minute"))
analysis_limit = Depends(rate_limit("analysis", "analysis_rate_limit_per_minute"))

AnalysisId = Annotated[str, Path(pattern=r"^[0-9a-f]{24}$", description="Analysis id")]

# Preset regions (bounding boxes kept within the 5 degree limit).
PRESETS = [
    {"id": "delhi-ncr", "name": "Delhi NCR, India", "kind": "bbox", "south": 28.2, "west": 76.8, "north": 29.0, "east": 77.6},
    {"id": "gujarat", "name": "Central Gujarat, India", "kind": "bbox", "south": 21.5, "west": 71.0, "north": 24.5, "east": 74.0},
    {
        "id": "west-rajasthan",
        "name": "Western Rajasthan, India",
        "kind": "bbox",
        "south": 25.0,
        "west": 70.0,
        "north": 29.0,
        "east": 75.0,
    },
    {"id": "mumbai", "name": "Mumbai, India", "kind": "point", "lat": 19.076, "lon": 72.8777},
    {
        "id": "ile-de-france",
        "name": "Île-de-France, France",
        "kind": "bbox",
        "south": 48.1,
        "west": 1.4,
        "north": 49.2,
        "east": 3.6,
    },
    {"id": "andalusia", "name": "Andalusia, Spain", "kind": "bbox", "south": 36.0, "west": -6.5, "north": 38.7, "east": -2.0},
    {
        "id": "central-valley",
        "name": "Central Valley, California",
        "kind": "bbox",
        "south": 35.0,
        "west": -122.5,
        "north": 40.0,
        "east": -118.5,
    },
    {"id": "phoenix", "name": "Phoenix, Arizona", "kind": "point", "lat": 33.4484, "lon": -112.074},
    {
        "id": "sydney",
        "name": "Greater Sydney, Australia",
        "kind": "bbox",
        "south": -34.2,
        "west": 150.5,
        "north": -33.4,
        "east": 151.4,
    },
]

_GEOCODE_TTL_S = 24 * 3600
_GEOCODE_MAX_ENTRIES = 2000
_geocode_cache: dict[str, tuple[float, list[GeocodeResult]]] = {}
_QUERY_RE = re.compile(r"^[\w\s.,'()-]+$", re.UNICODE)


def get_analysis_service(request: Request) -> AnalysisService:
    return request.app.state.analysis_service


def get_open_meteo(request: Request) -> OpenMeteoClient:
    return request.app.state.open_meteo


def _public(doc: dict) -> dict:
    return {k: v for k, v in doc.items() if k not in ("_id", "created_at")}


@router.get("/health", tags=["meta"])
async def health(request: Request):
    db_ok = await request.app.state.repo.ping()
    return {"status": "ok" if db_ok else "degraded", "database": request.app.state.repo_kind, "database_ok": db_ok}


@router.get("/meta", tags=["meta"], dependencies=[default_limit])
async def meta():
    return {
        "hazards": [
            {"id": "heatwave", "label": "Heatwave", "default": True},
            {"id": "drought", "label": "Drought"},
            {"id": "rainfall", "label": "Heavy rainfall"},
        ],
        "min_year": MIN_YEAR,
        "max_year": last_complete_year(),
        "default_range": [1990, min(2020, last_complete_year())],
        "default_params": {
            "percentile": 95,
            "min_duration_days": 3,
            "threshold_method": "fixed",
            "baseline_start": 1961,
            "baseline_end": 1990,
        },
        "presets": PRESETS,
    }


@router.get("/geocode", response_model=list[GeocodeResult], tags=["regions"], dependencies=[default_limit])
async def geocode(
    response: Response,
    q: Annotated[str, Query(min_length=2, max_length=80)],
    client: OpenMeteoClient = Depends(get_open_meteo),
):
    query = " ".join(q.split())
    if not _QUERY_RE.match(query):
        raise HTTPException(422, "Search text contains unsupported characters")
    key = query.lower()
    now = time.monotonic()
    hit = _geocode_cache.get(key)
    if hit and now - hit[0] < _GEOCODE_TTL_S:
        response.headers["X-Cache"] = "HIT"
        return hit[1]
    try:
        results = await client.geocode(query)
    except UpstreamError as exc:
        raise HTTPException(502, str(exc)) from exc

    if len(results) < 2:
        nominatim = await client.geocode_nominatim(query)
        existing_coords = {(r.lat, r.lon) for r in results}
        for r in nominatim:
            if (r.lat, r.lon) not in existing_coords:
                results.append(r)
                existing_coords.add((r.lat, r.lon))

    if len(_geocode_cache) >= _GEOCODE_MAX_ENTRIES:
        _geocode_cache.pop(next(iter(_geocode_cache)))
    _geocode_cache[key] = (now, results)
    response.headers["X-Cache"] = "MISS"
    response.headers["Cache-Control"] = "public, max-age=86400"
    return results


@router.post("/analyses", tags=["analyses"], dependencies=[analysis_limit])
async def create_analysis(req: AnalysisRequest, service: AnalysisService = Depends(get_analysis_service)):
    """Run (or fetch the cached result of) a heatwave analysis. Results are stored in and served from the database."""
    try:
        doc, cached = await service.get_or_create(req)
    except AnalysisError as exc:
        raise HTTPException(422, str(exc)) from exc
    except UpstreamError as exc:
        raise HTTPException(502, f"Could not retrieve weather data: {exc}") from exc
    return JSONResponse(_public(doc), headers={"X-Cache": "HIT" if cached else "MISS"})


async def _load(aid: str, service: AnalysisService) -> dict:
    doc = await service.get(aid)
    if doc is None:
        raise HTTPException(404, "Analysis not found (it may have expired)")
    return doc


@router.get("/analyses/{aid}", tags=["analyses"], dependencies=[default_limit])
async def get_analysis(aid: AnalysisId, service: AnalysisService = Depends(get_analysis_service)):
    return JSONResponse(_public(await _load(aid, service)), headers={"Cache-Control": "public, max-age=3600"})


@router.get("/analyses/{aid}/export.csv", tags=["exports"], dependencies=[default_limit])
async def export_csv(aid: AnalysisId, service: AnalysisService = Depends(get_analysis_service)):
    doc = await _load(aid, service)
    return Response(
        export.analysis_to_csv(doc),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="heatwave-{aid}.csv"'},
    )


@router.get("/analyses/{aid}/plot.png", tags=["exports"], dependencies=[default_limit])
async def export_png(aid: AnalysisId, service: AnalysisService = Depends(get_analysis_service)):
    doc = await _load(aid, service)
    return Response(export.trend_plot_png(doc), media_type="image/png", headers={"Cache-Control": "public, max-age=3600"})


@router.get("/analyses/{aid}/report.pdf", tags=["exports"], dependencies=[default_limit])
async def export_pdf(aid: AnalysisId, service: AnalysisService = Depends(get_analysis_service)):
    doc = await _load(aid, service)
    return Response(
        export.analysis_to_pdf(doc),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="heatwave-report-{aid}.pdf"'},
    )

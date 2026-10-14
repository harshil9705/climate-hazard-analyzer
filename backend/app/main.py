import logging
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import router
from app.config import Settings, get_settings
from app.core.middleware import SecurityMiddleware
from app.db.repository import MemoryRepository, MongoRepository, Repository
from app.services.analysis import AnalysisService
from app.services.open_meteo import OpenMeteoClient
from app.services.weather_data import WeatherDataService

logger = logging.getLogger("app")


async def build_repository(settings: Settings) -> tuple[Repository, str]:
    if settings.mongodb_uri:
        repo = MongoRepository(settings.mongodb_uri, settings.mongodb_db, settings.analysis_ttl_days)
        await repo.init()
        return repo, "mongodb"
    logger.warning("MONGODB_URI not set - using in-memory storage (data is lost on restart)")
    return MemoryRepository(), "memory"


def create_app(
    settings: Settings | None = None, repo: Repository | None = None, http: httpx.AsyncClient | None = None
) -> FastAPI:
    settings = settings or get_settings()
    logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        client = http or httpx.AsyncClient(headers={"User-Agent": "climate-hazard-analyzer/1.0"})
        if repo is not None:
            app.state.repo, app.state.repo_kind = repo, "injected"
        else:
            app.state.repo, app.state.repo_kind = await build_repository(settings)
        app.state.open_meteo = OpenMeteoClient(client, settings)
        weather = WeatherDataService(app.state.open_meteo, app.state.repo, settings.open_meteo_model)
        app.state.analysis_service = AnalysisService(weather, app.state.repo, settings)
        yield
        await app.state.repo.close()
        if http is None:
            await client.aclose()

    app = FastAPI(
        title=settings.app_name,
        version="1.0.0",
        description="Detects heatwaves in historical ERA5 temperature data and quantifies their trends.",
        lifespan=lifespan,
    )
    app.state.settings = settings

    app.add_middleware(GZipMiddleware, minimum_size=1024)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
        expose_headers=["X-Cache", "X-Request-ID", "Retry-After"],
        max_age=600,
    )
    app.add_middleware(SecurityMiddleware, max_body_bytes=settings.max_request_body_bytes)

    @app.exception_handler(RequestValidationError)
    async def validation_handler(_: Request, exc: RequestValidationError):
        # Return concise messages without echoing the full raw input back.
        errors = [
            {
                "field": ".".join(str(p) for p in e["loc"] if p not in ("body", "point", "bbox")),
                "message": e["msg"].removeprefix("Value error, "),
            }
            for e in exc.errors()
        ]
        return JSONResponse({"detail": "Invalid request", "errors": errors}, status_code=422)

    @app.exception_handler(Exception)
    async def unhandled(_: Request, exc: Exception):
        logger.exception("Unhandled error", exc_info=exc)
        return JSONResponse({"detail": "Internal server error"}, status_code=500)

    app.include_router(router)

    @app.get("/", include_in_schema=False)
    async def root():
        return {"name": settings.app_name, "docs": "/docs", "health": "/api/v1/health"}

    return app


app = create_app()

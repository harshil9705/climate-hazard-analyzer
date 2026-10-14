"""MongoDB and in-memory repositories for daily weather cache and analysis results."""

import logging
from abc import ABC, abstractmethod
from datetime import UTC, datetime, timedelta
from typing import Any

import certifi
from pymongo import AsyncMongoClient, ReplaceOne

logger = logging.getLogger(__name__)


class Repository(ABC):
    @abstractmethod
    async def get_daily_years(self, series_key: str, years: list[int]) -> dict[int, dict[str, Any]]: ...

    @abstractmethod
    async def put_daily_years(self, docs: list[dict[str, Any]]) -> None: ...

    @abstractmethod
    async def get_analysis(self, analysis_id: str) -> dict[str, Any] | None: ...

    @abstractmethod
    async def put_analysis(self, doc: dict[str, Any]) -> None: ...

    async def ping(self) -> bool:
        return True

    async def close(self) -> None:
        return None


def daily_doc_id(series_key: str, year: int) -> str:
    return f"{series_key}:{year}"


class MemoryRepository(Repository):
    """Process-local store used for tests and when no MongoDB URI is configured."""

    def __init__(self) -> None:
        self._daily: dict[str, dict[str, Any]] = {}
        self._analyses: dict[str, dict[str, Any]] = {}

    async def get_daily_years(self, series_key, years):
        out = {}
        for y in years:
            doc = self._daily.get(daily_doc_id(series_key, y))
            if doc is not None:
                out[y] = doc
        return out

    async def put_daily_years(self, docs):
        for doc in docs:
            self._daily[doc["_id"]] = doc

    async def get_analysis(self, analysis_id):
        return self._analyses.get(analysis_id)

    async def put_analysis(self, doc):
        self._analyses[doc["_id"]] = doc


class MongoRepository(Repository):
    def __init__(self, uri: str, db_name: str, analysis_ttl_days: int) -> None:
        self._client: AsyncMongoClient = AsyncMongoClient(
            uri,
            serverSelectionTimeoutMS=30000,
            connectTimeoutMS=30000,
            tz_aware=True,
            tls=True,
            tlsCAFile=certifi.where(),
        )
        db = self._client[db_name]
        self._daily = db["daily_cache"]
        self._analyses = db["analyses"]
        self._ttl_seconds = int(timedelta(days=analysis_ttl_days).total_seconds())

    async def init(self) -> None:
        try:
            await self._daily.create_index([("series_key", 1), ("year", 1)])
            await self._analyses.create_index("created_at", expireAfterSeconds=self._ttl_seconds)
            logger.info("MongoDB indexes created successfully")
        except Exception:  # noqa: BLE001
            logger.warning(
                "MongoDB index creation failed — will retry on first connection",
                exc_info=True,
            )

    async def get_daily_years(self, series_key, years):
        ids = [daily_doc_id(series_key, y) for y in years]
        out = {}
        async for doc in self._daily.find({"_id": {"$in": ids}}):
            out[int(doc["year"])] = doc
        return out

    async def put_daily_years(self, docs):
        if not docs:
            return
        await self._daily.bulk_write([ReplaceOne({"_id": d["_id"]}, d, upsert=True) for d in docs], ordered=False)

    async def get_analysis(self, analysis_id):
        return await self._analyses.find_one({"_id": analysis_id})

    async def put_analysis(self, doc):
        doc = {**doc, "created_at": datetime.now(UTC)}
        await self._analyses.replace_one({"_id": doc["_id"]}, doc, upsert=True)

    async def ping(self) -> bool:
        try:
            await self._client.admin.command("ping")
            return True
        except Exception:  # noqa: BLE001 - health check must never raise
            logger.warning("MongoDB ping failed", exc_info=True)
            return False

    async def close(self) -> None:
        await self._client.close()

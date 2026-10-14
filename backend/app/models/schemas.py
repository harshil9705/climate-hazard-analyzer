"""Request / response schemas. All user input is validated here before it reaches any service."""

import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.config import MIN_YEAR, get_settings, last_complete_year

MIN_ANALYSIS_YEARS = 10
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


def _clean_label(value: str | None) -> str | None:
    if value is None:
        return None
    value = _CONTROL_CHARS.sub("", value).strip()
    return value or None


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PointRegion(_Strict):
    kind: Literal["point"] = "point"
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    name: str | None = Field(default=None, max_length=120)

    _clean_name = field_validator("name")(_clean_label)


class BBoxRegion(_Strict):
    kind: Literal["bbox"] = "bbox"
    south: float = Field(ge=-90, le=90)
    west: float = Field(ge=-180, le=180)
    north: float = Field(ge=-90, le=90)
    east: float = Field(ge=-180, le=180)
    name: str | None = Field(default=None, max_length=120)

    _clean_name = field_validator("name")(_clean_label)

    @model_validator(mode="after")
    def _check_box(self) -> "BBoxRegion":
        if self.south >= self.north:
            raise ValueError("south must be less than north")
        if self.west >= self.east:
            raise ValueError("west must be less than east (boxes crossing the antimeridian are not supported)")
        max_span = get_settings().max_bbox_span_deg
        if self.north - self.south > max_span or self.east - self.west > max_span:
            raise ValueError(f"bounding box may span at most {max_span} degrees on each side")
        return self


Region = Annotated[PointRegion | BBoxRegion, Field(discriminator="kind")]


class HeatwaveParams(_Strict):
    percentile: float = Field(default=95.0, ge=80.0, le=99.9)
    min_duration_days: int = Field(default=3, ge=2, le=10)
    # "fixed": one regional threshold (absolute heat hazard, as in the brief).
    # "calendar_day": day-of-year threshold with a 15-day window (relative extremes, Perkins & Alexander 2013).
    threshold_method: Literal["fixed", "calendar_day"] = "fixed"
    # Threshold is computed from a fixed reference period, not from the analysis window,
    # so the warming trend does not leak into the definition of "extreme".
    baseline_start: int = 1961
    baseline_end: int = 1990


class DroughtParams(_Strict):
    dry_threshold_mm: float = Field(default=1.0, ge=0.0, le=50.0)
    min_duration_days: int = Field(default=7, ge=3, le=90)


class RainfallParams(_Strict):
    percentile: float = Field(default=95.0, ge=80.0, le=99.9)
    wet_threshold_mm: float = Field(default=1.0, ge=0.1, le=10.0)
    min_duration_days: int = Field(default=1, ge=1, le=10)
    baseline_start: int = 1961
    baseline_end: int = 1990


def _check_year_range(start_year: int, end_year: int, baseline_start: int | None = None, baseline_end: int | None = None) -> None:
    latest = last_complete_year()
    pairs: list[tuple[str, int]] = [("start_year", start_year), ("end_year", end_year)]
    if baseline_start is not None:
        pairs.append(("baseline_start", baseline_start))
    if baseline_end is not None:
        pairs.append(("baseline_end", baseline_end))
    for label, year in pairs:
        if not MIN_YEAR <= year <= latest:
            raise ValueError(f"{label} must be between {MIN_YEAR} and {latest}")
    if end_year - start_year + 1 < MIN_ANALYSIS_YEARS:
        raise ValueError(f"time range must cover at least {MIN_ANALYSIS_YEARS} years for a meaningful trend")
    if baseline_start is not None and baseline_end is not None:
        if baseline_end - baseline_start + 1 < MIN_ANALYSIS_YEARS:
            raise ValueError(f"baseline period must cover at least {MIN_ANALYSIS_YEARS} years")


class HeatwaveRequest(_Strict):
    region: Region
    hazard: Literal["heatwave"] = "heatwave"
    start_year: int
    end_year: int
    params: HeatwaveParams = Field(default_factory=HeatwaveParams)

    @model_validator(mode="after")
    def _check_years(self) -> "HeatwaveRequest":
        _check_year_range(self.start_year, self.end_year, self.params.baseline_start, self.params.baseline_end)
        return self


class DroughtRequest(_Strict):
    region: Region
    hazard: Literal["drought"] = "drought"
    start_year: int
    end_year: int
    params: DroughtParams = Field(default_factory=DroughtParams)

    @model_validator(mode="after")
    def _check_years(self) -> "DroughtRequest":
        _check_year_range(self.start_year, self.end_year)
        return self


class RainfallRequest(_Strict):
    region: Region
    hazard: Literal["rainfall"] = "rainfall"
    start_year: int
    end_year: int
    params: RainfallParams = Field(default_factory=RainfallParams)

    @model_validator(mode="after")
    def _check_years(self) -> "RainfallRequest":
        _check_year_range(self.start_year, self.end_year, self.params.baseline_start, self.params.baseline_end)
        return self


AnalysisRequest = Annotated[
    HeatwaveRequest | DroughtRequest | RainfallRequest,
    Field(discriminator="hazard"),
]


class GeocodeResult(BaseModel):
    name: str
    lat: float
    lon: float
    country: str | None = None
    admin1: str | None = None
    population: int | None = None

"""Heavy rainfall detection: events above a percentile of wet-day precipitation from a baseline period."""

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class RainfallEvent:
    start: pd.Timestamp
    end: pd.Timestamp
    duration: int
    peak_precip: float
    mean_precip: float
    cumulative_precip: float

    def to_dict(self) -> dict:
        return {
            "start": self.start.date().isoformat(),
            "end": self.end.date().isoformat(),
            "year": int(self.start.year),
            "duration_days": self.duration,
            "peak_precip_mm": round(self.peak_precip, 2),
            "mean_precip_mm": round(self.mean_precip, 2),
            "cumulative_precip_mm": round(self.cumulative_precip, 2),
        }


def compute_rainfall_threshold(
    precip: pd.Series,
    percentile: float,
    wet_threshold_mm: float,
    baseline_start: int,
    baseline_end: int,
) -> float:
    """Xth percentile of wet-day daily precip in the baseline period."""
    base = precip[(precip.index.year >= baseline_start) & (precip.index.year <= baseline_end)]
    wet = base[base >= wet_threshold_mm].dropna()
    if len(wet) < 30:
        raise ValueError("not enough wet days in the baseline to compute a percentile threshold")
    return float(np.percentile(wet.to_numpy(), percentile))


def detect_heavy_rain(precip: pd.Series, threshold_mm: float, min_duration: int) -> list[RainfallEvent]:
    """Runs of >= min_duration consecutive days with precip >= threshold_mm. Missing days break an event."""
    values = precip.to_numpy(dtype=float)
    heavy = np.nan_to_num(values, nan=-np.inf) >= threshold_mm

    padded = np.concatenate(([False], heavy, [False])).astype(np.int8)
    edges = np.diff(padded)
    starts = np.flatnonzero(edges == 1)
    ends = np.flatnonzero(edges == -1)

    events = []
    for s, e in zip(starts, ends, strict=True):
        length = e - s
        if length < min_duration:
            continue
        seg = values[s:e]
        events.append(
            RainfallEvent(
                start=precip.index[s],
                end=precip.index[e - 1],
                duration=int(length),
                peak_precip=float(np.nanmax(seg)),
                mean_precip=float(np.nanmean(seg)),
                cumulative_precip=float(np.nansum(seg)),
            )
        )
    return events


def annual_rainfall_metrics(
    precip: pd.Series,
    events: list[RainfallEvent],
    threshold_mm: float,
    start_year: int,
    end_year: int,
    excluded_years: set[int],
) -> list[dict]:
    rows = []
    for year in range(start_year, end_year + 1):
        year_p = precip[precip.index.year == year]
        if year in excluded_years or year_p.dropna().empty:
            rows.append({"year": year, "excluded": True, **{k: None for k in _RAINFALL_METRIC_KEYS}})
            continue
        evs = [ev for ev in events if ev.start.year == year]
        heavy_days = sum(ev.duration for ev in evs)
        valid = year_p.dropna()
        rx1 = round(float(valid.max()), 2) if len(valid) > 0 else None
        rolling5 = year_p.rolling(5, min_periods=3).sum()
        rx5_vals = rolling5.dropna()
        rx5 = round(float(rx5_vals.max()), 2) if len(rx5_vals) > 0 else None
        rows.append(
            {
                "year": year,
                "excluded": False,
                "event_count": len(evs),
                "heavy_days": heavy_days,
                "max_event_days": max((ev.duration for ev in evs), default=0),
                "total_heavy_precip_mm": round(sum(ev.cumulative_precip for ev in evs), 2),
                "rx1day_mm": rx1,
                "rx5day_mm": rx5,
                "total_annual_precip_mm": round(float(year_p.sum()), 2),
                "mean_annual_precip_mm": round(float(year_p.mean()), 2),
            }
        )
    return rows


_RAINFALL_METRIC_KEYS = (
    "event_count",
    "heavy_days",
    "max_event_days",
    "total_heavy_precip_mm",
    "rx1day_mm",
    "rx5day_mm",
    "total_annual_precip_mm",
    "mean_annual_precip_mm",
)

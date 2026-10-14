"""Drought detection: consecutive dry spells below a fixed precipitation threshold."""

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class DroughtEvent:
    start: pd.Timestamp
    end: pd.Timestamp
    duration: int
    min_precip: float
    mean_precip: float
    cumulative_deficit: float

    def to_dict(self) -> dict:
        return {
            "start": self.start.date().isoformat(),
            "end": self.end.date().isoformat(),
            "year": int(self.start.year),
            "duration_days": self.duration,
            "min_precip_mm": round(self.min_precip, 2),
            "mean_precip_mm": round(self.mean_precip, 2),
            "cumulative_deficit_mm": round(self.cumulative_deficit, 2),
        }


def detect_dry_spells(precip: pd.Series, threshold_mm: float, min_duration: int) -> list[DroughtEvent]:
    """Runs of >= min_duration consecutive days with precip below threshold_mm. Missing days break a spell."""
    values = precip.to_numpy(dtype=float)
    dry = np.nan_to_num(values, nan=np.inf) < threshold_mm

    padded = np.concatenate(([False], dry, [False])).astype(np.int8)
    edges = np.diff(padded)
    starts = np.flatnonzero(edges == 1)
    ends = np.flatnonzero(edges == -1)

    events = []
    for s, e in zip(starts, ends, strict=True):
        length = e - s
        if length < min_duration:
            continue
        seg = values[s:e]
        deficit = float(np.nansum(np.maximum(0.0, threshold_mm - np.nan_to_num(seg, nan=0.0))))
        events.append(
            DroughtEvent(
                start=precip.index[s],
                end=precip.index[e - 1],
                duration=int(length),
                min_precip=float(np.nanmin(seg)),
                mean_precip=float(np.nanmean(seg)),
                cumulative_deficit=deficit,
            )
        )
    return events


def annual_drought_metrics(
    precip: pd.Series,
    events: list[DroughtEvent],
    threshold_mm: float,
    start_year: int,
    end_year: int,
    excluded_years: set[int],
) -> list[dict]:
    rows = []
    for year in range(start_year, end_year + 1):
        year_p = precip[precip.index.year == year]
        if year in excluded_years or year_p.dropna().empty:
            rows.append({"year": year, "excluded": True, **{k: None for k in _DROUGHT_METRIC_KEYS}})
            continue
        evs = [ev for ev in events if ev.start.year == year]
        spell_days = sum(ev.duration for ev in evs)
        dry_total = int((year_p < threshold_mm).sum())
        rows.append(
            {
                "year": year,
                "excluded": False,
                "event_count": len(evs),
                "drought_days": spell_days,
                "max_dry_spell": max((ev.duration for ev in evs), default=0),
                "cumulative_deficit_mm": round(sum(ev.cumulative_deficit for ev in evs), 2),
                "mean_annual_precip_mm": round(float(year_p.mean()), 2),
                "total_annual_precip_mm": round(float(year_p.sum()), 2),
                "dry_days_total": dry_total,
            }
        )
    return rows


_DROUGHT_METRIC_KEYS = (
    "event_count",
    "drought_days",
    "max_dry_spell",
    "cumulative_deficit_mm",
    "mean_annual_precip_mm",
    "total_annual_precip_mm",
    "dry_days_total",
)

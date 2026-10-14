"""Heatwave definition and detection.

Definition (configurable): a heatwave is a run of at least ``min_duration`` consecutive days on
which daily maximum temperature exceeds the ``percentile``-th percentile threshold computed over a
fixed baseline period.

Annual indices follow the heatwave framework of Perkins & Alexander (2013):
  HWN  number of events            HWF  number of heatwave days
  HWD  longest event (days)        HWM  mean Tmax on heatwave days
  HWA  hottest heatwave day        plus cumulative excess heat (deg C * days above threshold)
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

CALENDAR_WINDOW_HALF_WIDTH = 7  # 15-day centred window for calendar-day percentiles


@dataclass
class Threshold:
    method: str
    percentile: float
    baseline_start: int
    baseline_end: int
    fixed_value: float | None
    by_day_of_year: np.ndarray  # 365 values (Feb 29 shares Feb 28's threshold)

    def for_dates(self, index: pd.DatetimeIndex) -> np.ndarray:
        return self.by_day_of_year[noleap_doy(index) - 1]


@dataclass
class HeatwaveEvent:
    start: pd.Timestamp
    end: pd.Timestamp
    duration: int
    peak_tmax: float
    mean_tmax: float
    mean_excess: float
    cumulative_excess: float

    def to_dict(self) -> dict:
        return {
            "start": self.start.date().isoformat(),
            "end": self.end.date().isoformat(),
            "year": int(self.start.year),
            "duration_days": self.duration,
            "peak_tmax_c": round(self.peak_tmax, 2),
            "mean_tmax_c": round(self.mean_tmax, 2),
            "mean_excess_c": round(self.mean_excess, 2),
            "cumulative_excess_cdays": round(self.cumulative_excess, 2),
        }


def noleap_doy(index: pd.DatetimeIndex) -> np.ndarray:
    """Day of year on a 365-day calendar: Feb 29 maps to Feb 28 (59), later days shift back by one."""
    doy = index.dayofyear.to_numpy().copy()
    leap = index.is_leap_year
    after_feb28 = leap & (doy >= 60)
    doy[after_feb28] -= 1
    return doy


def compute_threshold(tmax: pd.Series, percentile: float, method: str, baseline_start: int, baseline_end: int) -> Threshold:
    base = tmax[(tmax.index.year >= baseline_start) & (tmax.index.year <= baseline_end)].dropna()
    if len(base) < 365 * 5:
        raise ValueError("not enough valid baseline data to compute a percentile threshold")

    if method == "fixed":
        value = float(np.percentile(base.to_numpy(), percentile))
        return Threshold(method, percentile, baseline_start, baseline_end, value, np.full(365, value))

    doy = noleap_doy(base.index)
    values = base.to_numpy()
    by_doy = np.empty(365)
    for d in range(1, 366):
        # circular distance so the window wraps around the new year
        dist = np.abs(doy - d)
        dist = np.minimum(dist, 365 - dist)
        by_doy[d - 1] = np.percentile(values[dist <= CALENDAR_WINDOW_HALF_WIDTH], percentile)
    return Threshold(method, percentile, baseline_start, baseline_end, None, by_doy)


def detect_heatwaves(tmax: pd.Series, threshold: Threshold, min_duration: int) -> list[HeatwaveEvent]:
    """Find runs of >= min_duration days above threshold. Missing days break a run (conservative)."""
    thr = threshold.for_dates(tmax.index)
    values = tmax.to_numpy(dtype=float)

    hot = np.nan_to_num(values, nan=-np.inf) > thr

    padded = np.concatenate(([False], hot, [False])).astype(np.int8)
    edges = np.diff(padded)
    starts = np.flatnonzero(edges == 1)
    ends = np.flatnonzero(edges == -1)  # exclusive

    events = []
    for s, e in zip(starts, ends, strict=True):
        length = e - s
        if length < min_duration:
            continue
        seg = values[s:e]
        excess = seg - thr[s:e]
        events.append(
            HeatwaveEvent(
                start=tmax.index[s],
                end=tmax.index[e - 1],
                duration=int(length),
                peak_tmax=float(seg.max()),
                mean_tmax=float(seg.mean()),
                mean_excess=float(excess.mean()),
                cumulative_excess=float(excess.sum()),
            )
        )
    return events


def annual_metrics(
    tmax: pd.Series,
    events: list[HeatwaveEvent],
    threshold: Threshold,
    start_year: int,
    end_year: int,
    excluded_years: set[int],
) -> list[dict]:
    """One row per year. Events are attributed to the year in which they start.

    Excluded (data-poor) years get ``None`` metrics so they show as gaps rather than fake zeros.
    """
    thr = pd.Series(threshold.for_dates(tmax.index), index=tmax.index)
    exceed = (tmax > thr) & tmax.notna()
    rows = []
    for year in range(start_year, end_year + 1):
        year_tmax = tmax[tmax.index.year == year]
        if year in excluded_years or year_tmax.dropna().empty:
            rows.append({"year": year, "excluded": True, **{k: None for k in _METRIC_KEYS}})
            continue
        evs = [ev for ev in events if ev.start.year == year]
        hw_days = sum(ev.duration for ev in evs)
        rows.append(
            {
                "year": year,
                "excluded": False,
                "event_count": len(evs),
                "heatwave_days": hw_days,
                "longest_event_days": max((ev.duration for ev in evs), default=0),
                "mean_heatwave_tmax_c": (round(sum(ev.mean_tmax * ev.duration for ev in evs) / hw_days, 2) if hw_days else None),
                "peak_tmax_c": round(max(ev.peak_tmax for ev in evs), 2) if evs else None,
                "cumulative_excess_cdays": round(sum(ev.cumulative_excess for ev in evs), 2),
                "exceedance_days": int(exceed[exceed.index.year == year].sum()),
                "mean_annual_tmax_c": round(float(year_tmax.mean()), 2),
                "annual_max_tmax_c": round(float(year_tmax.max()), 2),
            }
        )
    return rows


_METRIC_KEYS = (
    "event_count",
    "heatwave_days",
    "longest_event_days",
    "mean_heatwave_tmax_c",
    "peak_tmax_c",
    "cumulative_excess_cdays",
    "exceedance_days",
    "mean_annual_tmax_c",
    "annual_max_tmax_c",
)

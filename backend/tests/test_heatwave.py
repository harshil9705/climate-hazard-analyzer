import numpy as np
import pandas as pd
import pytest

from app.services.heatwave import Threshold, annual_metrics, compute_threshold, detect_heatwaves, noleap_doy


def _fixed(value: float) -> Threshold:
    return Threshold("fixed", 95, 2000, 2000, value, np.full(365, value))


def _series(values, start="2000-07-01"):
    return pd.Series(values, index=pd.date_range(start, periods=len(values), freq="D"), dtype=float)


def test_detects_only_runs_of_minimum_length():
    s = _series([30, 36, 36, 30, 36, 36, 36, 30, 36, 36, 36, 36, 36, 30])
    events = detect_heatwaves(s, _fixed(35), min_duration=3)
    assert [e.duration for e in events] == [3, 5]
    assert events[0].start == pd.Timestamp("2000-07-05")
    assert events[1].end == pd.Timestamp("2000-07-13")


def test_value_equal_to_threshold_is_not_an_exceedance():
    s = _series([35, 35, 35, 35])
    assert detect_heatwaves(s, _fixed(35), 3) == []


def test_missing_day_breaks_a_run():
    s = _series([36, 36, np.nan, 36, 36, 36])
    events = detect_heatwaves(s, _fixed(35), 3)
    assert [e.duration for e in events] == [3]


def test_event_at_series_edges_is_detected():
    s = _series([36, 36, 36, 30, 30, 36, 36, 36])
    assert [e.duration for e in detect_heatwaves(s, _fixed(35), 3)] == [3, 3]


def test_event_intensity_metrics():
    s = _series([30, 37, 39, 38, 30])
    (ev,) = detect_heatwaves(s, _fixed(35), 3)
    assert ev.peak_tmax == 39
    assert ev.mean_tmax == pytest.approx(38)
    assert ev.cumulative_excess == pytest.approx(2 + 4 + 3)


def test_fixed_threshold_uses_only_baseline_years(tmax_factory):
    s = tmax_factory(1960, 2020, warming_per_year=0.1)
    thr_early = compute_threshold(s, 95, "fixed", 1961, 1990)
    thr_late = compute_threshold(s, 95, "fixed", 1991, 2020)
    assert thr_late.fixed_value > thr_early.fixed_value + 2  # ~3 deg C of synthetic warming between baselines
    base = s[(s.index.year >= 1961) & (s.index.year <= 1990)]
    assert thr_early.fixed_value == pytest.approx(np.percentile(base, 95))


def test_calendar_day_threshold_follows_seasonal_cycle(tmax_factory):
    s = tmax_factory(1961, 1990)
    thr = compute_threshold(s, 90, "calendar_day", 1961, 1990)
    assert thr.fixed_value is None
    assert len(thr.by_day_of_year) == 365
    assert thr.by_day_of_year[190] > thr.by_day_of_year[10] + 10  # July much hotter than January


def test_threshold_requires_enough_baseline_data(tmax_factory):
    with pytest.raises(ValueError):
        compute_threshold(tmax_factory(2000, 2002), 95, "fixed", 2000, 2002)


def test_noleap_doy_maps_feb29_and_shifts_later_days():
    idx = pd.DatetimeIndex(["2020-02-28", "2020-02-29", "2020-03-01", "2021-03-01", "2020-12-31"])
    assert list(noleap_doy(idx)) == [59, 59, 60, 60, 365]


def test_annual_metrics_attribute_events_and_mark_excluded_years():
    s = _series([30] * 10 + [40, 40, 40, 40] + [30] * 10, start="2000-12-20")
    events = detect_heatwaves(s, _fixed(35), 3)
    rows = annual_metrics(s, events, _fixed(35), 2000, 2001, excluded_years={2001})
    r2000, r2001 = rows
    assert r2000["event_count"] == 1 and r2000["heatwave_days"] == 4  # event starts Dec 30 2000
    assert r2001["excluded"] and r2001["heatwave_days"] is None

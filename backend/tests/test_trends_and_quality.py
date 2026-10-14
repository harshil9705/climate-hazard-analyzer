import numpy as np
import pandas as pd
import pytest

from app.services.data_quality import clean_daily_series
from app.services.insights import build_insights
from app.services.trends import analyze_trend, mann_kendall, ols, rolling_mean, sens_slope, t_critical, t_two_sided_p

YEARS = list(range(1990, 2021))


def test_t_distribution_helpers_match_tables():
    assert t_critical(10) == pytest.approx(2.2281, abs=1e-3)
    assert t_critical(30) == pytest.approx(2.0423, abs=1e-3)
    assert t_two_sided_p(2.0423, 30) == pytest.approx(0.05, abs=1e-3)


def test_mann_kendall_detects_monotonic_increase():
    y = np.arange(20, dtype=float)
    res = mann_kendall(y)
    assert res["s"] == 190 and res["tau"] == pytest.approx(1.0)
    assert res["p_value"] < 0.001


def test_mann_kendall_no_trend_in_noise():
    rng = np.random.default_rng(42)
    assert mann_kendall(rng.normal(size=40))["p_value"] > 0.05


def test_mann_kendall_handles_ties():
    y = np.array([0, 0, 0, 0, 1, 0, 0, 2, 0, 3, 0, 4], dtype=float)
    res = mann_kendall(y)
    assert res["s"] > 0 and 0 <= res["p_value"] <= 1


def test_sens_slope_is_robust_to_outlier():
    x = np.arange(20, dtype=float)
    y = 2 * x + 1
    y[5] = 500
    slope, _ = sens_slope(x, y)
    assert slope == pytest.approx(2.0)


def test_ols_recovers_known_slope():
    x = np.arange(30, dtype=float)
    y = 0.5 * x + 3 + np.random.default_rng(1).normal(0, 0.1, 30)
    res = ols(x, y)
    assert res["slope"] == pytest.approx(0.5, abs=0.01)
    assert res["slope_ci95"][0] < 0.5 < res["slope_ci95"][1]


def test_analyze_trend_skips_none_and_handles_constant_series():
    assert analyze_trend(YEARS, [0] * len(YEARS))["status"] == "constant"
    assert analyze_trend(YEARS[:5], [1, 2, 3, 4, 5])["status"] == "insufficient_data"
    vals = [float(i) if i % 7 else None for i in range(len(YEARS))]
    res = analyze_trend(YEARS, vals)
    assert res["status"] == "ok" and res["direction"] == "increasing"
    assert len(res["trend_line"]) == len(YEARS)


def test_rolling_mean_tolerates_gaps():
    out = rolling_mean([1, 2, None, 4, 5, 6, None, 8, 9, 10], window=4)
    assert len(out) == 10 and out[4] is not None


def test_cleaning_interpolates_short_gaps_only():
    idx = pd.date_range("2000-01-01", periods=20, freq="D")
    s = pd.Series(np.linspace(10, 29, 20), index=idx)
    s.iloc[3] = np.nan  # 1-day gap -> filled
    s.iloc[8:12] = np.nan  # 4-day gap -> kept missing
    cleaned, rep = clean_daily_series(s)
    assert rep.interpolated == 1 and cleaned.iloc[3] == pytest.approx(13)
    assert rep.missing_after_cleaning == 4


def test_cleaning_removes_implausible_values_and_spikes_and_fills_dropped_dates():
    idx = pd.date_range("2000-01-01", periods=30, freq="D")
    s = pd.Series(20.0, index=idx)
    s.iloc[5] = 999  # sensor error
    s.iloc[15] = 48  # isolated spike, +28 from both neighbours
    s = s.drop(idx[20])  # a missing timestamp
    cleaned, rep = clean_daily_series(s)
    assert rep.implausible_removed == 1 and rep.spikes_removed == 1
    assert rep.missing_raw == 1
    assert len(cleaned) == 30 and cleaned.isna().sum() == 0


def test_cleaning_does_not_remove_a_genuine_multi_day_heatwave():
    idx = pd.date_range("2000-01-01", periods=15, freq="D")
    s = pd.Series([20] * 5 + [42, 44, 45, 43] + [20] * 6, index=idx, dtype=float)
    cleaned, rep = clean_daily_series(s)
    assert rep.spikes_removed == 0 and cleaned.max() == 45


def test_cleaning_excludes_years_with_too_much_missing_data():
    idx = pd.date_range("2000-01-01", "2001-12-31", freq="D")
    s = pd.Series(20.0, index=idx)
    s.loc["2001-03-01":"2001-04-30"] = np.nan
    _, rep = clean_daily_series(s)
    assert rep.excluded_years == [2001]


def _annual(days):
    return [
        {"year": y, "excluded": False, "heatwave_days": d, "event_count": 1 if d else 0} for y, d in zip(YEARS, days, strict=True)
    ]


def _trends(days):
    t = analyze_trend(YEARS, days)
    return {k: t for k in ("heatwave_days", "event_count", "longest_event_days", "cumulative_excess_cdays", "mean_annual_tmax_c")}


def test_insight_claims_increase_only_when_significant():
    days = [2 + i for i in range(len(YEARS))]
    ins = build_insights("Testville", 1990, 2020, _annual(days), _trends(days), "35 °C", {})
    assert "increased" in ins["headline"] and "statistically significant" in ins["headline"]
    assert ins["period_comparison"]["percent_change"] > 0


def test_insight_reports_no_trend_for_noise():
    rng = np.random.default_rng(3)
    days = [int(v) for v in rng.poisson(8, len(YEARS))]
    ins = build_insights("Testville", 1990, 2020, _annual(days), _trends(days), "35 °C", {})
    assert ins["headline"].startswith("No statistically significant trend")


def test_insight_suppresses_percent_change_on_tiny_baseline():
    days = [0] * 15 + [0, 1, 0, 2, 1, 3, 2, 4, 3, 5, 4, 6, 5, 7, 6, 8]
    ins = build_insights("Testville", 1990, 2020, _annual(days), _trends(days), "35 °C", {})
    assert ins["period_comparison"]["percent_change"] is None
    assert "%" not in ins["headline"]

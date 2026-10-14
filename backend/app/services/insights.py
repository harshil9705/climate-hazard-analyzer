"""Turns annual indices + trend statistics into plain-language, statistically honest insights.

Rules:
  * Only say "increased"/"decreased" when the Mann-Kendall test is significant (p < 0.05);
    p < 0.10 is reported as weak evidence; otherwise we say there is no significant trend.
  * Percent changes compare decade averages (not single endpoint years, which are noisy) and are
    suppressed when the early average is too small for a percentage to be meaningful.
"""

import numpy as np

MIN_BASE_FOR_PERCENT = 1.0  # days/events per year
COMPARISON_WINDOW = 10


def _window_means(annual: list[dict], key: str) -> dict | None:
    rows = [r for r in annual if not r["excluded"] and r.get(key) is not None]
    if len(rows) < 4:
        return None
    w = COMPARISON_WINDOW if len(rows) >= 2 * COMPARISON_WINDOW else len(rows) // 2
    early, late = rows[:w], rows[-w:]
    e_mean = float(np.mean([r[key] for r in early]))
    l_mean = float(np.mean([r[key] for r in late]))
    pct = (l_mean - e_mean) / e_mean * 100 if e_mean >= MIN_BASE_FOR_PERCENT else None
    return {
        "metric": key,
        "early": {"start": early[0]["year"], "end": early[-1]["year"], "mean": round(e_mean, 2)},
        "late": {"start": late[0]["year"], "end": late[-1]["year"], "mean": round(l_mean, 2)},
        "absolute_change": round(l_mean - e_mean, 2),
        "percent_change": round(pct, 1) if pct is not None else None,
    }


def _p(trend: dict) -> str:
    p = trend["mann_kendall"]["p_value"]
    return "p < 0.001" if p < 0.001 else f"p = {p:.3f}"


def _fmt(slope: float) -> str:
    if slope == 0:
        return "0"
    return f"{slope:+.3f}" if abs(slope) < 0.1 else f"{slope:+.2f}"


def _trend_sentence(label: str, unit: str, trend: dict) -> str:
    head = label[0].upper() + label[1:]
    if trend["status"] == "insufficient_data":
        return f"{head}: not enough complete years to assess a trend."
    if trend["status"] == "constant":
        return f"{head}: no variation over the period, so no trend can be assessed."
    slope = trend["sens_slope_per_decade"]
    rate = f"{_fmt(slope)} {unit} per decade"
    noun = "increase" if trend["direction"] == "increasing" else "decrease"
    if trend["significance"] == "significant":
        return f"{head}: statistically significant {noun} of {rate} ({_p(trend)})."
    if trend["significance"] == "weak":
        return f"{head}: weak evidence of an {noun} ({rate}, {_p(trend)}), not significant at the 5% level."
    return f"{head}: no statistically significant trend ({rate}, {_p(trend)})."


def build_insights(
    region_label: str, start_year: int, end_year: int, annual: list[dict], trends: dict, threshold_c: str, quality: dict
) -> dict:
    hw = trends["heatwave_days"]
    comp = _window_means(annual, "heatwave_days")
    total_events = sum(r["event_count"] or 0 for r in annual if not r["excluded"])

    if total_events == 0:
        headline = f"No heatwaves meeting the definition were detected in {region_label} between {start_year} and {end_year}."
    elif hw["status"] != "ok" or comp is None:
        headline = f"{total_events} heatwaves were detected in {region_label} between {start_year} and {end_year}, but there are too few complete years to assess a trend."
    else:
        e, late = comp["early"], comp["late"]
        pct = comp["percent_change"]
        if pct is None:
            change = f"from {e['mean']:.1f} to {late['mean']:.1f} days per year"
        elif hw["significance"] == "significant":
            change = f"by {abs(pct):.0f}%"  # the verb ("increased"/"decreased") already carries the sign
        else:
            change = f"by {pct:+.0f}%"
        periods = f"({e['start']}–{e['end']} avg {e['mean']:.1f} days/yr vs {late['start']}–{late['end']} avg {late['mean']:.1f})"
        if hw["significance"] == "significant":
            verb = "increased" if hw["direction"] == "increasing" else "decreased"
            headline = f"Heatwave days have {verb} {change} in {region_label} since {start_year} {periods}; the trend is statistically significant ({_p(hw)})."
        elif hw["significance"] == "weak":
            headline = f"Heatwave days in {region_label} changed {change} since {start_year} {periods}, but the evidence for a trend is weak ({_p(hw)})."
        else:
            headline = f"No statistically significant trend in heatwave days in {region_label} over {start_year}–{end_year} {periods}; year-to-year variability dominates ({_p(hw)})."

    findings = [
        {
            "metric": "heatwave_days",
            "text": _trend_sentence("annual heatwave days", "days", hw),
            "significance": hw.get("significance"),
        },
        {
            "metric": "event_count",
            "text": _trend_sentence("heatwave events per year", "events", trends["event_count"]),
            "significance": trends["event_count"].get("significance"),
        },
        {
            "metric": "longest_event_days",
            "text": _trend_sentence("the longest heatwave each year", "days", trends["longest_event_days"]),
            "significance": trends["longest_event_days"].get("significance"),
        },
        {
            "metric": "cumulative_excess_cdays",
            "text": _trend_sentence("cumulative excess heat", "°C·days", trends["cumulative_excess_cdays"]),
            "significance": trends["cumulative_excess_cdays"].get("significance"),
        },
        {
            "metric": "mean_annual_tmax_c",
            "text": _trend_sentence("mean annual maximum temperatures", "°C", trends["mean_annual_tmax_c"]),
            "significance": trends["mean_annual_tmax_c"].get("significance"),
        },
    ]

    caveats = [
        "Data are ERA5 reanalysis (~25-30 km grid), not station observations; local extremes (e.g. urban heat islands) can be stronger than shown.",
        f"The heatwave threshold ({threshold_c}) is computed from a fixed baseline period, so results depend on that choice.",
        "The Mann-Kendall test assumes independent years; multi-year climate modes (e.g. ENSO) can make p-values optimistic.",
    ]
    if quality.get("excluded_years"):
        caveats.append(
            f"{len(quality['excluded_years'])} year(s) were excluded for having more than 5% missing data: "
            + ", ".join(map(str, quality["excluded_years"][:10]))
        )
    return {"headline": headline, "findings": findings, "period_comparison": comp, "caveats": caveats}


def build_drought_insights(
    region_label: str, start_year: int, end_year: int, annual: list[dict], trends: dict, threshold_label: str, quality: dict
) -> dict:
    dr = trends.get("drought_days", {})
    comp = _window_means(annual, "drought_days")
    total_events = sum(r.get("event_count") or 0 for r in annual if not r["excluded"])

    if total_events == 0:
        headline = f"No dry spells meeting the definition were detected in {region_label} between {start_year} and {end_year}."
    elif dr.get("status") != "ok" or comp is None:
        headline = f"{total_events} dry spells were detected in {region_label} between {start_year} and {end_year}, but there are too few complete years to assess a trend."
    else:
        e, late = comp["early"], comp["late"]
        pct = comp["percent_change"]
        if pct is None:
            change = f"from {e['mean']:.1f} to {late['mean']:.1f} days per year"
        elif dr.get("significance") == "significant":
            change = f"by {abs(pct):.0f}%"
        else:
            change = f"by {pct:+.0f}%"
        periods = f"({e['start']}–{e['end']} avg {e['mean']:.1f} days/yr vs {late['start']}–{late['end']} avg {late['mean']:.1f})"
        if dr.get("significance") == "significant":
            verb = "increased" if dr.get("direction") == "increasing" else "decreased"
            headline = f"Drought days have {verb} {change} in {region_label} since {start_year} {periods}; the trend is statistically significant ({_p(dr)})."
        elif dr.get("significance") == "weak":
            headline = f"Drought days in {region_label} changed {change} since {start_year} {periods}, but the evidence for a trend is weak ({_p(dr)})."
        else:
            headline = f"No statistically significant trend in drought days in {region_label} over {start_year}–{end_year} {periods}; year-to-year variability dominates ({_p(dr)})."

    findings = [
        {
            "metric": "drought_days",
            "text": _trend_sentence("annual drought days", "days", dr),
            "significance": dr.get("significance"),
        },
        {
            "metric": "event_count",
            "text": _trend_sentence("dry spell events per year", "events", trends.get("event_count", {})),
            "significance": trends.get("event_count", {}).get("significance"),
        },
        {
            "metric": "max_dry_spell",
            "text": _trend_sentence("the longest dry spell each year", "days", trends.get("max_dry_spell", {})),
            "significance": trends.get("max_dry_spell", {}).get("significance"),
        },
        {
            "metric": "total_annual_precip_mm",
            "text": _trend_sentence("total annual precipitation", "mm", trends.get("total_annual_precip_mm", {})),
            "significance": trends.get("total_annual_precip_mm", {}).get("significance"),
        },
    ]

    caveats = [
        "Data are ERA5 reanalysis (~25-30 km grid), not station observations.",
        f"The dry day threshold ({threshold_label}) is user-defined; results change with different thresholds.",
        "The Mann-Kendall test assumes independent years; climate modes (ENSO, PDO) can affect p-values.",
    ]
    if quality.get("excluded_years"):
        caveats.append(
            f"{len(quality['excluded_years'])} year(s) were excluded for having more than 5% missing data: "
            + ", ".join(map(str, quality["excluded_years"][:10]))
        )
    return {"headline": headline, "findings": findings, "period_comparison": comp, "caveats": caveats}


def build_rainfall_insights(
    region_label: str, start_year: int, end_year: int, annual: list[dict], trends: dict, threshold_label: str, quality: dict
) -> dict:
    hr = trends.get("heavy_days", {})
    comp = _window_means(annual, "heavy_days")
    total_events = sum(r.get("event_count") or 0 for r in annual if not r["excluded"])

    if total_events == 0:
        headline = f"No heavy rainfall events meeting the definition were detected in {region_label} between {start_year} and {end_year}."
    elif hr.get("status") != "ok" or comp is None:
        headline = f"{total_events} heavy rainfall events were detected in {region_label} between {start_year} and {end_year}, but there are too few complete years to assess a trend."
    else:
        e, late = comp["early"], comp["late"]
        pct = comp["percent_change"]
        if pct is None:
            change = f"from {e['mean']:.1f} to {late['mean']:.1f} days per year"
        elif hr.get("significance") == "significant":
            change = f"by {abs(pct):.0f}%"
        else:
            change = f"by {pct:+.0f}%"
        periods = f"({e['start']}–{e['end']} avg {e['mean']:.1f} days/yr vs {late['start']}–{late['end']} avg {late['mean']:.1f})"
        if hr.get("significance") == "significant":
            verb = "increased" if hr.get("direction") == "increasing" else "decreased"
            headline = f"Heavy rainfall days have {verb} {change} in {region_label} since {start_year} {periods}; the trend is statistically significant ({_p(hr)})."
        elif hr.get("significance") == "weak":
            headline = f"Heavy rainfall days in {region_label} changed {change} since {start_year} {periods}, but the evidence for a trend is weak ({_p(hr)})."
        else:
            headline = f"No statistically significant trend in heavy rainfall days in {region_label} over {start_year}–{end_year} {periods}; year-to-year variability dominates ({_p(hr)})."

    findings = [
        {
            "metric": "heavy_days",
            "text": _trend_sentence("heavy rainfall days", "days", hr),
            "significance": hr.get("significance"),
        },
        {
            "metric": "event_count",
            "text": _trend_sentence("heavy rainfall events per year", "events", trends.get("event_count", {})),
            "significance": trends.get("event_count", {}).get("significance"),
        },
        {
            "metric": "rx1day_mm",
            "text": _trend_sentence("annual maximum daily precipitation", "mm", trends.get("rx1day_mm", {})),
            "significance": trends.get("rx1day_mm", {}).get("significance"),
        },
        {
            "metric": "total_annual_precip_mm",
            "text": _trend_sentence("total annual precipitation", "mm", trends.get("total_annual_precip_mm", {})),
            "significance": trends.get("total_annual_precip_mm", {}).get("significance"),
        },
    ]

    caveats = [
        "Data are ERA5 reanalysis (~25-30 km grid), not station observations.",
        f"The heavy-rain threshold ({threshold_label}) is based on a fixed baseline; a warming climate may shift wet-day distributions.",
        "The Mann-Kendall test assumes independent years.",
    ]
    if quality.get("excluded_years"):
        caveats.append(
            f"{len(quality['excluded_years'])} year(s) were excluded for having more than 5% missing data: "
            + ", ".join(map(str, quality["excluded_years"][:10]))
        )
    return {"headline": headline, "findings": findings, "period_comparison": comp, "caveats": caveats}

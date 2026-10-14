"""CSV / PNG / PDF renderings of a stored analysis document (heatwave, drought, or rainfall)."""

import csv
import io
import textwrap

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.backends.backend_pdf import PdfPages  # noqa: E402

# Per-hazard annual columns for CSV
_HEATWAVE_COLS = [
    "year",
    "excluded",
    "event_count",
    "heatwave_days",
    "longest_event_days",
    "mean_heatwave_tmax_c",
    "peak_tmax_c",
    "cumulative_excess_cdays",
    "exceedance_days",
    "mean_annual_tmax_c",
    "annual_max_tmax_c",
]
_DROUGHT_COLS = [
    "year",
    "excluded",
    "event_count",
    "drought_days",
    "max_dry_spell",
    "cumulative_deficit_mm",
    "mean_annual_precip_mm",
    "total_annual_precip_mm",
    "dry_days_total",
]
_RAINFALL_COLS = [
    "year",
    "excluded",
    "event_count",
    "heavy_days",
    "max_event_days",
    "total_heavy_precip_mm",
    "rx1day_mm",
    "rx5day_mm",
    "total_annual_precip_mm",
    "mean_annual_precip_mm",
]

_HAZARD_LABELS = {
    "heatwave": "Heatwave",
    "drought": "Drought",
    "rainfall": "Heavy Rainfall",
}

_BAR_COLORS = {
    "heatwave": "#d97706",
    "drought": "#d97706",
    "rainfall": "#0ea5e9",
}


def _safe_cell(value) -> str:
    s = "" if value is None else str(value)
    return "'" + s if s[:1] in ("=", "+", "-", "@") and not _is_number(s) else s


def _is_number(s: str) -> bool:
    try:
        float(s)
        return True
    except ValueError:
        return False


def _hazard(doc: dict) -> str:
    return doc.get("hazard", "heatwave")


def _primary_trend_key(doc: dict) -> str:
    h = _hazard(doc)
    if h == "drought":
        return "drought_days"
    if h == "rainfall":
        return "heavy_days"
    return "heatwave_days"


def _primary_bar_field(doc: dict) -> str:
    h = _hazard(doc)
    if h == "drought":
        return "drought_days"
    if h == "rainfall":
        return "heavy_days"
    return "heatwave_days"


def _annual_cols(doc: dict) -> list[str]:
    h = _hazard(doc)
    if h == "drought":
        return _DROUGHT_COLS
    if h == "rainfall":
        return _RAINFALL_COLS
    return _HEATWAVE_COLS


def _threshold_label(doc: dict) -> str:
    t = doc.get("threshold", {})
    h = _hazard(doc)
    if h == "drought":
        return t.get("label", f"<{t.get('dry_threshold_mm', '?')} mm/day, ≥{t.get('min_duration_days', '?')} days")
    if h == "rainfall":
        return t.get("label", f"≥{t.get('value_mm', '?')} mm/day ({t.get('percentile', '?')}th pct)")
    return t.get("label", "")


def _event_csv_rows(doc: dict) -> tuple[list[str], list[list]]:
    h = _hazard(doc)
    if h == "drought":
        headers = ["start", "end", "duration_days", "min_precip_mm", "mean_precip_mm", "cumulative_deficit_mm"]
        rows = [
            [ev["start"], ev["end"], ev["duration_days"], ev["min_precip_mm"], ev["mean_precip_mm"], ev["cumulative_deficit_mm"]]
            for ev in doc.get("events", [])
        ]
    elif h == "rainfall":
        headers = ["start", "end", "duration_days", "peak_precip_mm", "mean_precip_mm", "cumulative_precip_mm"]
        rows = [
            [ev["start"], ev["end"], ev["duration_days"], ev["peak_precip_mm"], ev["mean_precip_mm"], ev["cumulative_precip_mm"]]
            for ev in doc.get("events", [])
        ]
    else:
        headers = ["start", "end", "duration_days", "peak_tmax_c", "mean_tmax_c", "mean_excess_c", "cumulative_excess_cdays"]
        rows = [[ev[h] for h in headers] for ev in doc.get("events", [])]
    return headers, rows


def analysis_to_csv(doc: dict) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    hazard = _hazard(doc)
    label = _HAZARD_LABELS.get(hazard, hazard.title())
    w.writerow([f"# Climate Hazard Trend Analyzer - {label} analysis"])
    w.writerow(["# region", _safe_cell(doc.get("region_label", ""))])
    w.writerow(["# threshold", _safe_cell(_threshold_label(doc))])
    src = doc.get("source", {})
    w.writerow(["# source", _safe_cell(src.get("dataset", "")), _safe_cell(src.get("provider", ""))])
    w.writerow(["# insight", _safe_cell(doc.get("insights", {}).get("headline", ""))])
    w.writerow([])

    cols = _annual_cols(doc)
    trend_key = _primary_trend_key(doc)
    trend = doc.get("trends", {}).get(trend_key, {})
    roll = trend.get("rolling_mean_10y", [])
    trend_line = trend.get("trend_line", [None] * len(doc.get("annual", [])))

    w.writerow([*cols, f"{trend_key}_rolling10", f"{trend_key}_trend"])
    for i, row in enumerate(doc.get("annual", [])):
        roll_val = roll[i] if i < len(roll) else None
        trend_val = trend_line[i] if i < len(trend_line) else None
        w.writerow([row.get(c) for c in cols] + [roll_val, trend_val])

    w.writerow([])
    headers, rows = _event_csv_rows(doc)
    w.writerow(headers)
    for row in rows:
        w.writerow(row)
    return buf.getvalue()


def _trend_figure(doc: dict):
    hazard = _hazard(doc)
    bar_field = _primary_bar_field(doc)
    trend_key = _primary_trend_key(doc)
    label = _HAZARD_LABELS.get(hazard, hazard.title())
    color = _BAR_COLORS.get(hazard, "#d97706")

    annual = doc.get("annual", [])
    years = [r["year"] for r in annual]
    values = [r.get(bar_field) or 0 for r in annual]
    trend = doc.get("trends", {}).get(trend_key, {})

    fig, ax = plt.subplots(figsize=(10, 4.5), dpi=110)
    ax.bar(years, values, color=color, alpha=0.85, label=f"{label} days")
    rolling = trend.get("rolling_mean_10y", [])
    if rolling:
        ax.plot(years, rolling, color="#0891b2", lw=2, label="10-yr rolling mean")
    if trend.get("trend_line"):
        ax.plot(years, trend["trend_line"], color="#475569", lw=1.5, ls="--", label="Sen's slope trend")
    ax.set_title(f"Annual {label} days — {doc.get('region_label', '')}")
    ax.set_ylabel("days / year")
    ax.grid(axis="y", alpha=0.3)
    ax.legend(loc="upper left", frameon=False)
    fig.tight_layout()
    return fig


def trend_plot_png(doc: dict) -> bytes:
    fig = _trend_figure(doc)
    buf = io.BytesIO()
    fig.savefig(buf, format="png")
    plt.close(fig)
    return buf.getvalue()


def analysis_to_pdf(doc: dict) -> bytes:
    hazard = _hazard(doc)
    label = _HAZARD_LABELS.get(hazard, hazard.title())
    buf = io.BytesIO()
    with PdfPages(buf) as pdf:
        # Page 1: text summary
        fig = plt.figure(figsize=(8.27, 11.69))  # A4 portrait
        req = doc.get("request", {})
        lines = [
            (f"{label} Trend Report", 18, "bold"),
            (doc.get("region_label", ""), 12, "normal"),
            (f"{req.get('start_year', '')}–{req.get('end_year', '')} · {doc.get('source', {}).get('dataset', '')}", 10, "normal"),
            ("", 8, "normal"),
            ("Key insight", 13, "bold"),
            *[(ln, 10, "normal") for ln in textwrap.wrap(doc.get("insights", {}).get("headline", ""), 95)],
            ("", 8, "normal"),
            ("Findings", 13, "bold"),
        ]
        for f in doc.get("insights", {}).get("findings", []):
            lines += [(("• " if i == 0 else "  ") + ln, 10, "normal") for i, ln in enumerate(textwrap.wrap(f["text"], 92))]

        lines += [("", 8, "normal"), ("Method", 13, "bold")]
        method = _method_text(doc)
        lines += [(ln, 10, "normal") for ln in textwrap.wrap(method, 95)]

        lines += [("", 8, "normal"), ("Caveats", 13, "bold")]
        for c in doc.get("insights", {}).get("caveats", []):
            lines += [(("• " if i == 0 else "  ") + ln, 9, "normal") for i, ln in enumerate(textwrap.wrap(c, 100))]

        y = 0.95
        for text, size, weight in lines:
            fig.text(0.07, y, text, fontsize=size, weight=weight, va="top")
            y -= 0.012 + size * 0.0016
        pdf.savefig(fig)
        plt.close(fig)

        # Page 2: chart
        fig = _trend_figure(doc)
        pdf.savefig(fig)
        plt.close(fig)
    return buf.getvalue()


def _method_text(doc: dict) -> str:
    h = _hazard(doc)
    t = doc.get("threshold", {})
    if h == "drought":
        return (
            f"Drought = a dry spell of at least {t.get('min_duration_days', '?')} consecutive days "
            f"with daily precipitation below {t.get('dry_threshold_mm', '?')} mm. "
            "Trends: Mann-Kendall test and Sen's slope on annual values."
        )
    if h == "rainfall":
        return (
            f"Heavy rainfall = days exceeding the {t.get('percentile', '?')}th percentile of wet-day "
            f"precipitation ({t.get('value_mm', '?')} mm/day) in the baseline period "
            f"{t.get('baseline', ['?', '?'])[0]}–{t.get('baseline', ['?', '?'])[1]}, "
            f"with events of at least {t.get('min_duration_days', '?')} day(s). "
            "Trends: Mann-Kendall test and Sen's slope on annual values."
        )
    return (
        f"Heatwave = at least {t.get('min_duration_days', '?')} consecutive days with daily maximum "
        f"temperature above {t.get('label', '?')}. Trends: Mann-Kendall test and Sen's slope on annual values."
    )

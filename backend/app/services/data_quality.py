"""Cleaning of raw daily temperature series: gaps, implausible values, spikes, incomplete years."""

from dataclasses import asdict, dataclass, field

import numpy as np
import pandas as pd

# Physically plausible range for 2 m daily maximum temperature (world records: -89 / +57 deg C).
PLAUSIBLE_MIN_C = -90.0
PLAUSIBLE_MAX_C = 60.0
# A single day that jumps this far away from *both* neighbours in the same direction is treated
# as a data error. Real heat extremes build over days, so this does not remove genuine heatwaves.
SPIKE_DELTA_C = 20.0
# Gaps up to this many consecutive days are linearly interpolated; longer gaps stay missing
# (and break heatwave runs) because inventing several days of temperature would bias detection.
MAX_INTERPOLATE_DAYS = 2
# Years missing more than this fraction of days are excluded from annual statistics and trends.
MAX_MISSING_FRACTION = 0.05


@dataclass
class QualityReport:
    total_days: int = 0
    missing_raw: int = 0
    implausible_removed: int = 0
    spikes_removed: int = 0
    interpolated: int = 0
    missing_after_cleaning: int = 0
    excluded_years: list[int] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _nan_run_lengths(mask: np.ndarray) -> np.ndarray:
    """For each True position, the length of the contiguous True run it belongs to (0 elsewhere)."""
    out = np.zeros(len(mask), dtype=int)
    i = 0
    n = len(mask)
    while i < n:
        if mask[i]:
            j = i
            while j < n and mask[j]:
                j += 1
            out[i:j] = j - i
            i = j
        else:
            i += 1
    return out


def clean_daily_series(raw: pd.Series) -> tuple[pd.Series, QualityReport]:
    report = QualityReport()
    if raw.empty:
        return raw.astype(float), report

    # 1. Regular daily index: missing timestamps become explicit NaNs.
    full_index = pd.date_range(raw.index.min().normalize(), raw.index.max().normalize(), freq="D")
    s = raw.groupby(raw.index.normalize()).mean().reindex(full_index).astype(float)
    report.total_days = len(s)
    report.missing_raw = int(s.isna().sum())

    # 2. Physically implausible values.
    implausible = (s < PLAUSIBLE_MIN_C) | (s > PLAUSIBLE_MAX_C)
    report.implausible_removed = int(implausible.sum())
    s[implausible] = np.nan

    # 3. Isolated single-day spikes.
    prev, nxt = s.shift(1), s.shift(-1)
    spike = ((s - prev > SPIKE_DELTA_C) & (s - nxt > SPIKE_DELTA_C)) | ((prev - s > SPIKE_DELTA_C) & (nxt - s > SPIKE_DELTA_C))
    report.spikes_removed = int(spike.sum())
    s[spike] = np.nan

    # 4. Interpolate short interior gaps only.
    missing = s.isna().to_numpy()
    run_len = _nan_run_lengths(missing)
    interpolated = s.interpolate(method="linear", limit_area="inside")
    fill_mask = missing & (run_len <= MAX_INTERPOLATE_DAYS) & interpolated.notna().to_numpy()
    s = s.where(~fill_mask, interpolated)
    report.interpolated = int(fill_mask.sum())
    report.missing_after_cleaning = int(s.isna().sum())

    # 5. Flag incomplete years.
    per_year = s.isna().groupby(s.index.year).mean()
    report.excluded_years = [int(y) for y, frac in per_year.items() if frac > MAX_MISSING_FRACTION]
    return s, report


# Valid range for daily precipitation in mm.
PLAUSIBLE_MAX_PRECIP_MM = 500.0


def clean_precip_series(raw: pd.Series) -> tuple[pd.Series, QualityReport]:
    """Clean daily precipitation series: clip invalid values, interpolate short gaps, flag incomplete years."""
    report = QualityReport()
    if raw.empty:
        return raw.astype(float), report

    full_index = pd.date_range(raw.index.min().normalize(), raw.index.max().normalize(), freq="D")
    s = raw.groupby(raw.index.normalize()).mean().reindex(full_index).astype(float)
    report.total_days = len(s)
    report.missing_raw = int(s.isna().sum())

    implausible = (s < 0) | (s > PLAUSIBLE_MAX_PRECIP_MM)
    report.implausible_removed = int(implausible.sum())
    s[implausible] = np.nan

    missing = s.isna().to_numpy()
    run_len = _nan_run_lengths(missing)
    interpolated = s.interpolate(method="linear", limit_area="inside")
    fill_mask = missing & (run_len <= MAX_INTERPOLATE_DAYS) & interpolated.notna().to_numpy()
    s = s.where(~fill_mask, interpolated)
    s = s.clip(lower=0)
    report.interpolated = int(fill_mask.sum())
    report.missing_after_cleaning = int(s.isna().sum())

    per_year = s.isna().groupby(s.index.year).mean()
    report.excluded_years = [int(y) for y, frac in per_year.items() if frac > MAX_MISSING_FRACTION]
    return s, report

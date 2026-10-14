import numpy as np
import pandas as pd
import pytest


def synthetic_tmax(start_year: int, end_year: int, seed: int = 0, warming_per_year: float = 0.0) -> pd.Series:
    """Seasonal cycle + noise (+ optional linear warming), a stand-in for real daily Tmax."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range(f"{start_year}-01-01", f"{end_year}-12-31", freq="D")
    doy = idx.dayofyear.to_numpy()
    seasonal = 25 + 10 * np.sin(2 * np.pi * (doy - 100) / 365.25)
    trend = warming_per_year * (idx.year.to_numpy() - start_year)
    return pd.Series(seasonal + trend + rng.normal(0, 2.5, len(idx)), index=idx)


def open_meteo_payload(series: pd.Series) -> dict:
    return {
        "daily_units": {"time": "iso8601", "temperature_2m_max": "°C"},
        "daily": {
            "time": [d.strftime("%Y-%m-%d") for d in series.index],
            "temperature_2m_max": [None if np.isnan(v) else round(float(v), 1) for v in series.to_numpy()],
        },
    }


@pytest.fixture
def tmax_factory():
    return synthetic_tmax

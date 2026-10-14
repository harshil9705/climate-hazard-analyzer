"""Trend statistics for annual indices: OLS regression, Mann-Kendall test, Sen's slope, rolling means."""

import math
from itertools import combinations

import numpy as np

MIN_TREND_POINTS = 10


# --- small distribution helpers (keeps the service free of a SciPy dependency) ---------------


def norm_cdf(z: float) -> float:
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def _betacf(a: float, b: float, x: float, max_iter: int = 200, eps: float = 1e-12) -> float:
    """Continued fraction for the regularized incomplete beta function (Numerical Recipes 6.4)."""
    tiny = 1e-300
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c, d = 1.0, 1.0 - qab * x / qap
    d = 1.0 / (d if abs(d) > tiny else tiny)
    h = d
    for m in range(1, max_iter + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > tiny else tiny)
        c = 1.0 + aa / c if abs(1.0 + aa / c) > tiny else tiny
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > tiny else tiny)
        c = 1.0 + aa / c if abs(1.0 + aa / c) > tiny else tiny
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < eps:
            break
    return h


def _betainc(a: float, b: float, x: float) -> float:
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    ln_front = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log1p(-x)
    if x < (a + 1.0) / (a + b + 2.0):
        return math.exp(ln_front) * _betacf(a, b, x) / a
    return 1.0 - math.exp(ln_front) * _betacf(b, a, 1.0 - x) / b


def t_two_sided_p(t: float, df: int) -> float:
    return _betainc(df / 2.0, 0.5, df / (df + t * t))


def t_critical(df: int, alpha: float = 0.05) -> float:
    """Two-sided critical value via bisection on the t distribution."""
    lo, hi = 0.0, 1000.0
    for _ in range(200):
        mid = (lo + hi) / 2
        if t_two_sided_p(mid, df) > alpha:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def _clean_xy(years: list[int], values: list[float | None]) -> tuple[np.ndarray, np.ndarray]:
    pairs = [(x, v) for x, v in zip(years, values, strict=True) if v is not None and not math.isnan(v)]
    if not pairs:
        return np.array([]), np.array([])
    x, y = zip(*pairs, strict=True)
    return np.asarray(x, dtype=float), np.asarray(y, dtype=float)


def mann_kendall(y: np.ndarray) -> dict:
    """Two-sided Mann-Kendall trend test with tie correction.

    Non-parametric, so it suits skewed count data like heatwave days (many zeros, a few big years).
    Note: does not correct for serial autocorrelation (Hamed & Rao) - see README.
    """
    n = len(y)
    s = 0
    for i, j in combinations(range(n), 2):
        s += int(np.sign(y[j] - y[i]))
    _, counts = np.unique(y, return_counts=True)
    ties = counts[counts > 1]
    var_s = (n * (n - 1) * (2 * n + 5) - np.sum(ties * (ties - 1) * (2 * ties + 5))) / 18.0
    if var_s <= 0:
        z = 0.0
    elif s > 0:
        z = (s - 1) / math.sqrt(var_s)
    elif s < 0:
        z = (s + 1) / math.sqrt(var_s)
    else:
        z = 0.0
    p = 2 * (1 - norm_cdf(abs(z)))
    tau = s / (0.5 * n * (n - 1)) if n > 1 else 0.0
    return {"s": int(s), "z": round(float(z), 4), "p_value": round(float(p), 5), "tau": round(float(tau), 4)}


def sens_slope(x: np.ndarray, y: np.ndarray) -> tuple[float, float]:
    slopes = [(y[j] - y[i]) / (x[j] - x[i]) for i, j in combinations(range(len(x)), 2) if x[j] != x[i]]
    slope = float(np.median(slopes)) if len(slopes) > 0 else 0.0
    intercept = float(np.median(y - slope * x))
    return slope, intercept


def ols(x: np.ndarray, y: np.ndarray) -> dict:
    """Ordinary least squares with slope standard error, p-value and 95% confidence interval."""
    n = len(x)
    df = n - 2
    xm, ym = x.mean(), y.mean()
    sxx = float(np.sum((x - xm) ** 2))
    slope = float(np.sum((x - xm) * (y - ym)) / sxx)
    intercept = float(ym - slope * xm)
    resid = y - (intercept + slope * x)
    ss_res = float(np.sum(resid**2))
    ss_tot = float(np.sum((y - ym) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
    stderr = math.sqrt(ss_res / df / sxx) if df > 0 else float("nan")
    if stderr > 0:
        p = t_two_sided_p(slope / stderr, df)
    else:
        p = 0.0 if slope != 0 else 1.0
    half = t_critical(df) * stderr
    return {
        "slope": slope,
        "intercept": intercept,
        "r_squared": round(r2, 4),
        "p_value": round(p, 5),
        "slope_ci95": [slope - half, slope + half],
    }


def rolling_mean(values: list[float | None], window: int = 10) -> list[float | None]:
    """Centred rolling mean that tolerates gaps (needs at least half the window present)."""
    arr = np.array([np.nan if v is None else v for v in values], dtype=float)
    out: list[float | None] = []
    half = window // 2
    for i in range(len(arr)):
        seg = arr[max(0, i - half) : i - half + window]
        valid = seg[~np.isnan(seg)]
        out.append(round(float(valid.mean()), 3) if len(valid) >= max(1, window // 2) else None)
    return out


def classify(p: float | None) -> str:
    if p is None:
        return "insufficient_data"
    if p < 0.05:
        return "significant"
    if p < 0.10:
        return "weak"
    return "not_significant"


def analyze_trend(years: list[int], values: list[float | None]) -> dict:
    x, y = _clean_xy(years, values)
    if len(x) < MIN_TREND_POINTS:
        return {"n": int(len(x)), "status": "insufficient_data"}
    if np.all(y == y[0]):
        # e.g. zero heatwaves every year: no variance, no trend to speak of
        return {"n": int(len(x)), "status": "constant", "direction": "none", "value": float(y[0])}

    mk = mann_kendall(y)
    sen, sen_int = sens_slope(x, y)
    reg = ols(x, y)
    direction = "increasing" if sen > 0 else "decreasing" if sen < 0 else "none"
    if direction == "none" and mk["s"] != 0:
        direction = "increasing" if mk["s"] > 0 else "decreasing"
    return {
        "n": int(len(x)),
        "status": "ok",
        "direction": direction,
        "significance": classify(mk["p_value"]),
        "mann_kendall": mk,
        "sens_slope_per_decade": round(sen * 10, 4),
        "sens_intercept": sen_int,
        "ols": {
            "slope_per_decade": round(reg["slope"] * 10, 4),
            "slope_ci95_per_decade": [round(v * 10, 4) for v in reg["slope_ci95"]],
            "intercept": reg["intercept"],
            "r_squared": reg["r_squared"],
            "p_value": reg["p_value"],
        },
        # fitted Sen line evaluated at every requested year, for plotting
        "trend_line": [round(sen_int + sen * yr, 3) for yr in years],
    }

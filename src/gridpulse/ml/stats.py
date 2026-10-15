"""Is model A really better than model B? Block bootstrap CIs and the Diebold-Mariano test.

Both work on daily mean absolute percentage errors: hourly errors inside a day are strongly
correlated, so treating 8,760 hours as independent would make every difference "significant".
"""

from dataclasses import dataclass

import numpy as np
from scipy import stats


def block_bootstrap_ci(
    daily_ape: np.ndarray, block: int = 7, n_boot: int = 2000, level: float = 0.95, seed: int = 0
) -> tuple[float, float]:
    """Percentile CI for the mean daily APE, resampling whole weeks (moving blocks)."""
    x = np.asarray(daily_ape, dtype=float)
    n = len(x)
    if n < block * 2:
        raise ValueError(f"need at least {block * 2} days, got {n}")
    rng = np.random.default_rng(seed)
    n_blocks = int(np.ceil(n / block))
    starts = rng.integers(0, n - block + 1, size=(n_boot, n_blocks))
    idx = (starts[..., None] + np.arange(block)).reshape(n_boot, -1)[:, :n]
    means = x[idx].mean(axis=1)
    alpha = (1 - level) / 2
    lo, hi = np.quantile(means, [alpha, 1 - alpha])
    return float(lo), float(hi)


@dataclass(frozen=True)
class DMResult:
    statistic: float
    p_value: float
    mean_diff: float  # mean(loss_a - loss_b); negative = A is better
    n: int


def diebold_mariano(loss_a: np.ndarray, loss_b: np.ndarray, max_lag: int = 7) -> DMResult:
    """Two-sided DM test with a Newey-West (Bartlett) variance and the Harvey-Leybourne-Newbold
    small-sample correction, for one-step-ahead (daily) losses."""
    d = np.asarray(loss_a, dtype=float) - np.asarray(loss_b, dtype=float)
    d = d[~np.isnan(d)]
    n = len(d)
    mean = d.mean()
    dc = d - mean
    var = dc @ dc / n
    for lag in range(1, max_lag + 1):
        weight = 1 - lag / (max_lag + 1)
        var += 2 * weight * (dc[lag:] @ dc[:-lag]) / n
    if var <= 0:
        return DMResult(0.0, 1.0, float(mean), n)
    dm = mean / np.sqrt(var / n)
    dm *= np.sqrt((n - 1) / n)  # HLN correction for h = 1
    p = 2 * stats.t.sf(abs(dm), df=n - 1)
    return DMResult(float(dm), float(p), float(mean), n)

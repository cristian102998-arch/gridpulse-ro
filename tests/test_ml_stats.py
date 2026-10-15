import numpy as np
import pytest

from gridpulse.ml.stats import block_bootstrap_ci, diebold_mariano


def test_bootstrap_ci_brackets_the_mean_and_is_reproducible():
    rng = np.random.default_rng(1)
    x = rng.gamma(2.0, 0.02, size=365)
    lo, hi = block_bootstrap_ci(x)
    assert lo < x.mean() < hi
    assert (lo, hi) == block_bootstrap_ci(x)


def test_bootstrap_needs_two_blocks():
    with pytest.raises(ValueError):
        block_bootstrap_ci(np.ones(10), block=7)


def test_dm_identical_forecasts_are_not_different():
    x = np.linspace(0.01, 0.05, 100)
    r = diebold_mariano(x, x)
    assert r.p_value == 1.0 and r.mean_diff == 0


def test_dm_detects_a_clearly_better_model():
    rng = np.random.default_rng(2)
    bad = rng.gamma(2.0, 0.03, size=365)
    good = bad * 0.6 + rng.normal(0, 0.002, size=365)
    r = diebold_mariano(good, bad)
    assert r.statistic < 0 and r.p_value < 0.001


def test_dm_noise_alone_is_not_significant():
    rng = np.random.default_rng(3)
    a = rng.gamma(2.0, 0.03, size=365)
    b = a + rng.normal(0, 0.01, size=365)
    assert diebold_mariano(a, b).p_value > 0.01

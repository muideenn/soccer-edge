"""Bookmaker odds -> implied probabilities, with margin (overround) removal."""
import numpy as np
from scipy.optimize import brentq


def implied(odds):
    with np.errstate(divide="ignore"):
        return 1.0 / np.asarray(odds, float)


def overround(odds):
    return implied(odds).sum(-1) - 1.0


def devig_proportional(odds):
    q = implied(odds)
    return q / q.sum(-1, keepdims=True)


def devig_power(odds):
    """Find k with sum(q_i ** k) = 1 (removes more margin from longshots)."""
    q = implied(odds)
    if abs(q.sum() - 1) < 1e-12:
        return q
    k = brentq(lambda k: np.sum(q ** k) - 1, 0.5, 3.0)
    return q ** k


def devig_shin(odds):
    """Shin (1993) model: margin attributed to insider trading; standard for 1X2 markets."""
    q = implied(odds)
    s = q.sum()
    if s <= 1:
        return q / s

    def probs(z):
        return (np.sqrt(z ** 2 + 4 * (1 - z) * q ** 2 / s) - z) / (2 * (1 - z))

    z = brentq(lambda z: probs(z).sum() - 1, 0.0, 0.4)
    return probs(z)


def devig_rows(odds2d, method="shin"):
    f = {"shin": devig_shin, "power": devig_power, "proportional": devig_proportional}[method]
    out = np.full(odds2d.shape, np.nan)
    for r in range(len(odds2d)):
        row = odds2d[r]
        if np.all(np.isfinite(row)) and np.all(row > 1):
            try:
                out[r] = f(row)
            except ValueError:
                out[r] = devig_proportional(row)
    return out

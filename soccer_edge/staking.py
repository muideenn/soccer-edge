"""Expected value, conservative fractional Kelly, and bet gating rules."""
import numpy as np


def kelly_fraction_binary(p, odds):
    b = odds - 1
    return max(0.0, (p * b - (1 - p)) / b)


def kelly_general(vals, probs, grid=2001):
    """Growth-optimal fraction for arbitrary per-unit outcomes (pushes, half wins)."""
    if np.dot(vals, probs) <= 0:
        return 0.0
    fmax = 0.999 / max(1e-9, -vals.min()) if vals.min() < 0 else 1.0
    f = np.linspace(0, min(1.0, fmax), grid)
    g = (probs[None, :] * np.log1p(f[:, None] * vals[None, :])).sum(1)
    return float(f[np.argmax(g)])


def stake(ev_lo, odds, cfg_bet, bankroll=1.0):
    """Fractional Kelly using the *lower-quantile* EV (EV_lo / (odds-1) is binary Kelly at p_lo).

    Capped by max_stake_pct. Returns stake in bankroll units. Never negative.
    """
    if ev_lo <= 0:
        return 0.0
    f = cfg_bet["kelly_fraction"] * ev_lo / (odds - 1)
    return float(min(f, cfg_bet["max_stake_pct"]) * bankroll)


def gate(ev_mean, ev_lo, odds, market, cfg_bet, data_ok=True):
    """Return (bet: bool, reason)."""
    if not data_ok:
        return False, "data not current"
    if not np.isfinite(odds):
        return False, "no odds"
    if odds < cfg_bet["min_odds"]:
        return False, "odds below minimum"
    if odds > cfg_bet["max_odds"].get(market, 5.0):
        return False, "odds above market cap"
    if ev_mean < cfg_bet["min_edge"]:
        return False, "edge below threshold"
    if cfg_bet["require_lower_ev_positive"] and ev_lo <= 0:
        return False, "edge not robust to model uncertainty"
    return True, "meets thresholds"


def rank_score(ev_lo, p, odds):
    """Lower-bound EV per unit of return volatility: favours robust edges over long shots."""
    sd = np.sqrt(max(p * (1 - p), 1e-9)) * odds
    return ev_lo / sd

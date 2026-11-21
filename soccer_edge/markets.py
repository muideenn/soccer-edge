"""Market pricing from a score matrix M[i, j] = P(home scores i, away scores j).

Every wager is represented by a per-unit return matrix R[i, j] (profit per 1 unit staked
for each final score), so EV = sum(M * R) works for 1X2, totals, BTTS, team totals and
Asian handicaps (including quarter lines and pushes) with one formula.
"""
import numpy as np


def _grid(G):
    g = np.arange(G + 1)
    return g[:, None], g[None, :]


def p1x2(M):
    i, j = _grid(M.shape[-1] - 1)
    return np.stack([(M * (i > j)).sum((-1, -2)), (M * (i == j)).sum((-1, -2)),
                     (M * (i < j)).sum((-1, -2))], -1)


def p_over(M, line):
    i, j = _grid(M.shape[-1] - 1)
    return (M * ((i + j) > line)).sum((-1, -2))


def p_btts(M):
    i, j = _grid(M.shape[-1] - 1)
    return (M * ((i > 0) & (j > 0))).sum((-1, -2))


def _ah_single(margin, line, odds):
    """Return for a whole or half line. margin = goals_for - goals_against."""
    d = margin + line
    return np.where(d > 0, odds - 1, np.where(d < 0, -1.0, 0.0))


def snap_quarter(line):
    """Sources often print quarter lines rounded (-0.25 -> -0.3, 0.75 -> 0.8). Snap to the 0.25 grid."""
    return round(float(line) * 4) / 4


def ah_return(margin, line, odds):
    line = snap_quarter(line)
    q = round(line * 4)
    if q % 2:  # quarter line: half stake on each neighbour
        return 0.5 * _ah_single(margin, line - 0.25, odds) + 0.5 * _ah_single(margin, line + 0.25, odds)
    return _ah_single(margin, line, odds)


def returns(market, selection, odds, G=10, line=None):
    """Per-unit profit matrix for a selection.

    market: 1X2 | DC | DNB | OU | BTTS | AH | TT_HOME | TT_AWAY
    selection: H/D/A, 1X/X2/12, H/A, over/under, yes/no, home/away
    line: totals line, or handicap for the *selected* side (AH).
    """
    i, j = _grid(G)
    i = i + 0 * j
    j = j + 0 * i
    win = None
    if market == "1X2":
        win = {"H": i > j, "D": i == j, "A": i < j}[selection]
    elif market == "DC":
        win = {"1X": i >= j, "X2": i <= j, "12": i != j}[selection]
    elif market == "DNB":
        w = (i > j) if selection == "H" else (i < j)
        return np.where(w, odds - 1, np.where(i == j, 0.0, -1.0))
    elif market == "OU":
        line = snap_quarter(line)
        tot = i + j
        if float(line) * 2 % 2 == 0 or round(line * 4) % 2:  # whole or quarter totals
            sgn = 1 if selection == "over" else -1
            return ah_return(sgn * tot, -sgn * line, odds)
        win = (tot > line) if selection == "over" else (tot < line)
    elif market == "BTTS":
        b = (i > 0) & (j > 0)
        win = b if selection == "yes" else ~b
    elif market == "CORNERS":  # total corners; same settlement rules as goal totals (G must cover corners)
        line = snap_quarter(line)
        tot = i + j
        if float(line) * 2 % 2 == 0 or round(line * 4) % 2:
            sgn = 1 if selection == "over" else -1
            return ah_return(sgn * tot, -sgn * line, odds)
        win = (tot > line) if selection == "over" else (tot < line)
    elif market in ("TT_HOME", "TT_AWAY"):
        goals = i if market == "TT_HOME" else j
        win = (goals > line) if selection == "over" else (goals < line)
    elif market == "AH":
        margin = (i - j) if selection == "home" else (j - i)
        return ah_return(margin, line, odds)
    else:
        raise ValueError(market)
    return np.where(win, odds - 1, -1.0)


def ev(M, R):
    return (M * R).sum((-1, -2))


def outcome_probs(M, R):
    """Distinct per-unit returns and their probabilities (for Kelly with pushes / half results)."""
    vals = np.unique(np.round(R, 10))
    return vals, np.array([(M * (np.round(R, 10) == v)).sum() for v in vals])


def fair_odds_from_returns(M, R_unit_odds_fn, lo=1.01, hi=50.0):
    """Odds at which EV = 0 (break-even price), by bisection on a returns(odds) function."""
    for _ in range(60):
        mid = (lo + hi) / 2
        if ev(M, R_unit_odds_fn(mid)) > 0:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2


def correct_scores(M, top=5):
    G = M.shape[-1]
    flat = np.argsort(M.ravel())[::-1][:top]
    return [(f"{k // G}-{k % G}", float(M.ravel()[k])) for k in flat]


def summary(M):
    """Standard market probabilities from one score matrix."""
    h, d, a = p1x2(M)
    out = {"p_home": h, "p_draw": d, "p_away": a, "p_1x": h + d, "p_x2": d + a, "p_12": h + a,
           "p_dnb_home": h / (h + a), "p_btts": p_btts(M)}
    for L in (0.5, 1.5, 2.5, 3.5, 4.5):
        out[f"p_over{L}"] = p_over(M, L)
    G = M.shape[-1] - 1
    i, j = _grid(G)
    out["xg_home"] = float((M * i).sum())
    out["xg_away"] = float((M * j).sum())
    for L in (0.5, 1.5, 2.5):
        out[f"p_home_over{L}"] = float((M * (i + 0 * j > L)).sum())
        out[f"p_away_over{L}"] = float((M * (0 * i + j > L)).sum())
    return {k: float(v) for k, v in out.items()}

"""Market anchoring.

The raw models are less accurate than the closing-ish bookmaker prices, so treating every
model/market disagreement as an edge is mostly betting on model error. Here we:

1. back out the market-implied goal rates (λh, λa) that best reproduce the de-margined
   1X2 and Over/Under 2.5 prices under the Dixon-Coles score distribution;
2. blend in log space: log λ = w · log λ_model + (1 - w) · log λ_market,
   with w chosen on validation seasons only.

Every market (1X2, totals, BTTS, Asian handicap) is then priced from one blended score
matrix, so the probabilities stay mutually consistent.
"""
import numpy as np
from scipy.optimize import least_squares

from .dixon_coles import score_matrix
from .markets import p1x2, p_over


def market_lambdas(p3, po25, rho, G=10):
    """p3: de-margined (H, D, A); po25: de-margined P(over 2.5) or nan. Returns (lh, la, resid)."""
    target = np.r_[p3, po25] if np.isfinite(po25) else np.asarray(p3)

    def f(x):
        M = score_matrix(np.exp(x[0]), np.exp(x[1]), rho, G)
        r = p1x2(M)
        if np.isfinite(po25):
            r = np.r_[r, p_over(M, 2.5)]
        return r - target

    x0 = np.log([1.5, 1.15])
    s = least_squares(f, x0, bounds=([-3, -3], [1.8, 1.8]), xtol=1e-9, ftol=1e-10)
    return float(np.exp(s.x[0])), float(np.exp(s.x[1])), float(np.sqrt(np.mean(s.fun ** 2)))


def add_market_lambdas(dom, mask):
    from .odds import devig_rows
    idx = np.where(mask & dom.b365_h.notna().values & dom.dc_rho.notna().values)[0]
    q3 = devig_rows(dom[["b365_h", "b365_d", "b365_a"]].values[idx], "shin")
    q2 = devig_rows(dom[["b365_o25", "b365_u25"]].values[idx], "proportional")[:, 0]
    out = np.full((len(dom), 3), np.nan)
    rho = dom.dc_rho.values
    for k, i in enumerate(idx):
        if np.all(np.isfinite(q3[k])):
            out[i] = market_lambdas(q3[k], q2[k], rho[i])
    dom["mkt_lh"], dom["mkt_la"], dom["mkt_fit_rmse"] = out[:, 0], out[:, 1], out[:, 2]
    return dom


def blend_eta(eta_model_h, eta_model_a, mkt_lh, mkt_la, w):
    return w * eta_model_h + (1 - w) * np.log(mkt_lh), w * eta_model_a + (1 - w) * np.log(mkt_la)


def choose_weight(dom, y, val_mask, grid=np.round(np.arange(0, 1.0001, 0.05), 2)):
    from .models_ml import logloss
    m = val_mask & dom.mkt_lh.notna().values
    o = (dom.hg + dom.ag > 2.5).values[m]
    rows = []
    for w in grid:
        eh, ea = blend_eta(dom.dc_eta_h.values[m], dom.dc_eta_a.values[m], dom.mkt_lh.values[m], dom.mkt_la.values[m], w)
        M = score_matrix(np.exp(eh), np.exp(ea), dom.dc_rho.values[m][:, None, None])
        P = p1x2(M)
        po = np.clip(p_over(M, 2.5), 1e-9, 1 - 1e-9)
        ll1 = logloss(P, y[m])
        ll2 = -np.mean(np.where(o, np.log(po), np.log(1 - po)))
        rows.append((w, ll1, ll2, ll1 + ll2))
    best = min(rows, key=lambda r: r[3])
    return best[0], rows

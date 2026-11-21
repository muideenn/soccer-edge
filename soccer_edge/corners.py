"""Corner-kick model.

Each team gets a time-weighted "corners won" and "corners conceded" rating (the same
penalised Poisson regression as the goals model, fitted on corner counts). Match corner
counts are then drawn from negative-binomial marginals whose dispersion is chosen on
validation seasons, because corner counts are more variable than a Poisson allows.

No historical corner *odds* exist in the training data, so corner betting rules cannot be
validated; the app shows corner probabilities and lets corner legs into parlays, but
labels them unvalidated and never recommends them as singles.
"""
import numpy as np
import pandas as pd
from scipy.stats import nbinom, poisson

from .dixon_coles import DixonColes

GMAX = 20


def corner_pmf(lam, k, G=GMAX):
    """Marginal pmf for 0..G corners; k=None -> Poisson, else NB with size k (var = m + m^2/k)."""
    g = np.arange(G + 1)
    lam = np.asarray(lam, float)[..., None]
    if k is None:
        p = poisson.pmf(g, lam)
    else:
        p = nbinom.pmf(g, k, k / (k + lam))
    return p / p.sum(-1, keepdims=True)


def corner_matrix(lh, la, k, G=GMAX):
    ph, pa = corner_pmf(lh, k, G), corner_pmf(la, k, G)
    return ph[..., :, None] * pa[..., None, :]


def fit_corner_model(hist, ref_date, cfg):
    c = cfg["corners"]
    past = hist[(hist.date < ref_date) & (hist.date >= ref_date - pd.Timedelta(days=c["window_days"]))]
    past = past.dropna(subset=["hc", "ac"])
    if len(past) < 150:
        return None
    df = past.assign(hg=past.hc, ag=past.ac)
    m = DixonColes(c["xi"], c["l2"], GMAX).fit(df, ref_date)
    m.rho = 0.0
    return m


def corners_walk_forward(matches, cfg, start, end):
    rows = []
    for name, lg in cfg["leagues"].items():
        hist = matches[(matches.comp == name)]
        target = hist[(hist.date >= start) & (hist.date < end)].dropna(subset=["hc", "ac"])
        edges = pd.date_range(pd.Timestamp(start) - pd.Timedelta(days=pd.Timestamp(start).weekday()),
                              end + pd.Timedelta(days=7), freq="7D")
        for a, b in zip(edges[:-1], edges[1:]):
            blk = target[(target.date >= a) & (target.date < b)]
            if not len(blk):
                continue
            m = fit_corner_model(hist, a, cfg)
            if m is None:
                continue
            for r in blk.itertuples(index=False):
                lp = m.linear_predictor(r.home, r.away)
                if lp is None:
                    continue
                eta, cov = lp
                rows.append({"match_id": r.match_id, "comp": name, "season": r.season, "hc": r.hc, "ac": r.ac,
                             "c_lh": float(np.exp(eta[0])), "c_la": float(np.exp(eta[1]))})
    return pd.DataFrame(rows)


def _ll(df, k):
    M = corner_matrix(df.c_lh.values, df.c_la.values, k)
    h = np.clip(df.hc.values.astype(int), 0, GMAX)
    a = np.clip(df.ac.values.astype(int), 0, GMAX)
    return -np.mean(np.log(np.clip(M[np.arange(len(df)), h, a], 1e-12, 1)))


def evaluate(cfg, matches, out_dir):
    """Choose dispersion on validation seasons, then score test seasons against base rates."""
    import json
    c = cfg["corners"]
    vs, ts = c["validation_seasons"], c["test_seasons"]
    wf = corners_walk_forward(matches, cfg, pd.Timestamp(f"{min(vs)}-07-01"), pd.Timestamp(f"{max(ts) + 1}-07-01"))
    val, test = wf[wf.season.isin(vs)], wf[wf.season.isin(ts)]
    grid = [None, 40.0, 20.0, 12.0, 8.0, 5.0]
    scores = {str(k): _ll(val, k) for k in grid}
    best = min(grid, key=lambda k: scores[str(k)])
    M = corner_matrix(test.c_lh.values, test.c_la.values, best)
    tot = (test.hc + test.ac).values
    train = matches[(matches.tier == 1) & matches.season.isin(range(min(vs) - 4, min(vs)))].dropna(subset=["hc", "ac"])
    base_tot = (train.hc + train.ac).values
    i = np.arange(GMAX + 1)
    S = i[:, None] + i[None, :]
    lines = []
    for L in (8.5, 9.5, 10.5, 11.5):
        p = np.clip((M * (S > L)).sum((-1, -2)), 1e-9, 1 - 1e-9)
        o = tot > L
        b = np.clip((base_tot > L).mean(), 1e-9, 1 - 1e-9)
        lines.append({"line": L, "n": int(len(o)), "observed_over": float(o.mean()), "model_mean_p": float(p.mean()),
                      "logloss_model": float(-np.mean(np.where(o, np.log(p), np.log(1 - p)))),
                      "logloss_base_rate": float(-np.mean(np.where(o, np.log(b), np.log(1 - b)))),
                      "brier_model": float(np.mean((p - o) ** 2)), "brier_base_rate": float(np.mean((b - o) ** 2))})
    # calibration of P(over 9.5) in deciles
    p95 = (M * (S > 9.5)).sum((-1, -2))
    q = pd.qcut(p95, 8, duplicates="drop")
    cal = pd.DataFrame({"p": p95, "o": tot > 9.5, "q": q}).groupby("q", observed=True).agg(mean_pred=("p", "mean"), observed=("o", "mean"), n=("o", "size"))
    res = {"dispersion_k": best, "validation_logloss_by_k": scores, "test_seasons": ts, "validation_seasons": vs,
           "lines": lines, "calibration_over9_5": cal.reset_index(drop=True).to_dict("records"),
           "mean_total_pred": float((M * S).sum((-1, -2)).mean()), "mean_total_obs": float(tot.mean()),
           "note": "No historical corner odds in the data: corner probabilities are evaluated, corner betting rules are not."}
    json.dump(res, open(out_dir / "corners_metrics.json", "w"), indent=2)
    return res

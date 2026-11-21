"""Leak-free walk-forward forecasting.

Every prediction for a match on date D is produced by a model fitted only on matches
strictly before the start of D's forecast block (weekly blocks in backtests; the
as-of date for live reports).
"""
import numpy as np
import pandas as pd

from .dixon_coles import DixonColes, score_matrix
from .elo import attach_clubelo, run_elo
from .markets import p1x2, p_over


# ---------------------------------------------------------------- Dixon-Coles
def dc_block_predict(model, hist, block, cfg, ref_date):
    dcc = cfg["dixon_coles"]
    past = hist[(hist.date < ref_date) & (hist.date >= ref_date - pd.Timedelta(days=dcc["window_days"]))]
    if not dcc["use_second_division"]:
        past = past[past.tier == 1]
    past = past.dropna(subset=["hg", "ag"])
    if len(past) < 200:
        return []
    model.fit(past, ref_date)
    out = []
    for r in block.itertuples(index=False):
        lp = model.linear_predictor(r.home, r.away)
        if lp is None:
            continue
        eta, cov = lp
        out.append({"match_id": r.match_id, "dc_eta_h": eta[0], "dc_eta_a": eta[1],
                    "dc_v_h": cov[0, 0], "dc_v_a": cov[1, 1], "dc_c_ha": cov[0, 1],
                    "dc_rho": model.rho, "dc_ntrain": model.n_train,
                    "dc_fit_date": ref_date})
    return out


def dc_walk_forward(matches, cfg, start, end, countries=None, freq="7D"):
    """Weekly refits per country; returns DC linear predictors for tier-1 matches in [start, end)."""
    dcc = cfg["dixon_coles"]
    rows = []
    countries = countries or [lg["country"] for lg in cfg["leagues"].values()]
    for c in countries:
        hist = matches[(matches.country == c) & matches.tier.isin([1, 2])]
        target = hist[(hist.tier == 1) & (hist.date >= start) & (hist.date < end)]
        model = DixonColes(dcc["xi"], dcc["l2"], dcc["max_goals"])
        edges = pd.date_range(pd.Timestamp(start) - pd.Timedelta(days=pd.Timestamp(start).weekday()),
                              end + pd.Timedelta(days=7), freq=freq)
        for a, b in zip(edges[:-1], edges[1:]):
            blk = target[(target.date >= a) & (target.date < b)]
            if len(blk):
                rows += dc_block_predict(model, hist, blk, cfg, a)
    return pd.DataFrame(rows)


def dc_probs(df):
    """Point-estimate 1X2 / O2.5 probabilities from stored DC linear predictors."""
    lh, la = np.exp(df.dc_eta_h.values), np.exp(df.dc_eta_a.values)
    M = score_matrix(lh, la, df.dc_rho.values[:, None, None])
    p = p1x2(M)
    return pd.DataFrame({"match_id": df.match_id.values, "dc_ph": p[:, 0], "dc_pd": p[:, 1],
                         "dc_pa": p[:, 2], "dc_po25": p_over(M, 2.5), "dc_lh": lh, "dc_la": la})


# ---------------------------------------------------------------- Elo-Poisson
def _poisson_irls(X, y, l2=1e-3, iters=30):
    b = np.zeros(X.shape[1])
    b[0] = np.log(y.mean())
    for _ in range(iters):
        mu = np.exp(X @ b)
        g = X.T @ (y - mu) - l2 * b
        H = (X * mu[:, None]).T @ X + l2 * np.eye(len(b))
        s = np.linalg.solve(H, g)
        b += s
        if np.abs(s).max() < 1e-8:
            break
    return b, np.linalg.inv(H)


def _ep_design(df):
    """Rows: home-goal and away-goal observations; features: 1, home flag, elo diff/400, tier2, ucl."""
    N = len(df)
    hf = (~df.neutral.values.astype(bool)).astype(float)
    d = (df.elo_h.values - df.elo_a.values) / 400
    t2 = (df.tier.values == 2).astype(float)
    ucl = (df.tier.values == 0).astype(float)
    Xh = np.column_stack([np.ones(N), hf, d, t2, ucl])
    Xa = np.column_stack([np.ones(N), np.zeros(N), -d, t2, ucl])
    return Xh, Xa


def elo_poisson_fit_predict(train, target):
    Xh, Xa = _ep_design(train)
    X = np.vstack([Xh, Xa])
    y = np.concatenate([train.hg.values, train.ag.values]).astype(float)
    b, cov = _poisson_irls(X, y)
    th, ta = _ep_design(target)
    return th @ b, ta @ b, b


def elo_poisson_walk_forward(matches, seasons, years_back=4):
    out = []
    for s in seasons:
        tr = matches[(matches.season >= s - years_back) & (matches.season < s)].dropna(subset=["hg", "ag"])
        tg = matches[(matches.season == s) & (matches.tier != 2)]
        if not len(tr) or not len(tg):
            continue
        eh, ea, b = elo_poisson_fit_predict(tr, tg)
        out.append(pd.DataFrame({"match_id": tg.match_id.values, "ep_lh": np.exp(eh), "ep_la": np.exp(ea)}))
    df = pd.concat(out, ignore_index=True)
    M = score_matrix(df.ep_lh.values, df.ep_la.values, -0.05)  # small fixed low-score correction
    p = p1x2(M)
    df["ep_ph"], df["ep_pd"], df["ep_pa"] = p[:, 0], p[:, 1], p[:, 2]
    df["ep_po25"] = p_over(M, 2.5)
    return df


# ---------------------------------------------------------------- team-form features
def team_form(matches):
    """Rolling pre-match form per team across all competitions (shifted: no leakage)."""
    m = matches[["match_id", "date", "home", "away", "hg", "ag", "hst", "ast", "tier"]]
    h = pd.DataFrame({"match_id": m.match_id, "date": m.date, "team": m.home, "side": "h",
                      "gf": m.hg, "ga": m.ag, "sotf": m.hst, "sota": m.ast})
    a = pd.DataFrame({"match_id": m.match_id, "date": m.date, "team": m.away, "side": "a",
                      "gf": m.ag, "ga": m.hg, "sotf": m.ast, "sota": m.hst})
    L = pd.concat([h, a]).sort_values(["team", "date", "match_id"]).reset_index(drop=True)
    L["pts"] = np.where(L.gf > L.ga, 3, np.where(L.gf == L.ga, 1, 0)).astype(float)
    L.loc[L.gf.isna(), "pts"] = np.nan
    g = L.groupby("team", sort=False)
    L["rest"] = (L.date - g.date.shift(1)).dt.days.clip(upper=21)
    for col, w in (("pts", 5), ("gf", 6), ("ga", 6), ("sotf", 6), ("sota", 6)):
        L[f"{col}_r"] = g[col].transform(lambda s: s.shift(1).rolling(w, min_periods=2).mean())
    feats = ["rest", "pts_r", "gf_r", "ga_r", "sotf_r", "sota_r"]
    H = L[L.side == "h"].set_index("match_id")[feats].add_suffix("_h")
    A = L[L.side == "a"].set_index("match_id")[feats].add_suffix("_a")
    return H.join(A).reset_index()


def build_base(matches, fixtures, clubelo, cfg):
    """All results + upcoming fixtures with leak-free Elo, ClubElo and form features."""
    fx = fixtures.copy()
    if len(fx):
        fx["tier"] = np.where(fx.comp == "UCL", 0, 1)
        fx["neutral"] = False
        fx["match_id"] = (fx.date.dt.strftime("%Y%m%d") + "_" + fx.comp + "_" +
                          fx.home.str.replace(" ", "") + "_" + fx.away.str.replace(" ", ""))
        fx["is_fixture"] = True
    m = matches.assign(is_fixture=False)
    allm = pd.concat([m, fx], ignore_index=True).sort_values(["date", "match_id"]).reset_index(drop=True)
    for c in ("hg", "ag", "hthg", "htag", "hs", "as_", "hst", "ast", "hc", "ac"):
        if c in allm:
            allm[c] = pd.to_numeric(allm[c], errors="coerce")
    elo, ratings = run_elo(allm, cfg)
    allm = allm.merge(elo, on="match_id", how="left")
    allm = attach_clubelo(allm, clubelo)
    allm = allm.merge(team_form(allm), on="match_id", how="left")
    allm["elo_diff"] = allm.elo_h - allm.elo_a + np.where(allm.neutral, 0, cfg["elo"]["home_adv"])
    allm["ce_diff"] = allm.ce_h - allm.ce_a
    return allm, ratings

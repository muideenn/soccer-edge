"""1X2 classifiers trained season-by-season on leak-free features, plus validated ensembling."""
import itertools

import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

FEATURES = ["dc_ph", "dc_pd", "dc_pa", "dc_lh", "dc_la", "ep_ph", "ep_pa", "elo_diff", "ce_diff",
            "rest_h", "rest_a", "pts_r_h", "pts_r_a", "gf_r_h", "ga_r_h", "gf_r_a", "ga_r_a",
            "sotf_r_h", "sota_r_h", "sotf_r_a", "sota_r_a"]
MODELS = ["dc", "ep", "elo_logit", "logit_full", "gbm"]
MKT_FEATURES = ["mkt_lo_h", "mkt_lo_a"]  # market log-odds vs draw


def make_models():
    return {
        "elo_logit": (["elo_diff"], make_pipeline(SimpleImputer(), StandardScaler(),
                                                  LogisticRegression(C=1.0, max_iter=500))),
        "logit_full": (FEATURES, make_pipeline(SimpleImputer(strategy="median"), StandardScaler(),
                                               LogisticRegression(C=0.3, max_iter=2000))),
        # residual test: does anything add information beyond the bookmaker price?
        "mkt_plus": (MKT_FEATURES + FEATURES, make_pipeline(SimpleImputer(strategy="median"), StandardScaler(),
                                                             LogisticRegression(C=0.1, max_iter=2000))),
        "mkt_only": (MKT_FEATURES, make_pipeline(SimpleImputer(strategy="median"), StandardScaler(),
                                                  LogisticRegression(C=1.0, max_iter=2000))),
        "gbm": (FEATURES, HistGradientBoostingClassifier(max_iter=250, learning_rate=0.04, max_leaf_nodes=15,
                                                         min_samples_leaf=80, l2_regularization=1.0,
                                                         random_state=0)),
    }


def fit_predict_season(df, y, season, first_season):
    """Train on seasons [first_season, season-1]; predict `season`. Returns {name: (n,3) probs}."""
    tr = (df.season >= first_season) & (df.season < season)
    te = df.season == season
    out = {}
    for name, (feats, mdl) in make_models().items():
        if name.startswith("mkt"):
            trm = tr & df.mkt_lo_h.notna()
            mdl.fit(df.loc[trm, feats], y[trm])
            out[name] = mdl.predict_proba(df.loc[te, feats])
            continue
        mdl.fit(df.loc[tr, feats], y[tr])
        out[name] = mdl.predict_proba(df.loc[te, feats])
    return out, te


def logloss(P, y):
    P = np.clip(P, 1e-12, 1)
    return -np.mean(np.log(P[np.arange(len(y)), y]))


def brier(P, y):
    Y = np.eye(3)[y]
    return np.mean(np.sum((P - Y) ** 2, 1))


def rps(P, y):
    Y = np.eye(3)[y]
    c = np.cumsum(P, 1)[:, :2] - np.cumsum(Y, 1)[:, :2]
    return np.mean(np.sum(c ** 2, 1) / 2)


def choose_ensemble(preds, y, step=0.1):
    """Grid search simplex weights on *validation* predictions. Single models are corners."""
    names = list(preds)
    k = len(names)
    best = (np.inf, None)
    ticks = int(round(1 / step))
    for c in itertools.product(range(ticks + 1), repeat=k - 1):
        if sum(c) > ticks:
            continue
        w = np.array(list(c) + [ticks - sum(c)]) / ticks
        P = sum(wi * preds[n] for wi, n in zip(w, names))
        ll = logloss(P, y)
        if ll < best[0]:
            best = (ll, w)
    return dict(zip(names, best[1])), best[0]

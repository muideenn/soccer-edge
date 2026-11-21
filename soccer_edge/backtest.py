"""Chronological out-of-sample evaluation of probabilities and of the betting rules."""
import json
import pickle
from pathlib import Path

import numpy as np
import pandas as pd

from . import markets as mk
from .config import p
from .dixon_coles import score_matrix
from .forecast import dc_probs, dc_walk_forward, elo_poisson_walk_forward
from .models_ml import MODELS, brier, choose_ensemble, fit_predict_season, logloss, rps
from .odds import devig_rows
from .anchor import add_market_lambdas, blend_eta, choose_weight
from .staking import gate, rank_score, stake


def outcome_idx(df):
    return np.select([df.hg > df.ag, df.hg == df.ag], [0, 1], 2)


# ------------------------------------------------------------------ probability forecasts
def build_forecasts(base, cfg, cache=None):
    if cache and Path(cache).exists():
        return pickle.load(open(cache, "rb"))
    bt = cfg["backtest"]
    res = base[~base.is_fixture.astype(bool)]
    start = pd.Timestamp(f"{bt['first_feature_season']}-07-01")
    end = res.date.max() + pd.Timedelta(days=1)
    dc = dc_walk_forward(res, cfg, start, end)
    seasons = list(range(bt["first_feature_season"], res.season.max() + 1))
    ep = elo_poisson_walk_forward(res, seasons)
    df = res.merge(dc, on="match_id", how="left").merge(dc_probs(dc.dropna()), on="match_id", how="left")
    df = df.merge(ep, on="match_id", how="left")
    if cache:
        pickle.dump(df, open(cache, "wb"))
    return df


def eval_models(df, cfg):
    """Season-by-season ML fits; ensemble weights chosen on validation seasons only."""
    bt = cfg["backtest"]
    dom = df[(df.tier == 1) & df.dc_ph.notna() & df.ep_ph.notna()].copy().reset_index(drop=True)
    y = outcome_idx(dom)
    Q = devig_rows(dom[["b365_h", "b365_d", "b365_a"]].values, "shin")
    dom["mkt_ph"], dom["mkt_pd"], dom["mkt_pa"] = Q[:, 0], Q[:, 1], Q[:, 2]
    dom["mkt_lo_h"], dom["mkt_lo_a"] = np.log(Q[:, 0] / Q[:, 1]), np.log(Q[:, 2] / Q[:, 1])
    for n in ("elo_logit", "logit_full", "gbm", "mkt_plus", "mkt_only"):
        for k in ("h", "d", "a"):
            dom[f"{n}_p{k}"] = np.nan
    for s in bt["validation_seasons"] + bt["test_seasons"]:
        preds, te = fit_predict_season(dom, y, s, bt["first_feature_season"])
        for n, P in preds.items():
            dom.loc[te, [f"{n}_ph", f"{n}_pd", f"{n}_pa"]] = P
    get = lambda n, m: dom.loc[m, [f"{n}_ph", f"{n}_pd", f"{n}_pa"]].values  # noqa: E731
    val = dom.season.isin(bt["validation_seasons"]).values
    w, ll = choose_ensemble({n: get(n, val) for n in MODELS}, y[val])
    P = sum(w[n] * dom[[f"{n}_ph", f"{n}_pd", f"{n}_pa"]].values for n in MODELS)
    dom["ens_ph"], dom["ens_pd"], dom["ens_pa"] = P[:, 0], P[:, 1], P[:, 2]
    dc_val = logloss(get("dc", val), y[val])
    ens_ll = logloss(get("ens", val), y[val])
    use_ens = ens_ll < dc_val - 0.001  # combine only if validation shows a real improvement
    return dom, y, {"weights": w, "val_logloss_ens": ens_ll, "val_logloss_dc": dc_val, "bet_model": "ens" if use_ens else "dc"}


def prob_metrics(dom, y, mask, names):
    rows = []
    has_mkt = mask & dom.mkt_ph.notna().values
    for n in names:
        P = dom[[f"{n}_ph", f"{n}_pd", f"{n}_pa"]].values
        for label, m in (("all", mask), ("with_odds", has_mkt)):
            if not m.any() or np.isnan(P[m]).any():
                continue
            rows.append({"model": n, "subset": label, "n": int(m.sum()), "logloss": logloss(P[m], y[m]),
                         "brier": brier(P[m], y[m]), "rps": rps(P[m], y[m]),
                         "accuracy": float(np.mean(P[m].argmax(1) == y[m]))})
    return pd.DataFrame(rows)


def calibration(dom, y, mask, names, bins=np.linspace(0, 1, 11)):
    rows = []
    for n in names:
        P = dom[[f"{n}_ph", f"{n}_pd", f"{n}_pa"]].values
        for k, lab in enumerate("HDA"):
            p_, o = P[mask, k], (y[mask] == k)
            ok = np.isfinite(p_)
            b = np.digitize(p_[ok], bins) - 1
            for bi in np.unique(b):
                s = b == bi
                if s.sum() >= 30:
                    rows.append({"model": n, "outcome": lab, "bin": f"{bins[bi]:.1f}-{bins[bi + 1]:.1f}",
                                 "n": int(s.sum()), "mean_pred": float(p_[ok][s].mean()), "observed": float(o[ok][s].mean())})
    return pd.DataFrame(rows)


# ------------------------------------------------------------------ betting simulation
def candidate_bets(r, draws_M, p_ens, cfg, odds_src="b365"):
    """All candidate selections for one match with EV mean / lower quantile."""
    q = cfg["simulation"]["lower_quantile"]
    G = draws_M.shape[-1] - 1
    Mbar = draws_M.mean(0)
    cands = []
    c1 = [("H", f"{odds_src}_h", 0), ("D", f"{odds_src}_d", 1), ("A", f"{odds_src}_a", 2)]
    for sel, col, k in c1:
        o = getattr(r, col)
        if not np.isfinite(o):
            continue
        R = mk.returns("1X2", sel, o, G)
        evd = mk.ev(draws_M, R)
        ev_dc, ev_dc_lo = evd.mean(), np.quantile(evd, q)
        if p_ens is not None:
            ev_m = p_ens[k] * o - 1
            ev_lo = ev_m - (ev_dc - ev_dc_lo)
            pp = p_ens[k]
        else:
            ev_m, ev_lo, pp = ev_dc, ev_dc_lo, (ev_dc + 1) / o
        cands.append(("1X2", sel, np.nan, o, pp, ev_m, ev_lo, R))
    if odds_src == "b365":
        for sel, col in (("over", "b365_o25"), ("under", "b365_u25")):
            o = getattr(r, col)
            if np.isfinite(o):
                R = mk.returns("OU", sel, o, G, 2.5)
                evd = mk.ev(draws_M, R)
                cands.append(("OU25", sel, 2.5, o, mk.ev(Mbar, (R > 0).astype(float)), evd.mean(), np.quantile(evd, q), R))
        if np.isfinite(r.ah_line):
            for sel, col, line in (("home", "b365_ahh", r.ah_line), ("away", "b365_aha", -r.ah_line)):
                o = getattr(r, col)
                if np.isfinite(o):
                    R = mk.returns("AH", sel, o, G, line)
                    evd = mk.ev(draws_M, R)
                    cands.append(("AH", sel, line, o, mk.ev(Mbar, (R > 0).astype(float)), evd.mean(), np.quantile(evd, q), R))
    return cands


def simulate_bets(dom, mask, cfg, bet_model, odds_src="b365", seed=0, w=None):
    rng = np.random.default_rng(seed)
    nd = cfg["backtest"]["mc_draws"]
    bcfg = cfg["betting"]
    G = cfg["dixon_coles"]["max_goals"]
    rows = []
    sub = dom[mask & dom[f"{odds_src}_h"].notna()]
    if bet_model == "anch":
        sub = sub[sub.mkt_lh.notna()]
    for r in sub.itertuples(index=False):
        eta = np.array([r.dc_eta_h, r.dc_eta_a])
        cov = np.array([[r.dc_v_h, r.dc_c_ha], [r.dc_c_ha, r.dc_v_a]])
        z = rng.standard_normal((nd, 2)) @ np.linalg.cholesky(cov + 1e-12 * np.eye(2)).T + eta
        if bet_model == "anch":
            zh, za = blend_eta(z[:, 0], z[:, 1], r.mkt_lh, r.mkt_la, w)
            z = np.column_stack([zh, za])
        Md = score_matrix(np.exp(z[:, 0]), np.exp(z[:, 1]), r.dc_rho, G)
        p_ens = (np.array([getattr(r, f"{bet_model}_ph"), getattr(r, f"{bet_model}_pd"), getattr(r, f"{bet_model}_pa")])
                 if bet_model not in ("dc", "anch") else None)
        best = {}
        cands = candidate_bets(r, Md, p_ens, cfg, odds_src)
        if bet_model == "mkt_plus":  # residual model prices 1X2 only
            cands = [c for c in cands if c[0] == "1X2"]
        for mkt, sel, line, o, pp, ev_m, ev_lo, R in cands:
            ok, why = gate(ev_m, ev_lo, o, mkt, bcfg)
            if not ok:
                continue
            sc = rank_score(ev_lo, pp, o)
            if mkt not in best or sc > best[mkt][0]:
                hg, ag = int(min(r.hg, G)), int(min(r.ag, G))
                clv = np.nan
                ccol = {("1X2", "H"): "c_h", ("1X2", "D"): "c_d", ("1X2", "A"): "c_a", ("OU25", "over"): "c_o25",
                        ("OU25", "under"): "c_u25", ("AH", "home"): "c_ahh", ("AH", "away"): "c_aha"}.get((mkt, sel))
                if ccol and np.isfinite(getattr(r, ccol)):
                    clv = o / getattr(r, ccol) - 1
                best[mkt] = (sc, {"match_id": r.match_id, "date": r.date, "comp": r.comp, "season": r.season,
                                  "home": r.home, "away": r.away, "market": mkt, "selection": sel, "line": line,
                                  "odds": o, "model_p": pp, "ev": ev_m, "ev_lo": ev_lo, "rank": sc,
                                  "kelly_stake_frac": stake(ev_lo, o, bcfg), "score": f"{int(r.hg)}-{int(r.ag)}",
                                  "profit": float(R[hg, ag]), "clv": clv})
        rows += [v[1] for v in best.values()]
    return pd.DataFrame(rows)


def bankroll_path(bets, cfg):
    """Fractional-Kelly bankroll, stakes set from start-of-day bankroll, daily exposure capped."""
    cap = cfg["betting"]["max_matchday_exposure_pct"]
    bank, path = 1.0, []
    for d, g in bets.sort_values("date").groupby("date"):
        f = g.kelly_stake_frac.values
        if f.sum() > cap:
            f = f * cap / f.sum()
        bank += float(np.sum(f * bank * g.profit.values))
        path.append((d, bank))
    return pd.DataFrame(path, columns=["date", "bankroll"])


def max_drawdown(series):
    s = np.asarray(series, float)
    peak = np.maximum.accumulate(s)
    return float(np.max(peak - s)) if len(s) else 0.0


def longest_losing_streak(profits):
    best = cur = 0
    for x in profits:
        cur = cur + 1 if x < 0 else 0
        best = max(best, cur)
    return best


def bet_summary(b, by=None, n_boot=2000, seed=1):
    rng = np.random.default_rng(seed)

    def one(g):
        pr = g.profit.values
        roi = pr.mean() if len(pr) else np.nan
        if len(pr) > 1:
            bs = rng.choice(pr, (n_boot, len(pr))).mean(1)
            lo, hi = np.quantile(bs, [0.025, 0.975])
        else:
            lo = hi = np.nan
        cum = np.cumsum(pr)
        return pd.Series({"bets": len(pr), "hit_rate": float(np.mean(pr > 0)) if len(pr) else np.nan,
                          "avg_odds": g.odds.mean(), "avg_ev_claimed": g.ev.mean(), "roi_flat": roi,
                          "roi_ci95_lo": lo, "roi_ci95_hi": hi, "profit_units": pr.sum(),
                          "max_drawdown_units": max_drawdown(np.r_[0, cum]),
                          "longest_losing_streak": longest_losing_streak(pr),
                          "clv_mean": g.clv.mean() if g.clv.notna().any() else np.nan})
    if by is None:
        return one(b).to_frame().T
    return b.groupby(by).apply(one, include_groups=False).reset_index()


def odds_band(o):
    return pd.cut(o, [1, 1.6, 2.2, 3.0, 4.5, 100], labels=["1.0-1.6", "1.6-2.2", "2.2-3.0", "3.0-4.5", "4.5+"])


def totals_metrics(dom, mask):
    m = mask & dom.b365_o25.notna().values & dom.dc_po25.notna().values & dom.anch_po25.notna().values
    o = (dom.hg + dom.ag > 2.5).values[m]
    q = devig_rows(dom.loc[m, ["b365_o25", "b365_u25"]].values, "proportional")[:, 0]
    out = []
    for name, pp in (("dc", dom.dc_po25.values[m]), ("ep", dom.ep_po25.values[m]),
                     ("anchored", dom.anch_po25.values[m]), ("market", q),
                     ("base_rate", np.full(m.sum(), o.mean()))):
        pp = np.clip(pp, 1e-9, 1 - 1e-9)
        out.append({"model": name, "n": int(m.sum()),
                    "logloss": float(-np.mean(np.where(o, np.log(pp), np.log(1 - pp)))),
                    "brier": float(np.mean((pp - o) ** 2))})
    return pd.DataFrame(out)


def ucl_metrics(df, cfg):
    u = df[(df.comp == "UCL") & df.ep_ph.notna() & df.season.isin(cfg["backtest"]["test_seasons"])]
    y = outcome_idx(u)
    tr = df[(df.comp == "UCL") & df.season.isin(range(2011, min(cfg["backtest"]["test_seasons"])))]
    base = np.bincount(outcome_idx(tr), minlength=3) / len(tr)
    P = u[["ep_ph", "ep_pd", "ep_pa"]].values
    rows = [{"model": "elo_poisson", "n": len(u), "logloss": logloss(P, y), "brier": brier(P, y), "rps": rps(P, y)},
            {"model": "base_rate(UCL 2011-17)", "n": len(u), "logloss": logloss(np.tile(base, (len(u), 1)), y),
             "brier": brier(np.tile(base, (len(u), 1)), y), "rps": rps(np.tile(base, (len(u), 1)), y)}]
    return pd.DataFrame(rows)


def run_backtest(base, cfg, manifest, cache=None):
    out = p(cfg, "outputs")
    out.mkdir(exist_ok=True, parents=True)
    df = build_forecasts(base, cfg, cache)
    dom, y, ens_info = eval_models(df, cfg)
    test = dom.season.isin(cfg["backtest"]["test_seasons"]).values
    val = dom.season.isin(cfg["backtest"]["validation_seasons"]).values
    dom = add_market_lambdas(dom, val | test)
    w_anchor, w_curve = choose_weight(dom, y, val)
    ok = dom.mkt_lh.notna().values
    eh, ea = blend_eta(dom.dc_eta_h.values[ok], dom.dc_eta_a.values[ok], dom.mkt_lh.values[ok], dom.mkt_la.values[ok], w_anchor)
    Mb = score_matrix(np.exp(eh), np.exp(ea), dom.dc_rho.values[ok][:, None, None])
    Pb = mk.p1x2(Mb)
    for k, c in enumerate(("anch_ph", "anch_pd", "anch_pa")):
        dom[c] = np.nan
        dom.loc[ok, c] = Pb[:, k]
    dom["anch_po25"] = np.nan
    dom.loc[ok, "anch_po25"] = mk.p_over(Mb, 2.5)
    base_rate = np.bincount(y[dom.season.values < min(cfg["backtest"]["test_seasons"])], minlength=3)
    base_rate = base_rate / base_rate.sum()
    dom["base_ph"], dom["base_pd"], dom["base_pa"] = base_rate
    dom["uniform_ph"] = dom["uniform_pd"] = dom["uniform_pa"] = 1 / 3
    names = ["uniform", "base"] + MODELS + ["ens", "anch", "mkt", "mkt_only", "mkt_plus"]
    pm = prob_metrics(dom, y, test, names)
    pm_league = pd.concat([prob_metrics(dom, y, test & (dom.comp == c).values, ["dc", "ens", "anch", "mkt"]).assign(league=c)
                           for c in cfg["leagues"]])
    cal = calibration(dom, y, test, ["dc", "ens", "anch", "mkt"])
    tot = totals_metrics(dom, test)
    ucl = ucl_metrics(df, cfg)
    strategies = {}
    for label, model, wt in (("anchored", "anch", w_anchor), ("raw_model", ens_info["bet_model"], None),
                             ("market_residual", "mkt_plus", None)):
        bets = simulate_bets(dom, test, cfg, model, "b365", w=wt)
        bets["odds_band"] = odds_band(bets.odds)
        bank = bankroll_path(bets, cfg)
        summ = {
            "overall": bet_summary(bets),
            "by_market": bet_summary(bets, "market"),
            "by_league": bet_summary(bets, "comp"),
            "by_season": bet_summary(bets, "season"),
            "by_odds_band": bet_summary(bets, "odds_band"),
            "by_market_league": bet_summary(bets, ["market", "comp"]),
        }
        bmax = simulate_bets(dom, test & dom.max_h.notna().values, cfg, model, "max", w=wt)
        summ["best_price_1x2_overall"] = bet_summary(bmax) if len(bmax) else pd.DataFrame()
        strategies[label] = {"bets": bets, "bank": bank, "summ": summ}
    pm.to_csv(out / "prob_metrics_test.csv", index=False)
    pm_league.to_csv(out / "prob_metrics_by_league.csv", index=False)
    cal.to_csv(out / "calibration.csv", index=False)
    tot.to_csv(out / "totals_metrics.csv", index=False)
    ucl.to_csv(out / "ucl_metrics.csv", index=False)
    bank_meta = {}
    for label, st in strategies.items():
        st["bets"].to_csv(out / f"backtest_bets_{label}.csv", index=False)
        st["bank"].to_csv(out / f"backtest_bankroll_{label}.csv", index=False)
        for k, v in st["summ"].items():
            v.to_csv(out / f"bets_{label}_{k}.csv", index=False)
        bk = st["bank"].bankroll
        bank_meta[label] = {"final": float(bk.iloc[-1]) if len(bk) else None,
                            "min": float(bk.min()) if len(bk) else None,
                            "max_drawdown_pct": float(np.max(1 - bk / bk.cummax())) if len(bk) else None}
    pd.DataFrame(w_curve, columns=["w_model", "val_logloss_1x2", "val_logloss_ou25", "val_sum"]).to_csv(
        out / "anchor_weight_validation.csv", index=False)
    meta = {"ensemble": ens_info, "anchor_weight_model": w_anchor, "bankroll": bank_meta,
            "n_test_matches": int(test.sum()), "config_hash": cfg["_hash"], "model_version": cfg["model_version"],
            "data_manifest": manifest}
    json.dump(meta, open(out / "backtest_meta.json", "w"), indent=2, default=str)
    pickle.dump({"dom": dom, "ens": ens_info, "w_anchor": w_anchor}, open(out / "backtest_frames.pkl", "wb"))
    return {"pm": pm, "pm_league": pm_league, "cal": cal, "tot": tot, "ucl": ucl, "strategies": strategies,
            "meta": meta, "dom": dom}

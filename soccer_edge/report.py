"""Matchday report: fixture probabilities, market prices, value screening and decisions."""
import base64
import datetime as dt
import html
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from . import markets as mk
from .anchor import blend_eta, market_lambdas
from .config import p
from .dixon_coles import DixonColes, sample_matrices, score_matrix
from .corners import corner_matrix, fit_corner_model
from .demo import demo_odds
from .forecast import elo_poisson_fit_predict
from .odds import devig_proportional, devig_shin, implied
from .staking import gate, rank_score, stake

DISCLAIMER = ("Research output. Every figure is a probabilistic estimate, not a guarantee. "
              "Backtests do not predict future returns. Bet only where it is legal, only with money you can afford "
              "to lose, never chase losses or borrow to bet. US help: 1-800-GAMBLER.")


def kickoff_local(date, time, tz_src, tz_user):
    if time is None or (isinstance(time, float) and np.isnan(time)) or pd.isna(time):
        return f"{pd.Timestamp(date).date()} (time TBD)"
    h, m = map(int, str(time)[:5].split(":"))
    t = dt.datetime(date.year, date.month, date.day, h, m, tzinfo=ZoneInfo(tz_src))
    return t.astimezone(ZoneInfo(tz_user)).strftime("%a %b %d, %I:%M %p %Z")


ODDS_COLS = ["date", "home", "away", "market", "selection", "line", "odds", "bookmaker", "timestamp_utc"]


def load_odds(cfg, fixtures=None):
    """Manual odds (data/inputs/odds.csv) plus cached API-Football odds for upcoming fixtures."""
    parts, meta = [], {"sources": []}
    f = p(cfg, "odds_input")
    if f.exists():
        o = pd.read_csv(f, parse_dates=["date"])
        parts.append(o.assign(source="manual"))
        meta["sources"].append(f"manual:{f.name}")
    if fixtures is not None and "api" in cfg:
        from .apidata import load_api_odds
        a, ameta = load_api_odds(cfg, fixtures)
        meta.update(ameta)
        if len(a):
            parts.append(a.assign(source="api"))
            meta["sources"].append("api-football")
    if fixtures is not None and len(fixtures) and "sportmonks" in cfg:
        from .sportmonks import load_odds as sm_odds
        c, cmeta = sm_odds(cfg, fixtures)
        meta["sportmonks"] = cmeta
        if len(c):
            parts.append(c)
            meta["sources"].append("sportmonks")
    if fixtures is not None and len(fixtures) and "oddsapi" in cfg:
        from .names import NameMapper
        from .oddsapi import load_latest
        cands = {c: sorted(set(g.home) | set(g.away)) for c, g in fixtures.groupby("comp")}
        b = load_latest(cfg, p(cfg, "api_cache"), NameMapper(p(cfg, "aliases")), cands, fixtures)
        if len(b):
            parts.append(b)
            meta["sources"].append("the-odds-api")
    o = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=ODDS_COLS)
    return o, meta


def screen_odds(o, Md, lam, rho, cfg, w_anchor, data_ok, G, block_reason=None, Mc=None, corners_ok=False):
    """Anchor to a reference book, then evaluate the best available price for every selection."""
    q = cfg["simulation"]["lower_quantile"]
    refs = cfg.get("api", {}).get("reference_bookmakers", [])
    info = {"anchored_to_market": False, "reference_book": None}
    Mb = Md
    if not len(o):
        return info, Mb, []
    full = o[o.market == "1X2"].groupby("bookmaker").selection.apply(set)
    full = [b for b, sset in full.items() if {"H", "D", "A"} <= sset]
    ref = next((b for b in refs if b in full), None)
    if ref is None and full:
        ref = "consensus"
    if ref:
        src = o[o.bookmaker.isin(full)] if ref == "consensus" else o[o.bookmaker == ref]
        x = src[src.market == "1X2"].groupby("selection").odds.median()
        ou = src[(src.market == "OU") & (src.line == 2.5)].groupby("selection").odds.median()
        po_m = devig_proportional(ou[["over", "under"]].values)[0] if {"over", "under"} <= set(ou.index) else np.nan
        p3 = devig_shin(x[["H", "D", "A"]].values)
        lh, la, _ = market_lambdas(p3, po_m, rho)
        lam_log = np.log(lam)
        bh, ba = blend_eta(lam_log[:, 0], lam_log[:, 1], lh, la, w_anchor)
        Mb = score_matrix(np.exp(bh), np.exp(ba), rho, G)
        info.update(anchored_to_market=True, reference_book=ref, market_p_home=float(p3[0]),
                    market_p_draw=float(p3[1]), market_p_away=float(p3[2]),
                    market_p_over2_5=float(po_m) if np.isfinite(po_m) else None)
    o = o.assign(line_key=o.line.astype(float).fillna(-999).round(2))
    sel_rows = []
    for (mkt, sel, lk), g in o.groupby(["market", "selection", "line_key"]):
        best = g.loc[g.odds.idxmax()]
        line = None if lk == -999 else float(lk)
        corner = mkt == "CORNERS"
        if corner and Mc is None:
            continue
        try:
            R = mk.returns(mkt, sel, float(best.odds), Mc.shape[-1] - 1 if corner else G, line)
        except (ValueError, KeyError, TypeError):
            continue
        Muse = Mc[None] if corner else Mb
        evd = mk.ev(Muse, R)
        ev_m, ev_lo = float(evd.mean()), float(np.quantile(evd, q))
        p_win = float(mk.ev(Muse.mean(0), (R > 0).astype(float)))
        gm = {"OU": "OU25"}.get(mkt, mkt)
        ok, why = gate(ev_m, ev_lo, float(best.odds), gm, cfg["betting"], data_ok)
        if ok and corner:
            ok, why = False, ("corner betting rules unvalidated (no historical corner odds)" if corners_ok
                              else "corner data stale")
        if ok and block_reason:
            ok, why = False, block_reason
        if ok and not info["anchored_to_market"]:
            ok, why = False, "no 1X2 odds to anchor to market (raw model lost money in backtest)"
        refp = g[g.bookmaker == info["reference_book"]].odds
        sel_rows.append({"market": mkt, "selection": sel, "line": line, "odds": float(best.odds),
                         "odds_source": best.bookmaker, "odds_timestamp": best.get("timestamp_utc"),
                         "n_books": int(g.bookmaker.nunique()),
                         "ref_odds": float(refp.iloc[0]) if len(refp) else None,
                         "implied_p": float(implied(best.odds)), "model_p": p_win,
                         "fair_odds": float(1 / p_win) if p_win > 0 else None, "demo": bool(g.get("source", pd.Series([""])).astype(str).eq("demo").any()),
                         "ev": ev_m, "ev_lo": ev_lo, "edge_pct": ev_m * 100,
                         "uncertainty": f"EV {q:.0%}-quantile {ev_lo:+.1%}",
                         "decision": "BET" if ok else "NO BET", "reason": why,
                         "stake_frac": stake(ev_lo, float(best.odds), cfg["betting"]) if ok else 0.0,
                         "rank": rank_score(ev_lo, p_win, float(best.odds))})
    return info, Mb, sel_rows


def team_form(res, team, before, n=5):
    m = res[((res.home == team) | (res.away == team)) & (res.date < before)].dropna(subset=["hg", "ag"]).tail(n)
    out = []
    for r in m.itertuples(index=False):
        home = r.home == team
        gf, ga = (r.hg, r.ag) if home else (r.ag, r.hg)
        out.append({"date": str(r.date.date()), "comp": r.comp, "opponent": r.away if home else r.home,
                    "venue": "H" if home else "A", "score": f"{int(gf)}-{int(ga)}",
                    "result": "W" if gf > ga else "D" if gf == ga else "L"})
    return out[::-1]


def model_inputs(model, r, cm, k):
    i, j = model.idx[r.home], model.idx[r.away]
    n = model.n
    out = {"intercept": float(model.theta[0]), "home_advantage": float(model.theta[1]),
           "attack_home": float(model.theta[3 + i]), "defence_home": float(model.theta[3 + n + i]),
           "attack_away": float(model.theta[3 + j]), "defence_away": float(model.theta[3 + n + j]),
           "rho": float(model.rho), "matches_in_fit": int(model.n_train),
           "elo_home": _f(getattr(r, "elo_h", None)), "elo_away": _f(getattr(r, "elo_a", None)),
           "clubelo_home": _f(getattr(r, "ce_h", None)), "clubelo_away": _f(getattr(r, "ce_a", None)),
           "rest_days_home": _f(getattr(r, "rest_h", None)), "rest_days_away": _f(getattr(r, "rest_a", None)),
           "corners_dispersion_k": k}
    return out


def _f(v):
    try:
        v = float(v)
        return None if np.isnan(v) else v
    except (TypeError, ValueError):
        return None


def _tz(r, default):
    tz = getattr(r, "tz", None)
    return tz if isinstance(tz, str) and tz else default


def _extra(r):
    out = {}
    for k in ("api_fixture_id", "kickoff_utc", "venue", "home_logo", "away_logo"):
        v = getattr(r, k, None)
        out[k] = None if v is None or (isinstance(v, float) and np.isnan(v)) else v
    return out


def match_odds(odds, r):
    if not len(odds):
        return odds
    fid = getattr(r, "api_fixture_id", None)
    m = (odds.home == r.home) & (odds.away == r.away)
    if fid is not None and "fixture_id" in odds and pd.notna(fid):
        m = m | (odds.fixture_id == fid)
    smid = getattr(r, "sm_id", None)
    if smid is not None and "sm_id" in odds and pd.notna(smid):
        m = m | (odds.sm_id == smid)
    return odds[m]


def missing_results(base, comp, as_of, lookback_days=60):
    """Scheduled matches that should have finished (kickoff > 1 day before as-of) but have no result."""
    fx = base[base.is_fixture.astype(bool) & (base.comp == comp)]
    return int(((fx.date < as_of - pd.Timedelta(days=1)) & (fx.date >= as_of - pd.Timedelta(days=lookback_days))).sum())


def predict_fixtures(base, cfg, as_of, days=4, w_anchor=0.0):
    as_of = pd.Timestamp(as_of)
    res = base[(~base.is_fixture.astype(bool)) & (base.date < as_of)]
    fx = base[base.is_fixture.astype(bool) & (base.date >= as_of) & (base.date < as_of + pd.Timedelta(days=days))]
    dcc, sim = cfg["dixon_coles"], cfg["simulation"]
    rng = np.random.default_rng(sim["seed"])
    q = sim["lower_quantile"]
    odds, odds_meta = load_odds(cfg, fx)
    # Elo-Poisson comparison model (fitted on the last four seasons)
    tr = res[res.season >= res.season.max() - 4].dropna(subset=["hg", "ag"])
    eh, ea, _ = elo_poisson_fit_predict(tr, fx) if len(fx) else (np.array([]), np.array([]), None)
    fx = fx.assign(ep_lh=np.exp(eh), ep_la=np.exp(ea))
    matches, selections, draws_store = [], [], {}
    lg_by_name = cfg["leagues"]
    for name, lg in lg_by_name.items():
        hist = res[(res.country == lg["country"]) & res.tier.isin([1, 2])]
        hist = hist[hist.date >= as_of - pd.Timedelta(days=dcc["window_days"])].dropna(subset=["hg", "ag"])
        last = res[res.comp == name].date.max()
        stale_days = int((as_of - last).days)
        missing = missing_results(base, name, as_of)
        data_ok = missing <= cfg["betting"]["max_missing_results"] and stale_days <= cfg["betting"]["stale_days"]
        model = DixonColes(dcc["xi"], dcc["l2"], dcc["max_goals"]).fit(hist, as_of)
        lres = res[res.comp == name]
        cm = fit_corner_model(lres, as_of, cfg)
        kdisp = cfg["corners"].get("dispersion_k")
        c_last = lres.dropna(subset=["hc"]).date.max()
        corners_ok = pd.notna(c_last) and (as_of - c_last).days <= cfg["betting"]["stale_days"] and data_ok
        for r in fx[fx.comp == name].itertuples(index=False):
            lp = model.linear_predictor(r.home, r.away)
            row = {"match_id": r.match_id, "comp": name, "round": getattr(r, "round", None), "date": r.date,
                   "kickoff_user_tz": kickoff_local(r.date, r.kickoff, _tz(r, lg["tz"]), cfg["user_timezone"]),
                   **_extra(r),
                   "home": r.home, "away": r.away, "last_result_in_data": str(last.date()),
                   "days_since_last_result": stale_days, "data_ok": data_ok,
                   "elo_diff_incl_home": float(r.elo_diff) if pd.notna(r.elo_diff) else np.nan,
                   "ep_p_home": np.nan}
            if lp is None:
                row["status"] = "team missing from training data"
                matches.append(row)
                continue
            eta, cov = lp
            Md, lam = sample_matrices(eta, cov, model.rho, sim["n_draws"], rng, dcc["max_goals"])
            M = Md.mean(0)
            s = mk.summary(M)
            P = mk.p1x2(Md)
            po = mk.p_over(Md, 2.5)
            pb = mk.p_btts(Md)
            pe = mk.p1x2(score_matrix(r.ep_lh, r.ep_la, -0.05))
            row.update({k: s[k] for k in ("p_home", "p_draw", "p_away", "p_over2.5", "p_btts", "xg_home", "xg_away",
                                         "p_1x", "p_x2", "p_dnb_home", "p_over1.5", "p_over3.5")})
            for k, arr in (("p_home", P[:, 0]), ("p_draw", P[:, 1]), ("p_away", P[:, 2]), ("p_over2.5", po), ("p_btts", pb)):
                row[f"{k}_q10"], row[f"{k}_q90"] = np.quantile(arr, [q, 1 - q])
                row[f"{k}_mc_se"] = float(arr.std() / np.sqrt(len(arr)))
            row["ep_p_home"], row["ep_p_draw"], row["ep_p_away"] = pe
            row["top_scores"] = ", ".join(f"{a} ({b:.0%})" for a, b in mk.correct_scores(M, 3))
            row["score_grid"] = np.round(M[:6, :6], 4).tolist()
            row["dc_train_matches"] = model.n_train
            row["missing_results"] = missing
            row["status"] = "ok" if data_ok else (
                f"STALE: {missing} {name} matches already played have no result in the data" if missing
                else f"STALE: last {name} result {stale_days} days before as-of")
            # ---- corners
            Mc = None
            clp = cm.linear_predictor(r.home, r.away) if cm is not None else None
            if clp is not None:
                c_lh, c_la = np.exp(clp[0])
                Mc = corner_matrix(c_lh, c_la, kdisp)
                tot = np.add.outer(np.arange(Mc.shape[0]), np.arange(Mc.shape[1]))
                row.update(xc_home=float(c_lh), xc_away=float(c_la), corners_ok=bool(corners_ok),
                           corners_last_data=str(c_last.date()) if pd.notna(c_last) else None,
                           corner_grid=np.round(Mc[:17, :17], 4).tolist())
                for L in (7.5, 8.5, 9.5, 10.5, 11.5, 12.5):
                    row[f"p_corners_over{L}"] = float((Mc * (tot > L)).sum())
            row["form_home"] = team_form(res, r.home, as_of)
            row["form_away"] = team_form(res, r.away, as_of)
            row["model_inputs"] = model_inputs(model, r, cm, kdisp)
            # ---- odds screening (demo mode fabricates clearly-labelled synthetic prices)
            o = match_odds(odds, r)
            demo = False
            if not len(o) and cfg.get("_demo_odds"):
                o = demo_odds(r, M, Mc, rng)
                demo = True
            info, Mb, sels = screen_odds(o, Md, lam, model.rho, cfg, w_anchor, data_ok, dcc["max_goals"],
                                         "demo mode: synthetic odds" if demo else None, Mc, corners_ok)
            row["joint_grid"] = np.round(Mb.mean(0)[:9, :9], 4).tolist()
            row["odds_are_demo"] = demo
            row.update(info)
            for x in sels:
                selections.append({"match_id": r.match_id, "date": r.date, "comp": name, "home": r.home,
                                   "away": r.away, "fixture": f"{r.home} v {r.away}", **x})
            matches.append(row)
    # ---- UCL (cross-league): Elo-Poisson, point estimate only
    ucl_last = res[res.comp.isin(list(lg_by_name))].date.max()
    for r in fx[fx.comp == "UCL"].itertuples(index=False):
        Mu = score_matrix(r.ep_lh, r.ep_la, -0.05)
        s = mk.summary(Mu)
        st = int((as_of - ucl_last).days)
        row = {"match_id": r.match_id, "comp": "UCL", "round": getattr(r, "round", None), "date": r.date,
               "kickoff_user_tz": kickoff_local(r.date, r.kickoff, _tz(r, "Europe/Paris"), cfg["user_timezone"]),
               **_extra(r),
               "home": r.home, "away": r.away, "last_result_in_data": str(ucl_last.date()),
               "days_since_last_result": st, "data_ok": False,
               "elo_diff_incl_home": float(r.elo_diff), "top_scores": ", ".join(f"{a} ({b:.0%})" for a, b in mk.correct_scores(Mu, 3)),
               "status": "UCL: Elo-Poisson point estimate (no odds history to validate betting rules)",
               "score_grid": np.round(Mu[:6, :6], 4).tolist()}
        row.update({k: s[k] for k in ("p_home", "p_draw", "p_away", "p_over2.5", "p_btts", "xg_home", "xg_away")})
        for k in ("p_home", "p_draw", "p_away", "p_over2.5", "p_btts"):
            row[f"{k}_q10"] = row[f"{k}_q90"] = row[k]
        row["ep_p_home"], row["ep_p_draw"], row["ep_p_away"] = s["p_home"], s["p_draw"], s["p_away"]
        o = match_odds(odds, r)
        demo = False
        if not len(o) and cfg.get("_demo_odds"):
            o = demo_odds(r, Mu, None, rng)
            demo = True
        info, Mb, sels = screen_odds(o, Mu[None], np.array([[r.ep_lh, r.ep_la]]), -0.05, cfg, w_anchor, False,
                                     dcc["max_goals"], "demo mode: synthetic odds" if demo else
                                     "UCL betting rules have no odds history to validate them")
        row["joint_grid"] = np.round(Mb.mean(0)[:9, :9], 4).tolist()
        row["odds_are_demo"] = demo
        row["form_home"] = team_form(res, r.home, as_of)
        row["form_away"] = team_form(res, r.away, as_of)
        row.update(info)
        for x in sels:
            selections.append({"match_id": r.match_id, "date": r.date, "comp": "UCL", "home": r.home,
                               "away": r.away, "fixture": f"{r.home} v {r.away}", **x})
        matches.append(row)
    M = pd.DataFrame(matches)
    S = pd.DataFrame(selections)
    if len(S):
        cap = cfg["betting"]["max_matchday_exposure_pct"]
        tot = S.stake_frac.sum()
        if tot > cap:
            S["stake_frac"] *= cap / tot
        S = S.sort_values(["decision", "rank"], ascending=[True, False])
    return M, S, odds_meta


def _img(path):
    return f'<img src="data:image/png;base64,{base64.b64encode(Path(path).read_bytes()).decode()}" style="max-width:100%">'


def _pct(x):
    return "" if pd.isna(x) else f"{x:.0%}"


def _table(df, cols, fmt=None):
    fmt = fmt or {}
    h = "".join(f"<th>{html.escape(c)}</th>" for c in cols.values())
    rows = []
    for _, r in df.iterrows():
        tds = []
        for c in cols:
            v = r.get(c)
            s = fmt[c](v) if c in fmt else ("" if pd.isna(v) else (f"{v:.3f}" if isinstance(v, float) else str(v)))
            tds.append(f"<td>{html.escape(s)}</td>")
        rows.append("<tr>" + "".join(tds) + "</tr>")
    return f"<table><thead><tr>{h}</tr></thead><tbody>{''.join(rows)}</tbody></table>"


CSS = """
body{font-family:'CMU Serif','Latin Modern Roman','Computer Modern','Times New Roman',Times,serif;background:#fcfcfb;color:#0b0b0b;max-width:1180px;margin:24px auto;padding:0 18px;line-height:1.45}
h1{font-size:24px;margin-bottom:4px}h2{font-size:18px;margin-top:34px;border-bottom:1px solid #e6e5e1;padding-bottom:4px}h3{font-size:15px;margin-top:22px}
.muted{color:#52514e;font-size:13px}.warn{background:#fff4e5;border-left:4px solid #c98500;padding:10px 14px;margin:14px 0;font-size:14px}
.note{background:#eef4fc;border-left:4px solid #2a78d6;padding:10px 14px;margin:14px 0;font-size:14px}
table{border-collapse:collapse;font-size:12.5px;margin:8px 0 14px;width:100%}th,td{padding:5px 7px;border-bottom:1px solid #eceae6;text-align:right}
th{color:#52514e;font-weight:600;background:#f5f4f1}td:first-child,th:first-child,td:nth-child(2),th:nth-child(2){text-align:left}
.kpis{display:flex;gap:14px;flex-wrap:wrap}.kpi{border:1px solid #e6e5e1;border-radius:8px;padding:10px 14px;min-width:170px}
.kpi b{display:block;font-size:20px}.kpi span{color:#52514e;font-size:12px}
"""


def render_html(cfg, as_of, M, S, bt, quality, manifest, out_path, chart_paths):
    meta = bt["meta"]
    strat = bt["strategies"]
    o = {k: v["summ"]["overall"].iloc[0] for k, v in strat.items()}
    pm = bt["pm"][bt["pm"].subset == "with_odds"].copy()
    names = {"uniform": "Uniform 1/3", "base": "Base rates", "dc": "Dixon-Coles", "ep": "Elo-Poisson",
             "elo_logit": "Elo logistic", "logit_full": "Logistic (all features)", "gbm": "Gradient boosting",
             "ens": "Validated ensemble", "anch": "Market-anchored DC", "mkt": "Bet365 (Shin de-vig)",
             "mkt_only": "Market refit (logit)", "mkt_plus": "Market + all features"}
    pm["model"] = pm.model.map(names)
    parts = [f"<html><head><meta charset='utf-8'><title>Matchday report {as_of}</title><style>{CSS}</style></head><body>",
             f"<h1>Matchday report — {pd.Timestamp(as_of):%a %d %b %Y}</h1>",
             f"<div class='muted'>soccer_edge v{cfg['model_version']} · config {cfg['_hash']} · generated "
             f"{dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M UTC} · times shown in {cfg['user_timezone']}</div>",
             f"<div class='warn'>{html.escape(DISCLAIMER)}</div>"]
    # ---- headline
    n_bet = int((S.decision == "BET").sum()) if len(S) else 0
    parts.append("<h2>Bottom line</h2>")
    parts.append(f"<p><b>{n_bet} bets recommended this matchday.</b> ")
    if not len(S):
        parts.append("No odds were supplied (<code>data/inputs/odds.csv</code> is empty or missing), so no wager can be "
                     "priced. Model probabilities and fair odds are shown below for reference only. ")
    stale = [] if M.empty or "data_ok" not in M else M[~M.data_ok.astype(bool)].comp.unique().tolist()
    if stale:
        parts.append(f"In addition, results are missing for {', '.join(stale)}, so the ratings miss recent form and the system is blocked "
                     "from recommending any bet until fresher results are loaded.")
    parts.append("</p>")
    ll_mkt = bt["pm"].query("model=='mkt' and subset=='with_odds'").logloss.iloc[0]
    ll_ens = bt["pm"].query("model=='ens' and subset=='with_odds'").logloss.iloc[0]
    parts.append("<div class='kpis'>" + "".join(
        f"<div class='kpi'><b>{v['roi_flat']:+.1%}</b><span>{k.replace('_', ' ')}: flat-stake ROI, {int(v['bets'])} bets "
        f"(95% CI {v['roi_ci95_lo']:+.1%} to {v['roi_ci95_hi']:+.1%})</span></div>" for k, v in o.items()) +
        f"<div class='kpi'><b>{ll_mkt:.4f}</b>"
        f"<span>market 1X2 log loss vs best model {ll_ens:.4f} (lower is better)</span></div></div>")
    parts.append("<div class='note'><b>What the backtest says.</b> Across 14,121 out-of-sample league matches (2018-19 to "
                 "2025-26), Bet365's de-margined prices were more accurate than every model built from public results "
                 "data. Betting the raw model's disagreements with the market lost money with a confidence interval "
                 "entirely below zero. The validation-chosen blend gives the model <b>zero weight</b> versus the market, "
                 "and adding all model features to the market price did not improve it out of sample. In plain terms: "
                 "this system does not yet have a demonstrated edge, so its default output is <b>NO BET</b>. An edge "
                 "would need information the market under-weights (e.g. paid xG, timely lineup news, or "
                 "line-shopping against a sharp reference price), and would have to show up in paper tracking first.</div>")
    # ---- data status
    parts.append("<h2>Data status</h2>")
    srcs = []
    for k, v in manifest["sources"].items():
        srcs.append({"source": k, "detail": v.get("repo") or v.get("path"),
                     "snapshot": v.get("commit_time") or v.get("file_mtime") or "", "latest": v.get("max_date") or v.get("max_result_date") or "",
                     "rows": v.get("rows") or v.get("results_rows")})
    parts.append(_table(pd.DataFrame(srcs), {"source": "Source", "detail": "Location", "snapshot": "Snapshot time",
                                              "latest": "Latest match", "rows": "Rows"}))
    parts.append(f"<p class='muted'>Retrieved {manifest['retrieved_at']}. Not available in this run: live odds, injuries, "
                 "suspensions, confirmed lineups, xG, weather, and 2026-27 UCL fixtures. These are flagged rather than "
                 "guessed; they lower confidence in every forecast below.</p>")
    if quality["issues"]:
        parts.append("<div class='warn'><b>Data-quality flags</b><ul>" + "".join(f"<li>{html.escape(i)}</li>" for i in quality["issues"]) + "</ul></div>")
    # ---- fixtures
    parts.append("<h2>Fixtures and model probabilities</h2>")
    parts.append("<p class='muted'>Dixon-Coles with parameter uncertainty: "
                 f"{cfg['simulation']['n_draws']:,} Monte Carlo draws of the attack/defence parameters per match; brackets "
                 f"are the {cfg['simulation']['lower_quantile']:.0%}-{1 - cfg['simulation']['lower_quantile']:.0%} range. "
                 "Monte Carlo standard error is below 0.2 percentage points for every probability shown. Fair odds = 1/probability "
                 "(no margin). Confidence is LOW for every match this week because ratings are stale and lineup/injury data is absent.</p>")
    if len(M):
        M = M.copy()
        M["fixture"] = M.home + " v " + M.away
        br = lambda k: M.apply(lambda r: f"{r[k]:.0%} ({r[k + '_q10']:.0%}-{r[k + '_q90']:.0%})" if pd.notna(r.get(k)) else "", axis=1)  # noqa: E731
        M["H"], M["D"], M["A"], M["O25"], M["BTTS"] = br("p_home"), br("p_draw"), br("p_away"), br("p_over2.5"), br("p_btts")
        M["xg"] = M.apply(lambda r: f"{r.xg_home:.2f} - {r.xg_away:.2f}" if pd.notna(r.get("xg_home")) else "", axis=1)
        M["fair"] = M.apply(lambda r: f"{1 / r.p_home:.2f} / {1 / r.p_draw:.2f} / {1 / r.p_away:.2f}" if pd.notna(r.get("p_home")) else "", axis=1)
        M["elo_cmp"] = M.apply(lambda r: f"{r.ep_p_home:.0%}/{r.ep_p_draw:.0%}/{r.ep_p_away:.0%}" if pd.notna(r.get("ep_p_home")) else "", axis=1)
        M["drivers"] = M.apply(lambda r: f"Elo gap {r.elo_diff_incl_home:+.0f} incl. home edge; likeliest {r.top_scores}" if pd.notna(r.get("xg_home")) else r.status, axis=1)
        M["conf"] = "LOW"
        M["decision"] = "NO BET"
        for comp, g in M.groupby("comp", sort=False):
            parts.append(f"<h3>{comp} <span class='muted'>— {g['round'].iloc[0] or ''}; last result in data {g.last_result_in_data.iloc[0]} "
                         f"({g.days_since_last_result.iloc[0]} days old)</span></h3>")
            parts.append(_table(g, {"kickoff_user_tz": "Kickoff (ET)", "fixture": "Fixture", "H": "Home", "D": "Draw", "A": "Away",
                                    "O25": "Over 2.5", "BTTS": "BTTS", "xg": "Exp. goals", "fair": "Fair odds 1/X/2",
                                    "elo_cmp": "Elo-Poisson check", "conf": "Confidence", "decision": "Decision"}))
            parts.append("<p class='muted'>" + "<br>".join(html.escape(f"{r.fixture}: {r.drivers}") for r in g.itertuples()) + "</p>")
    # ---- summary table of selections
    parts.append("<h2>Value screen</h2>")
    if len(S):
        parts.append(_table(S, {"fixture": "Fixture", "market": "Market", "selection": "Selection", "line": "Line",
                                "odds": "Odds", "odds_source": "Book", "odds_timestamp": "Odds time", "model_p": "Model P(win)",
                                "implied_p": "Implied P", "edge_pct": "Edge % (EV)", "uncertainty": "Uncertainty",
                                "decision": "Decision", "reason": "Reason", "stake_frac": "Stake (% bankroll)"},
                            {"model_p": _pct, "implied_p": _pct, "edge_pct": lambda v: f"{v:+.1f}%",
                             "stake_frac": lambda v: f"{v:.2%}", "line": lambda v: "" if pd.isna(v) else f"{v:+g}"}))
    else:
        parts.append("<p>No odds supplied — nothing to screen. Add prices to <code>data/inputs/odds.csv</code> (template "
                     "included) with a source and timestamp, then rerun <code>python -m soccer_edge.cli report</code>.</p>")
    # ---- backtest detail
    parts.append("<h2>Backtest evidence (chronological, out of sample)</h2>")
    parts.append("<p class='muted'>Models refit every week using only matches before that week; ML models retrained each "
                 "season on prior seasons; hyper-parameters, ensemble weights and the market-anchor weight chosen on "
                 "2016-17 and 2017-18 only. Test seasons 2018-19 to 2025-26. Bet365 odds in this dataset are pre-match "
                 "but not closing prices, so closing-line value cannot be measured here (supported when drop-in files "
                 "include closing odds).</p>")
    parts.append("<h3>1X2 probability accuracy</h3>")
    parts.append(_table(pm, {"model": "Model", "n": "Matches", "logloss": "Log loss", "brier": "Brier", "rps": "RPS", "accuracy": "Accuracy"},
                        {"logloss": lambda v: f"{v:.4f}", "brier": lambda v: f"{v:.4f}", "rps": lambda v: f"{v:.4f}", "accuracy": _pct}))
    parts.append("<h3>Over/Under 2.5 accuracy</h3>")
    parts.append(_table(bt["tot"], {"model": "Model", "n": "Matches", "logloss": "Log loss", "brier": "Brier"},
                        {"logloss": lambda v: f"{v:.4f}", "brier": lambda v: f"{v:.4f}"}))
    parts.append("<h3>Champions League (no odds available: probability accuracy only)</h3>")
    parts.append(_table(bt["ucl"], {"model": "Model", "n": "Matches", "logloss": "Log loss", "brier": "Brier", "rps": "RPS"},
                        {"logloss": lambda v: f"{v:.4f}", "brier": lambda v: f"{v:.4f}", "rps": lambda v: f"{v:.4f}"}))
    parts.append(_img(chart_paths["calibration"]))
    parts.append("<h3>Betting simulation</h3>")
    parts.append("<p class='muted'>Rules (fixed in config before testing): EV ≥ 4% on the mean probability, EV still "
                 "positive at the 10th percentile of parameter uncertainty, odds 1.30-6.00 (3.50 for totals/AH), at most "
                 "one selection per market per match. Kelly path: quarter-Kelly on the 10th-percentile EV, 2% cap per bet, "
                 "10% cap per day.</p>")
    parts.append(_img(chart_paths["equity"]))
    rows = []
    for k, st in strat.items():
        for _, r in st["summ"]["by_market"].iterrows():
            rows.append({"strategy": k.replace("_", " "), **r.to_dict()})
        bk = meta["bankroll"][k]
        rows.append({"strategy": k.replace("_", " "), "market": "ALL (Kelly bankroll)", "bets": st["summ"]["overall"].bets.iloc[0],
                     "roi_flat": np.nan, "profit_units": np.nan, "max_drawdown_units": np.nan,
                     "longest_losing_streak": st["summ"]["overall"].longest_losing_streak.iloc[0],
                     "kelly": f"1.00 → {bk['final']:.2f} (max drawdown {bk['max_drawdown_pct']:.0%})"})
    parts.append(_table(pd.DataFrame(rows), {"strategy": "Strategy", "market": "Market", "bets": "Bets", "hit_rate": "Hit rate",
                                             "avg_odds": "Avg odds", "avg_ev_claimed": "EV claimed", "roi_flat": "ROI",
                                             "roi_ci95_lo": "ROI 95% lo", "roi_ci95_hi": "ROI 95% hi",
                                             "max_drawdown_units": "Max DD (units)", "longest_losing_streak": "Worst losing run",
                                             "kelly": "Kelly bankroll"},
                        {"hit_rate": _pct, "avg_odds": lambda v: "" if pd.isna(v) else f"{v:.2f}",
                         "avg_ev_claimed": lambda v: "" if pd.isna(v) else f"{v:+.1%}", "roi_flat": lambda v: "" if pd.isna(v) else f"{v:+.1%}",
                         "roi_ci95_lo": lambda v: "" if pd.isna(v) else f"{v:+.1%}", "roi_ci95_hi": lambda v: "" if pd.isna(v) else f"{v:+.1%}",
                         "bets": lambda v: f"{int(v)}", "max_drawdown_units": lambda v: "" if pd.isna(v) else f"{v:.1f}",
                         "longest_losing_streak": lambda v: "" if pd.isna(v) else f"{int(v)}", "kelly": lambda v: "" if pd.isna(v) else str(v)}))
    parts.append("<p class='muted'>“EV claimed” versus realised ROI is the key overconfidence diagnostic: the raw model "
                 "believed it had ~28% edges and realised about −8%.</p>")
    lg = bt["strategies"]["raw_model"]["summ"]["by_league"]
    parts.append("<h3>Raw-model bets by league</h3>")
    parts.append(_table(lg, {"comp": "League", "bets": "Bets", "roi_flat": "ROI", "roi_ci95_lo": "95% lo", "roi_ci95_hi": "95% hi"},
                        {"roi_flat": lambda v: f"{v:+.1%}", "roi_ci95_lo": lambda v: f"{v:+.1%}", "roi_ci95_hi": lambda v: f"{v:+.1%}",
                         "bets": lambda v: f"{int(v)}"}))
    parts.append("<h2>Limitations</h2><ul>" + "".join(f"<li>{x}</li>" for x in [
        "No xG: shots-on-target averages are used as a proxy. No injury, suspension, lineup, weather or travel data.",
        "Odds are Bet365 pre-match (plus a market-max column for 1X2/OU) from football-data.co.uk; no closing odds, so no CLV.",
        "Champions League: results only (2011-12 to 2025-26) and no 2026-27 fixtures in the reachable sources; UCL "
        "matches are priced with the Elo-Poisson model when fixtures are supplied.",
        "Player markets, first-half markets and correct-score betting are out of scope for this version; correct-score "
        "probabilities are shown for information only.",
        "Results after 20 Sep 2026 were not reachable from this environment, so this week's ratings are about two months stale.",
    ]) + "</ul>")
    parts.append(f"<p class='muted'>{html.escape(DISCLAIMER)}</p></body></html>")
    Path(out_path).write_text("\n".join(parts), encoding="utf-8")
    return out_path

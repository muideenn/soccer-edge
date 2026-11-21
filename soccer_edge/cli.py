"""Command line entry point.

  python -m soccer_edge.cli sync      [--backfill 2024 2025]   # pull API-Football into data/api (budgeted)
  python -m soccer_edge.cli export    [--as-of YYYY-MM-DD]     # refit, price, paper-log, settle, write site JSON
  python -m soccer_edge.cli update                             # sync + export (what the scheduled workflow runs)
  python -m soccer_edge.cli backtest                           # full walk-forward evaluation (~6 min)
  python -m soccer_edge.cli report    [--as-of ...]            # standalone HTML report
  python -m soccer_edge.cli quality
"""
import argparse
import datetime as dt
import json
import pickle

import pandas as pd

from .env import load_dotenv

from . import charts
from .config import load_config, p


def _load(cfg):
    from .forecast import build_base
    from .ingest import Loader
    L = Loader(cfg)
    m, fx, ce = L.load_all()
    base, _ = build_base(m, fx, ce, cfg)
    return L, m, fx, base


def cmd_sync(cfg, backfill):
    import os

    from .apisports import ApiFootball, Sync
    from .env import soccer_key
    from .oddsapi import fetch as fetch_oddsapi
    a = cfg["api"]
    provider = os.environ.get("SOCCER_API_PROVIDER", a["provider"])
    st = {}
    if soccer_key():
        client = ApiFootball(provider, budget=a["run_budget"], per_minute=a["per_minute"])
        st = Sync(cfg, client, p(cfg, "api_cache")).run(backfill=backfill)
        print(json.dumps({k: v for k, v in st.items() if k != "request_log"}, indent=2))
    else:
        print("SOCCER_API_KEY not set: skipping API-Football sync")
    from .sportmonks import sync as sm_sync
    sst = sm_sync(cfg, p(cfg, "api_cache"))
    (p(cfg, "api_cache")).mkdir(parents=True, exist_ok=True)
    (p(cfg, "api_cache") / "sportmonks_status.json").write_text(json.dumps(sst, default=str))
    print(json.dumps({k: v for k, v in sst.items() if k != "steps"} | {"steps": sst["steps"][:8]}, indent=2, default=str))
    ost = fetch_oddsapi(cfg, p(cfg, "api_cache"))
    (p(cfg, "api_cache")).mkdir(parents=True, exist_ok=True)
    (p(cfg, "api_cache") / "oddsapi_status.json").write_text(json.dumps(ost))
    print(json.dumps(ost, indent=2))
    return st


def cmd_export(cfg, as_of, html=False):
    from .apidata import load_api_injuries
    from .export import export_all
    from .quality import check
    from .report import predict_fixtures, render_html
    from .tracking import log_predictions, settle
    out = p(cfg, "outputs")
    out.mkdir(parents=True, exist_ok=True)
    L, m, fx, base = _load(cfg)
    real_odds = any((p(cfg, "api_cache") / d).exists() and any((p(cfg, "api_cache") / d).glob("*.json"))
                    for d in ("odds/latest", "oddsapi/latest", "sportmonks/odds")) or p(cfg, "odds_input").exists()
    mode = cfg.get("demo_mode", "auto")
    cfg["_demo_odds"] = mode == "on" or (mode == "auto" and not real_odds)
    q = check(m, fx, cfg, as_of)
    bt = pickle.load(open(out / "backtest_results.pkl", "rb"))
    M, S, odds_meta = predict_fixtures(base, cfg, as_of, cfg["api"].get("odds_horizon_days", 4), bt["meta"]["anchor_weight_model"])
    rows = []
    if len(S):
        Mi = M.set_index("match_id")
        for r in S[~S.demo.astype(bool)].itertuples(index=False):  # synthetic demo prices are never paper-logged
            rows.append({"model_version": cfg["model_version"], "config_hash": cfg["_hash"],
                         "data_as_of": M.last_result_in_data.max(), "match_id": r.match_id, "date": r.date,
                         "comp": r.comp, "home": r.home, "away": r.away, "market": r.market, "selection": r.selection,
                         "line": r.line, "odds": r.odds, "odds_source": r.odds_source, "odds_timestamp": r.odds_timestamp,
                         "model_p": r.model_p, "ev": r.ev, "ev_lo": r.ev_lo, "decision": r.decision, "reason": r.reason,
                         "stake_frac": r.stake_frac, "api_fixture_id": Mi.loc[r.match_id].get("api_fixture_id"),
                         "kickoff_utc": Mi.loc[r.match_id].get("kickoff_utc")})
    log_predictions(rows, out / "paper_log.csv")
    settle(out / "paper_log.csv", base, p(cfg, "api_cache") / "odds" / "history",
           cfg["api"].get("reference_bookmakers", []))
    inj = load_api_injuries(cfg)
    demo = cfg["_demo_odds"] or not ({"api_football", "sportmonks"} & set(L.manifest["sources"]))
    site = export_all(cfg, as_of, M, S, odds_meta, bt, q, L.manifest, inj, L.team_map, demo)
    if html:
        tag = pd.Timestamp(as_of).strftime("%Y-%m-%d")
        render_html(cfg, as_of, M, S, bt, q, L.manifest, out / f"matchday_{tag}.html",
                    {"equity": out / "equity.png", "calibration": out / "calibration.png"})
    print(f"exported {len(M)} fixtures, {int((S.decision == 'BET').sum()) if len(S) else 0} bets -> {site}")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="soccer_edge")
    ap.add_argument("command", choices=["sync", "export", "update", "backtest", "report", "quality", "corners-eval", "check-env", "sportmonks-leagues"])
    ap.add_argument("--config")
    ap.add_argument("--as-of", default=str(dt.date.today()))
    ap.add_argument("--backfill", nargs="*", type=int, default=[])
    a = ap.parse_args(argv)
    load_dotenv()
    cfg = load_config(a.config)
    out = p(cfg, "outputs")
    out.mkdir(parents=True, exist_ok=True)
    if a.command == "sync":
        cmd_sync(cfg, a.backfill)
    elif a.command == "update":
        try:
            cmd_sync(cfg, a.backfill)
        except RuntimeError as e:  # missing key / network: still publish from cache, flagged as stale
            print(f"sync failed: {e}")
        cmd_export(cfg, a.as_of)
    elif a.command in ("export", "report"):
        cmd_export(cfg, a.as_of, html=a.command == "report")
    elif a.command == "check-env":
        from .env import odds_key, soccer_key
        print(f"SOCCER_API_KEY: {'set' if soccer_key() else 'missing (demo mode)'}")
        print(f"ODDS_API_KEY:   {'set' if odds_key() else 'missing (optional)'}")
        from .sportmonks import token as sm_token
        print(f"SPORTMONKS_API_TOKEN: {'set' if sm_token() else 'missing (optional)'}")
    elif a.command == "sportmonks-leagues":
        from .sportmonks import Sportmonks
        c = Sportmonks(budget=20)
        rows = c.get_all("football/leagues", include="country")
        want = cfg.get("sportmonks", {}).get("league_ids", {})
        print(f"{len(rows)} leagues in your subscription:")
        for x in sorted(rows, key=lambda x: str(x.get("name"))):
            tag = [k for k, v in want.items() if v == x.get("id")]
            print(f"  {x.get('id'):>6}  {x.get('name')}  ({(x.get('country') or {}).get('name', '')}){'  <- ' + tag[0] if tag else ''}")
        missing = [k for k, v in want.items() if v not in {x.get('id') for x in rows}]
        if missing:
            print(f"Not in your subscription (or different ids): {', '.join(missing)} -> edit sportmonks.league_ids in config.yaml")
    elif a.command == "corners-eval":
        from .corners import evaluate
        from .ingest import Loader
        m, _, _ = Loader(cfg).load_all()
        r = evaluate(cfg, m, out)
        print(json.dumps({k: v for k, v in r.items() if k != "calibration_over9_5"}, indent=2))
    elif a.command == "quality":
        from .quality import check
        L, m, fx, base = _load(cfg)
        print(json.dumps(check(m, fx, cfg, a.as_of), indent=2))
    elif a.command == "backtest":
        from .backtest import run_backtest
        L, m, fx, base = _load(cfg)
        R = run_backtest(base, cfg, L.manifest, cache=str(out / "forecast_cache.pkl"))
        R.pop("dom")
        pickle.dump(R, open(out / "backtest_results.pkl", "wb"))
        charts.equity(R["strategies"], out / "equity.png")
        charts.calibration(R["cal"], out / "calibration.png")
        print(R["pm"].to_string())


if __name__ == "__main__":
    main()

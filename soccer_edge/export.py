"""Publish model output as static JSON for the web app (no secrets, no raw API payloads)."""
import datetime as dt
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from .config import p
from .report import DISCLAIMER


def _clean(o):
    if isinstance(o, dict):
        return {str(k): _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating, float)):
        return None if not math.isfinite(float(o)) else round(float(o), 5)
    if isinstance(o, (pd.Timestamp, dt.date, dt.datetime)):
        return o.isoformat()
    if isinstance(o, np.bool_):
        return bool(o)
    if o is pd.NaT:
        return None
    return o


def _write(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_clean(obj), separators=(",", ":"), default=str))


def confidence(row, has_injuries):
    """Describes data completeness, not certainty of outcome."""
    if not row.get("data_ok"):
        return "LOW", "ratings stale: recent results missing from the data"
    if not row.get("anchored_to_market"):
        return "LOW", "no market odds to anchor to"
    if not has_injuries:
        return "MEDIUM", "injury list unavailable"
    return "MEDIUM", "fresh results and market odds; lineups not modelled"


def export_matchday(cfg, as_of, M, S, injuries, odds_meta, team_map):
    inj_by_fixture = {}
    if len(injuries):
        for fid, g in injuries.groupby("fixture_id"):
            inj_by_fixture[int(fid)] = g[["team", "player", "type", "reason"]].to_dict("records")
    fixtures = []
    for r in M.to_dict("records"):
        fid = r.get("api_fixture_id")
        inj = inj_by_fixture.get(int(fid), []) if fid is not None and pd.notna(fid) else []
        conf, why = confidence(r, bool(len(injuries)))
        sels = S[S.match_id == r["match_id"]].drop(columns=["date"], errors="ignore").to_dict("records") if len(S) else []
        fixtures.append({**{k: v for k, v in r.items() if k != "date"}, "date": str(pd.Timestamp(r["date"]).date()),
                         "confidence": conf, "confidence_reason": why, "injuries": inj,
                         "decision": "BET" if any(x["decision"] == "BET" for x in sels) else "NO BET",
                         "selections": sels})
    leagues = list(cfg["leagues"]) + ["UCL"]
    return {"as_of": str(as_of), "user_timezone": cfg["user_timezone"], "leagues": leagues,
            "n_fixtures": len(fixtures), "n_bets": int((S.decision == "BET").sum()) if len(S) else 0,
            "odds": odds_meta, "fixtures": fixtures}


def export_performance(cfg, bt):
    out = {"meta": {k: v for k, v in bt["meta"].items() if k != "data_manifest"},
           "prob_metrics": bt["pm"].to_dict("records"), "totals": bt["tot"].to_dict("records"),
           "ucl": bt["ucl"].to_dict("records"), "calibration": bt["cal"].to_dict("records"),
           "by_league_probs": bt["pm_league"].to_dict("records"), "strategies": {}}
    for k, st in bt["strategies"].items():
        b = st["bets"].sort_values("date")
        cum = np.cumsum(b.profit.values) if len(b) else np.array([])
        idx = np.unique(np.linspace(0, len(b) - 1, min(len(b), 400)).astype(int)) if len(b) else []
        out["strategies"][k] = {
            "summary": {kk: v.to_dict("records") for kk, v in st["summ"].items()},
            "equity": [{"date": str(pd.Timestamp(b.date.iloc[i]).date()), "units": float(cum[i]), "n": int(i + 1)} for i in idx],
            "bankroll": [{"date": str(pd.Timestamp(d).date()), "bankroll": float(v)} for d, v in
                         st["bank"].iloc[np.unique(np.linspace(0, len(st["bank"]) - 1, min(len(st["bank"]), 300)).astype(int))].values]
            if len(st["bank"]) else []}
    return out


def export_paper(path):
    path = Path(path)
    if not path.exists():
        return {"rows": [], "summary": {"logged": 0, "bets": 0, "settled_bets": 0}}
    log = pd.read_csv(path)
    bets = log[log.decision == "BET"]
    settled = bets.dropna(subset=["profit"])
    return {"rows": log.tail(500).to_dict("records"),
            "summary": {"logged": int(len(log)), "bets": int(len(bets)), "settled_bets": int(len(settled)),
                        "roi": float(settled.profit.mean()) if len(settled) else None,
                        "profit_units": float(settled.profit.sum()) if len(settled) else 0.0,
                        "clv_mean": float(settled.clv.mean()) if "clv" in settled and settled.clv.notna().any() else None}}


def export_all(cfg, as_of, M, S, odds_meta, bt, quality, manifest, injuries, team_map, demo):
    site = p(cfg, "site_data")
    cm = p(cfg, "outputs") / "corners_metrics.json"
    sync = p(cfg, "api_cache") / "sync_status.json"
    sync_status = json.loads(sync.read_text()) if sync.exists() else None
    if sync_status:
        sync_status.pop("request_log", None)
    osf = p(cfg, "api_cache") / "oddsapi_status.json"
    odds_status = json.loads(osf.read_text()) if osf.exists() else None
    _write(site / "matchday.json", export_matchday(cfg, as_of, M, S, injuries, odds_meta, team_map))
    perf = export_performance(cfg, bt)
    perf["corners"] = json.loads(cm.read_text()) if cm.exists() else None
    _write(site / "performance.json", perf)
    _write(site / "paper.json", export_paper(p(cfg, "outputs") / "paper_log.csv"))
    _write(site / "meta.json", {
        "generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "as_of": str(as_of),
        "model_version": cfg["model_version"], "config_hash": cfg["_hash"], "demo": demo,
        "disclaimer": DISCLAIMER, "sources": manifest["sources"], "quality": quality,
        "unmapped_names": manifest.get("unmapped_names", [])[:200], "sync": sync_status, "odds_sync": odds_status,
        "betting_rules": cfg["betting"], "simulation": cfg["simulation"]})
    return site

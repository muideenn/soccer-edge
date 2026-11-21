"""Turn cached API-Football responses into the canonical tables used by the models."""
import datetime as dt
import json
from pathlib import Path

import numpy as np
import pandas as pd

from .apisports import flatten_odds
from .config import p

FINISHED = {"FT", "AET", "PEN"}
UPCOMING = {"NS", "TBD"}


def comp_table(cfg):
    """API league id -> (comp, country, tier)."""
    ids = cfg["api"]["league_ids"]
    out = {}
    for name, lg in cfg["leagues"].items():
        if name in ids:
            out[ids[name]] = (name, lg["country"], 1)
        if lg["second"] in ids:
            out[ids[lg["second"]]] = (lg["second"], lg["country"], 2)
    if "UCL" in ids:
        out[ids["UCL"]] = ("UCL", "EUR", 0)
    return out


def load_statistics(root):
    """fixture_id -> {hc, ac, hs, as_, hst, ast} from cached fixtures/statistics responses."""
    out = {}
    d = root / "statistics"
    for f in d.glob("*.json") if d.exists() else []:
        resp = json.loads(f.read_text()).get("response", [])
        if len(resp) != 2:
            continue
        vals = []
        for team in resp:
            st = {x.get("type"): x.get("value") for x in team.get("statistics", [])}
            vals.append(st)
        num = lambda v: float(v) if isinstance(v, (int, float)) else np.nan  # noqa: E731
        out[int(f.stem)] = {"hc": num(vals[0].get("Corner Kicks")), "ac": num(vals[1].get("Corner Kicks")),
                            "hs": num(vals[0].get("Total Shots")), "as_": num(vals[1].get("Total Shots")),
                            "hst": num(vals[0].get("Shots on Goal")), "ast": num(vals[1].get("Shots on Goal"))}
    return out


REQUIRED = (("fixture", "id"), ("fixture", "date"), ("fixture", "status"), ("league", "round"),
            ("teams", "home"), ("teams", "away"))


def valid_fixture(x):
    try:
        return all(x[a][b] is not None for a, b in REQUIRED) and x["teams"]["home"].get("name") and x["teams"]["away"].get("name")
    except (KeyError, TypeError):
        return False


def load_api_matches(cfg, mapper, candidates_by_country, all_teams):
    root = p(cfg, "api_cache")
    stats = load_statistics(root)
    comps = comp_table(cfg)
    res, fx, teammap = [], [], {}
    meta = {"files": [], "latest_result": None, "rejected_items": 0}
    for f in sorted((root / "fixtures").glob("*.json")) if (root / "fixtures").exists() else []:
        blob = json.loads(f.read_text())
        lid = blob["league"]
        if lid not in comps:
            continue
        comp, country, tier = comps[lid]
        meta["files"].append({"file": f.name, "fetched_utc": blob.get("fetched_utc"), "n": len(blob["response"])})
        cands = candidates_by_country.get(country) or all_teams
        for x in blob["response"]:
            if not valid_fixture(x):
                meta["rejected_items"] += 1
                continue
            st = x["fixture"]["status"]["short"]
            names = []
            for side in ("home", "away"):
                t = x["teams"][side]
                nm = mapper.map(t["name"], cands, f"api:{comp}")
                teammap[t["id"]] = {"api_name": t["name"], "canonical": nm, "logo": t.get("logo")}
                names.append(nm)
            ko = pd.Timestamp(x["fixture"]["date"]).tz_convert("UTC")
            rec = {"date": pd.Timestamp(ko.date()), "kickoff": ko.strftime("%H:%M"), "tz": "UTC",
                   "kickoff_utc": ko.isoformat(), "comp": comp, "country": country, "tier": tier,
                   "home": names[0], "away": names[1], "round": x["league"].get("round"),
                   "api_fixture_id": x["fixture"]["id"], "venue": (x["fixture"].get("venue") or {}).get("name"),
                   "home_logo": x["teams"]["home"].get("logo"), "away_logo": x["teams"]["away"].get("logo"),
                   "source": f"api:{f.name}"}
            if st in FINISHED:
                ft = x["score"].get("fulltime") or {}
                ht = x["score"].get("halftime") or {}
                if ft.get("home") is None:  # 90-minute score missing -> fall back to goals
                    ft = x.get("goals") or {}
                rec.update(hg=ft.get("home"), ag=ft.get("away"), hthg=ht.get("home"), htag=ht.get("away"),
                           neutral=comp == "UCL" and "Final" == str(x["league"].get("round", "")).strip())
                rec.update(stats.get(x["fixture"]["id"], {}))
                if rec.get("hg") is None or rec.get("ag") is None:
                    meta["rejected_items"] += 1
                    continue
                res.append(rec)
                meta["latest_result"] = max(meta["latest_result"] or "", str(ko.date()))
            elif st in UPCOMING:
                fx.append(rec)
    return pd.DataFrame(res), pd.DataFrame(fx), teammap, meta


def detect_ah_convention(rows):
    """API 'Away X' values: is X the away side's own handicap ('own') or the home line ('home')?

    In a two-way AH market the home line L pairs with the away line -L. Count which reading
    produces complete pairs with a sane overround and use the better-supported one.
    """
    df = pd.DataFrame([r for r in rows if r["market"] == "AH"])
    if df.empty:
        return "own", {"own": 0, "home": 0}
    score = {"own": 0, "home": 0}
    for (_, _), g in df.groupby(["fixture_id", "bookmaker"]):
        H = {r.line: r.odds for r in g[g.selection == "home"].itertuples()}
        A = {r.line: r.odds for r in g[g.selection == "away"].itertuples()}
        for L, oh in H.items():
            if L == 0:
                continue
            for conv, key in (("own", -L), ("home", L)):
                if key in A and 1.0 < 1 / oh + 1 / A[key] < 1.15:
                    score[conv] += 1
    return ("home" if score["home"] > score["own"] else "own"), score


def load_api_odds(cfg, fixtures):
    """Latest pre-match odds for upcoming fixtures, normalised to the report's odds format."""
    root = p(cfg, "api_cache") / "odds" / "latest"
    rows = []
    for f in sorted(root.glob("*.json")) if root.exists() else []:
        blob = json.loads(f.read_text())
        rows += flatten_odds(blob["response"], blob["fetched_utc"])
    conv_cfg = cfg["api"].get("ah_away_value_convention", "auto")
    conv, score = detect_ah_convention(rows) if conv_cfg == "auto" else (conv_cfg, {})
    if not rows or not len(fixtures):
        return pd.DataFrame(), {"ah_convention": conv, "ah_votes": score, "n_rows": 0}
    o = pd.DataFrame(rows)
    if conv == "home":
        m = (o.market == "AH") & (o.selection == "away")
        o.loc[m, "line"] = -o.loc[m, "line"]
    fx = fixtures.dropna(subset=["api_fixture_id"])[["api_fixture_id", "date", "home", "away"]]
    o = o.merge(fx, left_on="fixture_id", right_on="api_fixture_id", how="inner")
    o = o.rename(columns={"update_utc": "timestamp_utc"})
    o = o.sort_values("fetched_utc").drop_duplicates(["fixture_id", "bookmaker", "market", "selection", "line"], keep="last")
    return o, {"ah_convention": conv, "ah_votes": score, "n_rows": int(len(o)),
               "bookmakers": sorted(o.bookmaker.unique().tolist())}


def load_api_injuries(cfg):
    root = p(cfg, "api_cache") / "injuries"
    out = []
    for f in sorted(root.glob("*.json")) if root.exists() else []:
        blob = json.loads(f.read_text())
        for x in blob["response"]:
            out.append({"fixture_id": (x.get("fixture") or {}).get("id"), "team_id": x["team"]["id"],
                        "team": x["team"]["name"], "player": x["player"]["name"],
                        "type": x["player"].get("type"), "reason": x["player"].get("reason"),
                        "fetched_utc": blob.get("fetched_utc")})
    return pd.DataFrame(out)

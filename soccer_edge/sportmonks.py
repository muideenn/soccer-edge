"""Sportmonks Football API v3 provider (https://docs.sportmonks.com/football).

Documented pieces this module relies on:
  * auth: token in the `Authorization` header (or `api_token` query param; we never put it in URLs)
  * GET /v3/football/fixtures/between/{start}/{end}  (max 100 days), filters=fixtureLeagues:<ids>,
    include=participants;scores;statistics;state, pagination per_page<=50 with has_more
  * scores entries: {participant_id, score: {goals, participant: home|away}, description}; the
    "2ND_HALF" description is the cumulative 90-minute score ("CURRENT" is the latest/final score)
  * statistics entries: {type_id, participant_id, data: {value}, location}; type 34 = corners,
    86 = shots on target
  * GET /v3/football/odds/pre-match/fixtures/{id}: odds with market_id, bookmaker_id, label, value,
    total, handicap, market_description, latest_bookmaker_update
  * HTTP 429 when the hourly limit is exceeded; the current limit is reported in `meta`

Markets are matched by description text first and documented v3 ids second, so a renamed or
renumbered market is skipped rather than mis-parsed.
"""
import datetime as dt
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

from .env import redact

BASE = "https://api.sportmonks.com/v3"
FINISHED_STATES = {"FT", "AET", "FT_PEN", "AWARDED"}
UPCOMING_STATES = {"NS", "TBA"}
STAT_CORNERS, STAT_SHOTS_ON_TARGET = 34, 86
BOOKMAKER_NAMES = {2: "Bet365"}          # documented id; others are shown as "Sportmonks book <id>"


def token():
    return os.environ.get("SPORTMONKS_API_TOKEN")


class SportmonksBudget(Exception):
    pass


class Sportmonks:
    def __init__(self, tok=None, budget=200, transport=None, base=BASE):
        self.tok = tok or token()
        self.budget, self.used = budget, 0
        self.transport = transport
        self.base = base
        self.rate = None
        self.log = []

    def _http(self, path, params):
        if not self.tok:
            raise RuntimeError("SPORTMONKS_API_TOKEN is not set")
        url = f"{self.base}/{path}?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(url, headers={"Authorization": self.tok, "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=40) as r:
                return r.status, r.read().decode()
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode(errors="replace")

    def get(self, path, **params):
        if self.used >= self.budget:
            raise SportmonksBudget(f"run budget of {self.budget} calls reached")
        status, body = (self.transport or self._http)(path, params)
        self.used += 1
        self.log.append({"path": path, "params": {k: v for k, v in params.items()}, "status": status})
        if status == 429:
            raise SportmonksBudget("hourly rate limit reached (HTTP 429)")
        if status in (401, 403):
            raise PermissionError(redact(f"HTTP {status}: token rejected or plan does not include this data: {body[:200]}"))
        if status >= 400:
            raise RuntimeError(redact(f"HTTP {status} for {path}: {body[:200]}"))
        data = json.loads(body)
        meta = data.get("rate_limit") or (data.get("meta") or {}).get("rate_limit")
        if isinstance(meta, dict):
            self.rate = meta
        if "message" in data and "data" not in data:  # e.g. plan/subscription messages
            raise PermissionError(redact(str(data["message"])[:200]))
        return data

    def get_all(self, path, **params):
        out, page = [], 1
        while True:
            d = self.get(path, **params, page=page, per_page=50)
            items = d.get("data") or []
            out += items if isinstance(items, list) else [items]
            if not (d.get("pagination") or {}).get("has_more"):
                return out
            page += 1


def sync(cfg, root, client=None, today=None):
    """Recent results + upcoming fixtures (one paged call for all leagues), then odds per fixture."""
    sc = cfg.get("sportmonks", {})
    st = {"provider": "sportmonks", "steps": [], "warnings": []}
    client = client or Sportmonks(budget=sc.get("run_budget", 200))
    if not client.tok and client.transport is None:
        st["steps"].append({"step": "skip", "ok": True, "reason": "SPORTMONKS_API_TOKEN not set"})
        return st
    root = Path(root) / "sportmonks"
    today = today or dt.date.today()
    start = today - dt.timedelta(days=sc.get("lookback_days", 10))
    end = today + dt.timedelta(days=cfg["api"].get("odds_horizon_days", 4))
    ids = ",".join(str(v) for v in sc.get("league_ids", {}).values())
    fixtures = []
    try:
        fixtures = client.get_all(f"football/fixtures/between/{start}/{end}",
                                  include="participants;scores;statistics;state", filters=f"fixtureLeagues:{ids}")
        (root / "fixtures").mkdir(parents=True, exist_ok=True)
        (root / "fixtures" / "latest.json").write_text(json.dumps(
            {"fetched_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
             "start": str(start), "end": str(end), "data": fixtures}))
        st["steps"].append({"step": f"fixtures {start}..{end}", "ok": True, "items": len(fixtures)})
    except (SportmonksBudget, PermissionError, RuntimeError) as e:
        st["steps"].append({"step": "fixtures", "ok": False, "reason": str(e)})
        if isinstance(e, PermissionError):
            st["warnings"].append(f"Sportmonks: {e}")
    for b in sc.get("backfill_ranges", []) or []:
        f = root / "fixtures" / f"{b[0]}_{b[1]}.json"
        if f.exists():
            continue
        try:
            data = client.get_all(f"football/fixtures/between/{b[0]}/{b[1]}",
                                  include="participants;scores;statistics;state", filters=f"fixtureLeagues:{ids}")
            f.write_text(json.dumps({"fetched_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "data": data}))
            st["steps"].append({"step": f"backfill {b[0]}..{b[1]}", "ok": True, "items": len(data)})
        except (SportmonksBudget, PermissionError, RuntimeError) as e:
            st["steps"].append({"step": f"backfill {b[0]}..{b[1]}", "ok": False, "reason": str(e)})
            break
    if sc.get("sync_odds", True):
        upcoming = [x for x in fixtures if _state(x) in UPCOMING_STATES]
        (root / "odds").mkdir(parents=True, exist_ok=True)
        fetched = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
        for x in upcoming:
            try:
                odds = client.get_all(f"football/odds/pre-match/fixtures/{x['id']}")
                (root / "odds" / f"{x['id']}.json").write_text(json.dumps({"fetched_utc": fetched, "data": odds}))
                st["steps"].append({"step": f"odds {x['id']}", "ok": True, "items": len(odds)})
            except PermissionError as e:
                st["steps"].append({"step": "odds", "ok": False, "reason": str(e)})
                st["warnings"].append(f"Sportmonks odds: {e}")
                break
            except (SportmonksBudget, RuntimeError) as e:
                st["steps"].append({"step": f"odds {x['id']}", "ok": False, "reason": str(e)})
                break
        for f in (root / "odds").glob("*.json"):  # drop odds files for fixtures no longer upcoming
            if f.stem not in {str(x["id"]) for x in upcoming}:
                f.unlink()
    st.update(calls_used=client.used, rate_limit=client.rate)
    return st


# ------------------------------------------------------------------ parsing
def _state(x):
    s = x.get("state")
    if isinstance(s, dict):
        return s.get("developer_name") or s.get("short_name") or s.get("state")
    return {5: "FT", 1: "NS"}.get(x.get("state_id"))


def _sides(x):
    """participant_id -> 'home'/'away' from participants meta, scores, or the 'Home vs Away' name."""
    sides = {}
    for p in x.get("participants") or []:
        loc = (p.get("meta") or {}).get("location")
        if loc in ("home", "away"):
            sides[p["id"]] = loc
    for s in x.get("scores") or []:
        loc = (s.get("score") or {}).get("participant")
        if loc in ("home", "away") and s.get("participant_id"):
            sides.setdefault(s["participant_id"], loc)
    if len(sides) < 2 and " vs " in str(x.get("name", "")):
        h, a = x["name"].split(" vs ", 1)
        for p in x.get("participants") or []:
            if p.get("name") == h.strip():
                sides[p["id"]] = "home"
            elif p.get("name") == a.strip():
                sides[p["id"]] = "away"
    return sides


def parse_fixture(x):
    """Return a dict with names, kickoff, state, 90-minute goals, corners, shots on target."""
    sides = _sides(x)
    names = {sides.get(p["id"]): p.get("name") for p in x.get("participants") or [] if sides.get(p["id"])}
    logos = {sides.get(p["id"]): p.get("image_path") for p in x.get("participants") or [] if sides.get(p["id"])}
    if "home" not in names or "away" not in names:
        return None
    goals = {}
    for desc in ("2ND_HALF", "CURRENT"):
        for s in x.get("scores") or []:
            if s.get("description") == desc:
                loc = (s.get("score") or {}).get("participant")
                if loc in ("home", "away") and (desc, loc) not in goals:
                    goals[(desc, loc)] = (s.get("score") or {}).get("goals")
    hg = goals.get(("2ND_HALF", "home"), goals.get(("CURRENT", "home")))
    ag = goals.get(("2ND_HALF", "away"), goals.get(("CURRENT", "away")))
    ht = {(s.get("score") or {}).get("participant"): (s.get("score") or {}).get("goals")
          for s in x.get("scores") or [] if s.get("description") == "1ST_HALF"}
    stat = {}
    for s in x.get("statistics") or []:
        loc = s.get("location") or sides.get(s.get("participant_id"))
        val = (s.get("data") or {}).get("value")
        if loc in ("home", "away") and isinstance(val, (int, float)):
            stat[(s.get("type_id"), loc)] = float(val)
    ko = pd.Timestamp(x.get("starting_at")).tz_localize("UTC") if x.get("starting_at") else None
    return {"sm_fixture_id": x.get("id"), "league_id": x.get("league_id"), "state": _state(x),
            "home_name": names["home"], "away_name": names["away"],
            "home_logo": logos.get("home"), "away_logo": logos.get("away"),
            "kickoff_utc": ko.isoformat() if ko is not None else None,
            "date": pd.Timestamp(ko.date()) if ko is not None else None, "kickoff": ko.strftime("%H:%M") if ko is not None else None,
            "hg": hg, "ag": ag, "hthg": ht.get("home"), "htag": ht.get("away"),
            "hc": stat.get((STAT_CORNERS, "home"), np.nan), "ac": stat.get((STAT_CORNERS, "away"), np.nan),
            "hst": stat.get((STAT_SHOTS_ON_TARGET, "home"), np.nan), "ast": stat.get((STAT_SHOTS_ON_TARGET, "away"), np.nan),
            "round": None}


def load_matches(cfg, mapper, candidates_by_country, all_teams):
    root = Path(cfg["_root"]) / cfg["paths"]["api_cache"] / "sportmonks" / "fixtures"
    lid_to_comp = {}
    for comp, lid in cfg.get("sportmonks", {}).get("league_ids", {}).items():
        country = "EUR" if comp == "UCL" else cfg["leagues"][comp]["country"]
        lid_to_comp[lid] = (comp, country, 0 if comp == "UCL" else 1)
    res, fx, meta = [], [], {"files": 0, "rejected_items": 0, "latest_result": None, "fetched_utc": None}
    seen = set()
    for f in sorted(root.glob("*.json"), reverse=True) if root.exists() else []:
        blob = json.loads(f.read_text())
        meta["files"] += 1
        meta["fetched_utc"] = max(meta["fetched_utc"] or "", blob.get("fetched_utc") or "")
        for x in blob.get("data", []):
            if x.get("id") in seen:
                continue
            seen.add(x.get("id"))
            p = parse_fixture(x)
            if p is None or p["league_id"] not in lid_to_comp or p["date"] is None:
                meta["rejected_items"] += 1
                continue
            comp, country, tier = lid_to_comp[p["league_id"]]
            cands = candidates_by_country.get(country) or all_teams
            rec = {**p, "comp": comp, "country": country, "tier": tier, "tz": "UTC",
                   "home": mapper.map(p["home_name"], cands, f"sportmonks:{comp}"),
                   "away": mapper.map(p["away_name"], cands, f"sportmonks:{comp}"),
                   "neutral": False, "source": f"sportmonks:{f.name}"}
            if p["state"] in FINISHED_STATES and p["hg"] is not None and p["ag"] is not None:
                res.append(rec)
                meta["latest_result"] = max(meta["latest_result"] or "", str(p["date"].date()))
            elif p["state"] in UPCOMING_STATES:
                fx.append(rec)
    drop = ["league_id", "state", "home_name", "away_name"]
    R = pd.DataFrame(res)
    F = pd.DataFrame(fx)
    R = R.drop(columns=[c for c in drop + ["sm_fixture_id"] if c in R]) if len(R) else R
    F = F.rename(columns={"sm_fixture_id": "sm_id"}).drop(columns=[c for c in drop if c in F]) if len(F) else F
    return R, F, meta


def _market(o):
    d = str(o.get("market_description") or "").lower()
    mid = o.get("market_id")
    if d in ("fulltime result", "full time result", "match winner", "3way result") or (not d and mid == 1):
        return "1X2"
    if d in ("goals over/under", "over/under", "match goals") or (not d and mid == 80):
        return "OU"
    if d in ("both teams to score",) or (not d and mid == 14):
        return "BTTS"
    if d in ("double chance",) or (not d and mid == 2):
        return "DC"
    if d in ("asian handicap",) or (not d and mid == 6):
        return "AH"
    if d in ("alternative corners", "corners over/under", "total corners", "corners") :
        return "CORNERS"
    return None


def _num(v):
    try:
        return float(str(v).replace("+", ""))
    except (TypeError, ValueError):
        return None


def parse_odds(items, fetched):
    rows = []
    for o in items:
        mk = _market(o)
        odd = _num(o.get("value") or o.get("dp3"))
        if not mk or odd is None or odd <= 1:
            continue
        lab = str(o.get("label") or o.get("name") or "").strip().lower()
        line = None
        if mk == "1X2":
            sel = {"1": "H", "home": "H", "x": "D", "draw": "D", "2": "A", "away": "A"}.get(lab)
        elif mk == "DC":
            sel = {"1x": "1X", "home/draw": "1X", "x2": "X2", "draw/away": "X2", "12": "12", "home/away": "12"}.get(lab)
        elif mk == "BTTS":
            sel = {"yes": "yes", "no": "no"}.get(lab)
        elif mk in ("OU", "CORNERS"):
            sel = lab if lab in ("over", "under") else None
            line = _num(o.get("total"))
            if line is None:
                sel = None
        elif mk == "AH":
            sel = {"1": "home", "home": "home", "2": "away", "away": "away"}.get(lab)
            line = _num(o.get("handicap"))
            if line is None:
                sel = None
        else:
            sel = None
        if sel is None:
            continue
        bid = o.get("bookmaker_id")
        rows.append({"fixture_id": o.get("fixture_id"), "bookmaker": BOOKMAKER_NAMES.get(bid, f"Sportmonks book {bid}"),
                     "market": mk, "selection": sel, "line": line, "odds": odd,
                     "update_utc": o.get("latest_bookmaker_update") or o.get("updated_at"), "fetched_utc": fetched})
    return rows


def load_odds(cfg, fixtures):
    from .apidata import detect_ah_convention
    root = Path(cfg["_root"]) / cfg["paths"]["api_cache"] / "sportmonks" / "odds"
    rows = []
    for f in sorted(root.glob("*.json")) if root.exists() else []:
        blob = json.loads(f.read_text())
        rows += parse_odds(blob.get("data", []), blob.get("fetched_utc"))
    if not rows or not len(fixtures) or "sm_id" not in fixtures:
        return pd.DataFrame(), {"n_rows": 0}
    conv, votes = detect_ah_convention(rows)
    o = pd.DataFrame(rows)
    if conv == "home":
        m = (o.market == "AH") & (o.selection == "away")
        o.loc[m, "line"] = -o.loc[m, "line"]
    fx = fixtures.dropna(subset=["sm_id"])[["sm_id", "date", "home", "away"]]
    o = o.merge(fx, left_on="fixture_id", right_on="sm_id", how="inner").drop(columns=["fixture_id"])
    o = o.rename(columns={"update_utc": "timestamp_utc"}).assign(source="sportmonks")
    return o, {"n_rows": int(len(o)), "ah_convention": conv, "ah_votes": votes}

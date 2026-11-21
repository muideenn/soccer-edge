"""API-Football v3 client (direct api-sports.io or RapidAPI) with a hard request budget.

The key is read from the environment (API_FOOTBALL_KEY) and never written to disk or logs.
Every raw response is cached under data/api/ so finished seasons are fetched once and
every published number can be traced back to the response it came from.
"""
import datetime as dt
import gzip
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

PROVIDERS = {
    "apisports": {"base": "https://v3.football.api-sports.io", "key_header": "x-apisports-key"},
    "rapidapi": {"base": "https://api-football-v1.p.rapidapi.com/v3", "key_header": "x-rapidapi-key",
                 "extra": {"x-rapidapi-host": "api-football-v1.p.rapidapi.com"}},
}


class BudgetExhausted(Exception):
    pass


class PlanError(Exception):
    """The subscription does not cover this request (e.g. season not on the free plan)."""


class ApiFootball:
    def __init__(self, provider="apisports", key=None, budget=90, per_minute=10, transport=None, log=None):
        if provider not in PROVIDERS:
            raise ValueError(f"provider must be one of {list(PROVIDERS)}")
        self.p = PROVIDERS[provider]
        self.provider = provider
        from .env import soccer_key
        self.key = key or soccer_key()
        self.budget = budget
        self.used = 0
        self.min_interval = 60.0 / per_minute if per_minute else 0
        self._last = 0.0
        self.transport = transport  # injectable for tests: fn(path, params) -> (status, headers, body)
        self.remaining_today = None
        self.log = log if log is not None else []

    def _http(self, path, params):
        if not self.key:
            raise RuntimeError("SOCCER_API_KEY is not set (add it to .env.local or GitHub Secrets)")
        url = f"{self.p['base']}/{path}?{urllib.parse.urlencode(params)}"
        headers = {self.p["key_header"]: self.key, **self.p.get("extra", {})}
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status, dict(r.headers), r.read().decode()
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers or {}), e.read().decode(errors="replace")

    def get(self, path, **params):
        if self.used >= self.budget:
            raise BudgetExhausted(f"run budget of {self.budget} requests reached")
        wait = self.min_interval - (time.monotonic() - self._last)
        if wait > 0 and self.transport is None:
            time.sleep(wait)
        status, headers, body = (self.transport or self._http)(path, params)
        self._last = time.monotonic()
        self.used += 1
        h = {k.lower(): v for k, v in headers.items()}
        rem = h.get("x-ratelimit-requests-remaining")
        if rem is not None:
            self.remaining_today = int(rem)
        entry = {"t": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "path": path,
                 "params": params, "status": status, "remaining_today": self.remaining_today}
        self.log.append(entry)
        if status == 429:
            raise BudgetExhausted("provider rate limit (HTTP 429)")
        if status >= 400:
            from .env import redact
            raise RuntimeError(redact(f"HTTP {status} for {path}: {body[:200]}"))
        data = json.loads(body)
        errs = data.get("errors")
        if errs:
            msg = json.dumps(errs)
            entry["errors"] = errs
            if isinstance(errs, dict) and ("plan" in errs or "access" in errs):
                raise PlanError(msg)
            if isinstance(errs, dict) and ("rateLimit" in errs or "requests" in errs):
                raise BudgetExhausted(msg)
            raise RuntimeError(f"API error for {path}: {msg}")
        if self.remaining_today is not None and self.remaining_today <= 2:
            self.budget = self.used  # stop before the daily quota is gone
        return data

    def get_all_pages(self, path, **params):
        first = self.get(path, **params)
        out = list(first.get("response", []))
        total = (first.get("paging") or {}).get("total", 1) or 1
        for page in range(2, total + 1):
            out += self.get(path, **params, page=page).get("response", [])
        return out


def season_for(date):
    """API-Football labels a European season by its start year (2026 = 2026-27)."""
    return date.year if date.month >= 7 else date.year - 1


class Sync:
    """Fetch what the model needs, in priority order, inside the request budget."""

    def __init__(self, cfg, client, root):
        self.cfg, self.c = cfg, client
        self.root = Path(root)
        self.status = {"started": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                       "provider": client.provider, "steps": [], "warnings": []}

    def _save(self, rel, obj):
        f = self.root / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(obj, separators=(",", ":")))

    def _step(self, name, fn):
        try:
            n = fn()
            self.status["steps"].append({"step": name, "ok": True, "items": n})
            return True
        except BudgetExhausted as e:
            self.status["steps"].append({"step": name, "ok": False, "reason": f"budget: {e}"})
            return False
        except PlanError as e:
            self.status["steps"].append({"step": name, "ok": False, "reason": f"plan: {e}"})
            self.status["warnings"].append(f"{name}: your API plan does not cover this request ({e})")
            return True  # keep going with other steps

    def fixtures(self, league_id, season, force=False):
        rel = f"fixtures/{league_id}_{season}.json"
        f = self.root / rel
        done_season = season < season_for(dt.date.today())
        if f.exists() and done_season and not force:
            return 0
        resp = self.c.get_all_pages("fixtures", league=league_id, season=season)
        self._save(rel, {"fetched_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                         "league": league_id, "season": season, "response": resp})
        return len(resp)

    def odds_for_date(self, league_id, season, date):
        resp = self.c.get_all_pages("odds", league=league_id, season=season, date=str(date))
        fetched = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
        self._save(f"odds/latest/{league_id}_{date}.json", {"fetched_utc": fetched, "response": resp})
        # append a compact, gzipped snapshot of reference-book prices for closing-line value
        keep = set(self.cfg["api"].get("reference_bookmakers", []))
        hist = self.root / f"odds/history/{fetched[:10]}.jsonl.gz"
        hist.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(hist, "at") as fh:
            for r in flatten_odds(resp, fetched):
                if r["bookmaker"] in keep:
                    fh.write(json.dumps(r, separators=(",", ":")) + "\n")
        return len(resp)

    def prune(self, today, keep_days=150):
        """Drop stale 'latest' odds files and old history so the repository stays small."""
        n = 0
        for f in (self.root / "odds/latest").glob("*.json") if (self.root / "odds/latest").exists() else []:
            d = f.stem.split("_")[-1]
            if d < str(today - dt.timedelta(days=2)):
                f.unlink()
                n += 1
        for f in (self.root / "odds/history").glob("*.jsonl.gz") if (self.root / "odds/history").exists() else []:
            if f.name[:10] < str(today - dt.timedelta(days=keep_days)):
                f.unlink()
                n += 1
        return n

    def statistics(self, fixture_id):
        resp = self.c.get("fixtures/statistics", fixture=fixture_id).get("response", [])
        self._save(f"statistics/{fixture_id}.json",
                   {"fetched_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "response": resp})
        return len(resp)

    def missing_statistics(self, league_ids, season, limit):
        have = {f.stem for f in (self.root / "statistics").glob("*.json")} if (self.root / "statistics").exists() else set()
        todo = []
        for lid in league_ids:
            f = self.root / f"fixtures/{lid}_{season}.json"
            if not f.exists():
                continue
            for x in json.loads(f.read_text())["response"]:
                if x["fixture"]["status"]["short"] in ("FT", "AET", "PEN") and str(x["fixture"]["id"]) not in have:
                    todo.append((x["fixture"]["date"], x["fixture"]["id"]))
        return [fid for _, fid in sorted(todo, reverse=True)[:limit]]

    def injuries(self, league_id, season):
        resp = self.c.get_all_pages("injuries", league=league_id, season=season)
        self._save(f"injuries/{league_id}_{season}.json",
                   {"fetched_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "response": resp})
        return len(resp)

    def run(self, today=None, backfill=()):
        api = self.cfg["api"]
        today = today or dt.date.today()
        season = season_for(today)
        ids = api["league_ids"]
        top = [ids[k] for k in api["sync_competitions"]]
        second = [ids[k] for k in api.get("sync_second_divisions", [])]
        # 1. current-season fixtures and results (top flights + UCL first)
        for lid in top + second:
            if not self._step(f"fixtures {lid}/{season}", lambda lid=lid: self.fixtures(lid, season)):
                break
        # 2. pre-match odds for fixtures inside the horizon
        upcoming = upcoming_fixture_dates(self.root, top, season, today, api["odds_horizon_days"])
        for lid, d in upcoming:
            if not self._step(f"odds {lid}/{d}", lambda lid=lid, d=d: self.odds_for_date(lid, season, d)):
                break
        # 3. injuries (displayed, not modelled)
        if api.get("sync_injuries", True):
            for lid in top:
                if not self._step(f"injuries {lid}", lambda lid=lid: self.injuries(lid, season)):
                    break
        # 4. optional per-match statistics (corners, shots): 1 request per finished match
        if api.get("sync_fixture_statistics"):
            for fid in self.missing_statistics(top, season, api.get("statistics_per_run", 10)):
                if not self._step(f"statistics {fid}", lambda fid=fid: self.statistics(fid)):
                    break
        # 5. optional history backfill (finished seasons are fetched once, then cached)
        for s in backfill:
            for lid in top + second:
                if not self._step(f"backfill {lid}/{s}", lambda lid=lid, s=s: self.fixtures(lid, s)):
                    break
        self._step("prune cache", lambda: self.prune(today))
        self.status.update(finished=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                           requests_used=self.c.used, remaining_today=self.c.remaining_today,
                           request_log=self.c.log)
        self._save("sync_status.json", self.status)
        return self.status


def upcoming_fixture_dates(root, league_ids, season, today, horizon):
    out = set()
    end = today + dt.timedelta(days=horizon)
    for lid in league_ids:
        f = Path(root) / f"fixtures/{lid}_{season}.json"
        if not f.exists():
            continue
        for x in json.loads(f.read_text())["response"]:
            if x["fixture"]["status"]["short"] not in ("NS", "TBD"):
                continue
            d = dt.date.fromisoformat(x["fixture"]["date"][:10])
            if today <= d <= end:
                out.add((lid, d))
    return sorted(out, key=lambda t: (t[1], t[0]))


# ---------------------------------------------------------------- odds parsing
BET_MAP = {"match winner": "1X2", "goals over/under": "OU", "asian handicap": "AH", "both teams score": "BTTS",
           "double chance": "DC", "home/away": "DNB", "total - home": "TT_HOME", "total - away": "TT_AWAY",
           "corners over under": "CORNERS"}


def _parse_value(market, v):
    v = str(v).strip()
    if market == "1X2":
        return {"Home": "H", "Draw": "D", "Away": "A"}.get(v), None
    if market == "DNB":
        return {"Home": "H", "Away": "A"}.get(v), None
    if market == "DC":
        return {"Home/Draw": "1X", "Draw/Away": "X2", "Home/Away": "12"}.get(v), None
    if market == "BTTS":
        return {"Yes": "yes", "No": "no"}.get(v), None
    if market in ("OU", "TT_HOME", "TT_AWAY", "CORNERS"):
        parts = v.split()
        if len(parts) == 2 and parts[0] in ("Over", "Under"):
            try:
                return parts[0].lower(), float(parts[1])
            except ValueError:
                return None, None
        return None, None
    if market == "AH":
        parts = v.split()
        if len(parts) == 2 and parts[0] in ("Home", "Away"):
            try:
                return parts[0].lower(), float(parts[1])
            except ValueError:
                return None, None
    return None, None


def flatten_odds(resp, fetched_utc):
    rows = []
    for item in resp:
        fid = item["fixture"]["id"]
        for b in item.get("bookmakers", []):
            for bet in b.get("bets", []):
                mkt = BET_MAP.get(str(bet.get("name", "")).lower())
                if not mkt:
                    continue
                for v in bet.get("values", []):
                    sel, line = _parse_value(mkt, v.get("value"))
                    try:
                        odd = float(v.get("odd"))
                    except (TypeError, ValueError):
                        continue
                    if sel is None or odd <= 1.0:
                        continue
                    rows.append({"fixture_id": fid, "bookmaker": b.get("name"), "market": mkt, "selection": sel,
                                 "line": line, "odds": odd, "update_utc": item.get("update"), "fetched_utc": fetched_utc,
                                 "kickoff_utc": item["fixture"].get("date")})
    return rows

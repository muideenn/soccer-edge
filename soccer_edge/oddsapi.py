"""Optional second odds provider: The Odds API v4 (https://the-odds-api.com/liveapi/guides/v4/).

Documented featured markets used here: h2h (1X2) and totals (over/under goals).
Cost per call = markets x regions credits; the free plan has 500 credits/month, so by default
this runs at most once per ~20 hours with 2 markets x 1 region = 2 credits per competition.
The key (ODDS_API_KEY) is sent as a query parameter, so request URLs are never logged.
"""
import datetime as dt
import gzip
import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import pandas as pd

from .env import odds_key, redact

BASE = "https://api.the-odds-api.com/v4"


def fetch(cfg, root, transport=None, now=None):
    oc = cfg.get("oddsapi", {})
    key = odds_key()
    status = {"provider": "the-odds-api", "steps": [], "credits_remaining": None}
    if not key and transport is None:
        status["steps"].append({"step": "skip", "ok": True, "reason": "ODDS_API_KEY not set"})
        return status
    now = now or dt.datetime.now(dt.timezone.utc)
    root = Path(root) / "oddsapi"
    stamp = root / "last_run.txt"
    if stamp.exists() and transport is None:
        last = dt.datetime.fromisoformat(stamp.read_text().strip())
        if (now - last).total_seconds() < oc.get("min_hours_between_runs", 20) * 3600:
            status["steps"].append({"step": "skip", "ok": True, "reason": "ran recently (credit budget)"})
            return status
    for comp, sport in oc.get("sports", {}).items():
        params = {"apiKey": key or "test", "regions": oc.get("regions", "eu"), "markets": oc.get("markets", "h2h,totals"),
                  "oddsFormat": "decimal", "dateFormat": "iso"}
        try:
            if transport:
                code, headers, body = transport(sport, params)
            else:
                url = f"{BASE}/sports/{sport}/odds?{urllib.parse.urlencode(params)}"
                with urllib.request.urlopen(url, timeout=30) as r:
                    code, headers, body = r.status, dict(r.headers), r.read().decode()
        except urllib.error.HTTPError as e:
            status["steps"].append({"step": f"odds {comp}", "ok": False, "reason": redact(f"HTTP {e.code}")})
            if e.code in (401, 429):
                break
            continue
        except Exception as e:  # network, timeout
            status["steps"].append({"step": f"odds {comp}", "ok": False, "reason": redact(type(e).__name__)})
            continue
        h = {k.lower(): v for k, v in headers.items()}
        status["credits_remaining"] = h.get("x-requests-remaining", status["credits_remaining"])
        data = json.loads(body)
        if not isinstance(data, list):
            status["steps"].append({"step": f"odds {comp}", "ok": False, "reason": "unexpected response shape"})
            continue
        fetched = now.isoformat(timespec="seconds")
        (root / "latest").mkdir(parents=True, exist_ok=True)
        (root / "latest" / f"{comp}.json").write_text(json.dumps({"fetched_utc": fetched, "response": data}))
        keep = {b.lower() for b in cfg["api"].get("reference_bookmakers", [])}
        hist = root / "history" / f"{fetched[:10]}.jsonl.gz"
        hist.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(hist, "at") as fh:
            for row in flatten(data, comp, fetched):
                if row["bookmaker"].lower() in keep:
                    fh.write(json.dumps(row, default=str) + "\n")
        status["steps"].append({"step": f"odds {comp}", "ok": True, "items": len(data)})
    if transport is None:
        root.mkdir(parents=True, exist_ok=True)
        stamp.write_text(now.isoformat(timespec="seconds"))
    return status


def flatten(events, comp, fetched):
    rows = []
    for ev in events:
        try:
            home, away, ko = ev["home_team"], ev["away_team"], ev["commence_time"]
        except (KeyError, TypeError):
            continue
        for b in ev.get("bookmakers", []):
            for m in b.get("markets", []):
                for o in m.get("outcomes", []):
                    price = o.get("price")
                    if not isinstance(price, (int, float)) or price <= 1:
                        continue
                    if m.get("key") == "h2h":
                        sel = "H" if o.get("name") == home else "A" if o.get("name") == away else "D" if o.get("name") == "Draw" else None
                        mk_, line = "1X2", None
                    elif m.get("key") == "totals" and o.get("point") is not None:
                        sel, mk_, line = str(o.get("name", "")).lower(), "OU", float(o["point"])
                        if sel not in ("over", "under"):
                            sel = None
                    else:
                        sel = None
                    if sel is None:
                        continue
                    rows.append({"comp": comp, "event_home": home, "event_away": away, "kickoff_utc": ko,
                                 "bookmaker": b.get("title") or b.get("key"), "market": mk_, "selection": sel,
                                 "line": line, "odds": float(price), "timestamp_utc": b.get("last_update"),
                                 "fetched_utc": fetched})
    return rows


def load_latest(cfg, root, mapper, candidates_by_comp, fixtures):
    """Normalise cached Odds API prices to the report's odds rows, matched to known fixtures."""
    d = Path(root) / "oddsapi" / "latest"
    rows = []
    for f in sorted(d.glob("*.json")) if d.exists() else []:
        blob = json.loads(f.read_text())
        rows += flatten(blob["response"], f.stem, blob["fetched_utc"])
    if not rows or not len(fixtures):
        return pd.DataFrame()
    o = pd.DataFrame(rows)
    o["home"] = [mapper.map(n, candidates_by_comp.get(c, []), f"oddsapi:{c}") for n, c in zip(o.event_home, o.comp)]
    o["away"] = [mapper.map(n, candidates_by_comp.get(c, []), f"oddsapi:{c}") for n, c in zip(o.event_away, o.comp)]
    o["date"] = pd.to_datetime(o.kickoff_utc, utc=True).dt.tz_convert(None).dt.normalize()
    fx = fixtures[["home", "away", "date"]].assign(date=pd.to_datetime(fixtures.date))
    o = o.merge(fx, on=["home", "away"], suffixes=("", "_fx"))
    o = o[(o.date - o.date_fx).abs() <= pd.Timedelta(days=1)].drop(columns=["date_fx"])
    return o.assign(source="the-odds-api")

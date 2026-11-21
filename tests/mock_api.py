"""API-Football-shaped mock responses for offline tests (synthetic odds; never published)."""
import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
API_NAMES = {"Manchester City FC": "Manchester City", "Manchester United FC": "Manchester United",
             "Nottingham Forest FC": "Nottingham Forest", "Hull City AFC": "Hull City", "Arsenal FC": "Arsenal",
             "Tottenham Hotspur FC": "Tottenham", "Newcastle United FC": "Newcastle", "AFC Bournemouth": "Bournemouth",
             "Brighton & Hove Albion FC": "Brighton", "Leeds United FC": "Leeds", "Coventry City FC": "Coventry",
             "Ipswich Town FC": "Ipswich", "Sunderland AFC": "Sunderland", "Aston Villa FC": "Aston Villa",
             "Chelsea FC": "Chelsea", "Crystal Palace FC": "Crystal Palace", "Everton FC": "Everton",
             "Fulham FC": "Fulham", "Liverpool FC": "Liverpool", "Brentford FC": "Brentford"}


def epl_fixtures(played_until="2026-11-20"):
    src = json.load(open(ROOT / "data/raw/fj/2026-27/en.1.json"))["matches"]
    ids = {n: 30 + i for i, n in enumerate(sorted(API_NAMES))}
    out = []
    rng = np.random.default_rng(3)
    for k, x in enumerate(src):
        sc = x.get("score")
        if isinstance(sc, list):
            sc = {"ft": sc}
        played = x["date"] <= played_until
        if played and not (sc and sc.get("ft")):
            sc = {"ft": [int(rng.poisson(1.5)), int(rng.poisson(1.2))], "ht": [0, 0]}  # fill the gap synthetically
        ft = (sc or {}).get("ft") if played else None
        out.append({"fixture": {"id": 900000 + k, "date": f"{x['date']}T{x.get('time', '15:00')}:00+00:00",
                                "timezone": "UTC", "venue": {"name": "Stadium"},
                                "status": {"short": "FT" if played else "NS"}},
                    "league": {"id": 39, "season": 2026, "round": x["round"].replace("Matchday", "Regular Season -")},
                    "teams": {"home": {"id": ids[x["team1"]], "name": API_NAMES[x["team1"]], "logo": None},
                              "away": {"id": ids[x["team2"]], "name": API_NAMES[x["team2"]], "logo": None}},
                    "goals": {"home": ft[0] if ft else None, "away": ft[1] if ft else None},
                    "score": {"halftime": {"home": (sc or {}).get("ht", [None, None])[0] if played else None,
                                           "away": (sc or {}).get("ht", [None, None])[1] if played else None},
                              "fulltime": {"home": ft[0] if ft else None, "away": ft[1] if ft else None}}})
    return out


def odds_for(fixtures, date, convention="own", margin=1.06):
    """Synthetic prices with a fixed margin: Pinnacle (reference) and a softer book."""
    resp = []
    for f in fixtures:
        if not f["fixture"]["date"].startswith(str(date)) or f["fixture"]["status"]["short"] != "NS":
            continue
        ph, pd_, pa = 0.45, 0.27, 0.28
        books = []
        for name, m in (("Pinnacle", 1.03), ("Bet365", margin)):
            o = lambda q: f"{1 / (q * m):.2f}"  # noqa: E731
            ah_away = "-0.25" if convention == "home" else "0.25"
            books.append({"id": 1, "name": name, "bets": [
                {"id": 1, "name": "Match Winner", "values": [{"value": "Home", "odd": o(ph)}, {"value": "Draw", "odd": o(pd_)},
                                                             {"value": "Away", "odd": o(pa)}]},
                {"id": 5, "name": "Goals Over/Under", "values": [{"value": "Over 2.5", "odd": o(0.52)}, {"value": "Under 2.5", "odd": o(0.48)}]},
                {"id": 4, "name": "Asian Handicap", "values": [{"value": "Home -0.25", "odd": o(0.5)}, {"value": f"Away {ah_away}", "odd": o(0.5)}]},
                {"id": 8, "name": "Both Teams Score", "values": [{"value": "Yes", "odd": o(0.55)}, {"value": "No", "odd": o(0.45)}]},
            ]})
        resp.append({"fixture": {"id": f["fixture"]["id"], "date": f["fixture"]["date"]}, "league": {"id": 39},
                     "update": "2026-11-21T06:00:00+00:00", "bookmakers": books})
    return resp


class MockTransport:
    def __init__(self, convention="own", plan_block=()):
        self.fx = epl_fixtures()
        self.convention = convention
        self.plan_block = set(plan_block)
        self.calls = []

    def __call__(self, path, params):
        self.calls.append((path, dict(params)))
        hdr = {"x-ratelimit-requests-remaining": str(100 - len(self.calls))}
        if params.get("league") in self.plan_block:
            return 200, hdr, json.dumps({"errors": {"plan": "Free plans do not have access to this season."}, "response": []})
        if path == "fixtures":
            resp = self.fx if params["league"] == 39 else []
        elif path == "odds":
            resp = odds_for(self.fx, params["date"], self.convention) if params["league"] == 39 else []
        elif path == "injuries":
            resp = [{"player": {"id": 1, "name": "A. Player", "type": "Missing Fixture", "reason": "Knee Injury"},
                     "team": {"id": 30, "name": "Arsenal"}, "fixture": {"id": self.fx[-300]["fixture"]["id"]}}] if params["league"] == 39 else []
        else:
            resp = []
        return 200, hdr, json.dumps({"errors": [], "paging": {"current": 1, "total": 1}, "response": resp})

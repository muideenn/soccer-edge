"""Sportmonks-v3-shaped mock responses (structure from docs.sportmonks.com), synthetic values."""
import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
SM_NAMES = {"Manchester City FC": "Manchester City", "Manchester United FC": "Manchester United",
            "Nottingham Forest FC": "Nottingham Forest", "Hull City AFC": "Hull City", "Arsenal FC": "Arsenal",
            "Tottenham Hotspur FC": "Tottenham Hotspur", "Newcastle United FC": "Newcastle United",
            "AFC Bournemouth": "AFC Bournemouth", "Brighton & Hove Albion FC": "Brighton & Hove Albion",
            "Leeds United FC": "Leeds United", "Coventry City FC": "Coventry City", "Ipswich Town FC": "Ipswich Town",
            "Sunderland AFC": "Sunderland", "Aston Villa FC": "Aston Villa", "Chelsea FC": "Chelsea",
            "Crystal Palace FC": "Crystal Palace", "Everton FC": "Everton", "Fulham FC": "Fulham",
            "Liverpool FC": "Liverpool", "Brentford FC": "Brentford"}


def fixtures():
    src = json.load(open(ROOT / "data/raw/fj/2026-27/en.1.json"))["matches"]
    ids = {n: 100 + i for i, n in enumerate(sorted(SM_NAMES))}
    rng = np.random.default_rng(5)
    out = []
    for k, x in enumerate(src):
        played = x["date"] <= "2026-11-20"
        h, a = ids[x["team1"]], ids[x["team2"]]
        fx = {"id": 5000 + k, "league_id": 8, "name": f"{SM_NAMES[x['team1']]} vs {SM_NAMES[x['team2']]}",
              "starting_at": f"{x['date']} {x.get('time', '15:00')}:00", "state_id": 5 if played else 1,
              "state": {"id": 5 if played else 1, "developer_name": "FT" if played else "NS"},
              "participants": [{"id": h, "name": SM_NAMES[x["team1"]], "image_path": None, "meta": {"location": "home"}},
                               {"id": a, "name": SM_NAMES[x["team2"]], "image_path": None, "meta": {"location": "away"}}],
              "scores": [], "statistics": []}
        if played:
            g = [int(rng.poisson(1.5)), int(rng.poisson(1.2))]
            for pid, loc, goals in ((h, "home", g[0]), (a, "away", g[1])):
                fx["scores"] += [{"participant_id": pid, "description": "2ND_HALF", "score": {"goals": goals, "participant": loc}},
                                 {"participant_id": pid, "description": "CURRENT", "score": {"goals": goals, "participant": loc}}]
                fx["statistics"].append({"type_id": 34, "participant_id": pid, "location": loc, "data": {"value": int(rng.poisson(5))}})
        out.append(fx)
    return out


def odds(fid):
    rows = []
    for m, d, vals in ((1, "Fulltime Result", [("1", None, None, 0.46), ("X", None, None, 0.27), ("2", None, None, 0.27)]),
                       (80, "Goals Over/Under", [("Over", "2.5", None, 0.52), ("Under", "2.5", None, 0.48)]),
                       (6, "Asian Handicap", [("1", None, "-0.5", 0.47), ("2", None, "0.5", 0.53)]),
                       (69, "Alternative Corners", [("Over", "9.5", None, 0.5), ("Under", "9.5", None, 0.5)])):
        for lab, tot, hcp, p in vals:
            rows.append({"fixture_id": fid, "market_id": m, "market_description": d, "bookmaker_id": 2, "label": lab,
                         "value": f"{1 / (p * 1.05):.2f}", "total": tot, "handicap": hcp,
                         "latest_bookmaker_update": "2026-11-21 06:00:00"})
    return rows


class SMTransport:
    def __init__(self):
        self.fx = fixtures()
        self.calls = []

    def __call__(self, path, params):
        self.calls.append(path)
        if path.startswith("football/fixtures/between/"):
            _, _, _, start, end = path.split("/")
            data = [x for x in self.fx if start <= x["starting_at"][:10] <= end]
            page, per = int(params.get("page", 1)), int(params.get("per_page", 25))
            chunk = data[(page - 1) * per: page * per]
            return 200, json.dumps({"data": chunk, "pagination": {"has_more": page * per < len(data)},
                                    "rate_limit": {"remaining": 1999, "resets_in_seconds": 3000}})
        if path.startswith("football/odds/pre-match/fixtures/"):
            return 200, json.dumps({"data": odds(int(path.rsplit("/", 1)[1])), "pagination": {"has_more": False}})
        return 404, "{}"

import copy
import datetime as dt
import json
import shutil

import pandas as pd
import pytest

from soccer_edge.config import ROOT, load_config
from soccer_edge.ingest import find_conflicts
from soccer_edge.sportmonks import Sportmonks, parse_fixture, parse_odds, sync

from .mock_sportmonks import SMTransport, odds


def test_parse_fixture_uses_90_minute_score_and_corners():
    x = {"id": 1, "league_id": 8, "starting_at": "2026-11-21 15:00:00", "state": {"developer_name": "AET"},
         "participants": [{"id": 10, "name": "A", "meta": {"location": "home"}}, {"id": 20, "name": "B", "meta": {"location": "away"}}],
         "scores": [{"participant_id": 10, "description": "2ND_HALF", "score": {"goals": 1, "participant": "home"}},
                    {"participant_id": 20, "description": "2ND_HALF", "score": {"goals": 1, "participant": "away"}},
                    {"participant_id": 10, "description": "CURRENT", "score": {"goals": 2, "participant": "home"}},
                    {"participant_id": 20, "description": "CURRENT", "score": {"goals": 1, "participant": "away"}}],
         "statistics": [{"type_id": 34, "participant_id": 10, "location": "home", "data": {"value": 7}},
                        {"type_id": 34, "participant_id": 20, "location": "away", "data": {"value": 3}}]}
    p = parse_fixture(x)
    assert (p["hg"], p["ag"]) == (1, 1)            # extra-time goal excluded
    assert (p["hc"], p["ac"]) == (7.0, 3.0)
    assert p["home_name"] == "A" and p["state"] == "AET"


def test_sides_fall_back_to_fixture_name():
    x = {"id": 2, "league_id": 8, "name": "A vs B", "starting_at": "2026-11-22 12:00:00", "state_id": 1,
         "participants": [{"id": 1, "name": "B"}, {"id": 2, "name": "A"}]}
    p = parse_fixture(x)
    assert p["home_name"] == "A" and p["away_name"] == "B" and p["state"] == "NS"


def test_parse_odds_markets():
    rows = parse_odds(odds(7), "now")
    got = {(r["market"], r["selection"], r["line"]) for r in rows}
    assert ("1X2", "D", None) in got and ("OU", "over", 2.5) in got and ("AH", "home", -0.5) in got and ("CORNERS", "under", 9.5) in got
    assert all(r["bookmaker"] == "Bet365" for r in rows)


def test_unknown_market_is_skipped_not_misparsed():
    assert parse_odds([{"fixture_id": 1, "market_id": 999, "market_description": "Player Shots", "label": "Over", "value": "1.9", "total": "1.5"}], "t") == []


def test_budget_and_permission_errors():
    t = lambda path, params: (200, json.dumps({"message": "You do not have access to this league."}))  # noqa: E731
    with pytest.raises(PermissionError):
        Sportmonks(tok="x", budget=5, transport=t).get("football/fixtures/between/a/b")
    c = Sportmonks(tok="x", budget=1, transport=SMTransport())
    c.get("football/odds/pre-match/fixtures/1")
    from soccer_edge.sportmonks import SportmonksBudget
    with pytest.raises(SportmonksBudget):
        c.get("football/odds/pre-match/fixtures/1")


def test_conflict_detection():
    d = pd.DataFrame({"_wk": [2026, 2026], "comp": ["EPL", "EPL"], "home": ["A", "A"], "away": ["B", "B"],
                      "hg": [2, 1], "ag": [0, 0], "date": pd.to_datetime(["2026-11-01", "2026-11-01"]),
                      "source": ["api:x", "sportmonks:y"]})
    c = find_conflicts(d)
    assert len(c) == 1 and {r["score"] for r in c[0]["reports"]} == {"2-0", "1-0"}


@pytest.mark.skipif(not (ROOT / "data/raw/cfmd").exists(), reason="raw data not fetched")
def test_end_to_end_sportmonks(tmp_path):
    from soccer_edge.cli import cmd_export
    cfg = copy.deepcopy(load_config())
    for k in ("api_cache", "site_data", "outputs"):
        cfg["paths"][k] = str(tmp_path / k)
    cfg["paths"]["odds_input"] = str(tmp_path / "none.csv")
    cfg["paths"]["fixtures_input"] = str(tmp_path / "none2.csv")
    cfg["sportmonks"]["backfill_ranges"] = [["2026-09-01", "2026-11-10"]]
    (tmp_path / "outputs").mkdir()
    shutil.copy(ROOT / "outputs/backtest_results.pkl", tmp_path / "outputs/backtest_results.pkl")
    st = sync(cfg, tmp_path / "api_cache", Sportmonks(tok="x", transport=SMTransport()), today=dt.date(2026, 11, 21))
    assert st["steps"][0]["ok"] and any(s["step"].startswith("backfill") and s["ok"] for s in st["steps"])
    cmd_export(cfg, "2026-11-21")
    md = json.loads((tmp_path / "site_data/matchday.json").read_text())
    meta = json.loads((tmp_path / "site_data/meta.json").read_text())
    epl = [f for f in md["fixtures"] if f["comp"] == "EPL"]
    assert epl and all(f["data_ok"] for f in epl)                         # Sportmonks results closed the gap
    assert all(f["reference_book"] == "Bet365" for f in epl)              # anchored to Sportmonks Bet365 odds
    assert any(s["market"] == "CORNERS" for f in epl for s in f["selections"])
    assert all(f["corners_last_data"] >= "2026-11-01" for f in epl)       # corners refreshed from statistics
    assert not [u for u in meta["unmapped_names"] if u.startswith("sportmonks:EPL")]
    assert meta["demo"] is False

import copy
import datetime as dt
import json
import shutil

import pytest

from soccer_edge.apidata import detect_ah_convention
from soccer_edge.apisports import ApiFootball, BudgetExhausted, Sync, flatten_odds, season_for
from soccer_edge.config import ROOT, load_config

from .mock_api import MockTransport, epl_fixtures, odds_for

TODAY = dt.date(2026, 11, 21)


def test_season_label():
    assert season_for(dt.date(2026, 11, 21)) == 2026
    assert season_for(dt.date(2027, 3, 1)) == 2026


def test_flatten_odds_parses_markets():
    fx = epl_fixtures()
    rows = flatten_odds(odds_for(fx, "2026-11-21"), "2026-11-21T07:00:00+00:00")
    mk = {(r["market"], r["selection"]) for r in rows}
    assert {("1X2", "H"), ("1X2", "D"), ("OU", "over"), ("AH", "home"), ("AH", "away"), ("BTTS", "yes")} <= mk
    assert all(r["odds"] > 1 for r in rows)


@pytest.mark.parametrize("conv", ["own", "home"])
def test_ah_convention_detection(conv):
    fx = epl_fixtures()
    rows = flatten_odds(odds_for(fx, "2026-11-21", convention=conv), "t")
    got, votes = detect_ah_convention(rows)
    assert got == conv, votes


def test_budget_is_hard_limit():
    c = ApiFootball("apisports", key="x", budget=2, transport=MockTransport())
    c.get("fixtures", league=39, season=2026)
    c.get("fixtures", league=39, season=2026)
    with pytest.raises(BudgetExhausted):
        c.get("fixtures", league=39, season=2026)


def test_rapidapi_provider_headers():
    c = ApiFootball("rapidapi", key="secret")
    assert c.p["key_header"] == "x-rapidapi-key" and "x-rapidapi-host" in c.p["extra"]
    assert "rapidapi.com" in c.p["base"]


@pytest.fixture
def cfg(tmp_path):
    c = load_config()
    c = copy.deepcopy(c)
    for k in ("api_cache", "site_data", "outputs"):
        c["paths"][k] = str(tmp_path / k)
    c["paths"]["odds_input"] = str(tmp_path / "none.csv")
    c["paths"]["fixtures_input"] = str(tmp_path / "none2.csv")
    (tmp_path / "outputs").mkdir()
    shutil.copy(ROOT / "outputs/backtest_results.pkl", tmp_path / "outputs/backtest_results.pkl")
    return c


def test_plan_error_is_reported_not_fatal(cfg, tmp_path):
    t = MockTransport(plan_block={2})  # UCL blocked by plan
    c = ApiFootball("apisports", key="SECRET-KEY-123", budget=60, transport=t)
    st = Sync(cfg, c, tmp_path / "api_cache").run(today=TODAY)
    assert any("plan" in w for w in st["warnings"])
    assert (tmp_path / "api_cache/fixtures/39_2026.json").exists()
    cached = "".join(f.read_text() for f in (tmp_path / "api_cache").rglob("*.json"))
    assert "SECRET-KEY-123" not in cached  # key never written to disk


@pytest.mark.skipif(not (ROOT / "data/raw/cfmd").exists(), reason="raw data not fetched")
def test_end_to_end_with_mock_api(cfg, tmp_path):
    from soccer_edge.cli import cmd_export
    t = MockTransport()
    Sync(cfg, ApiFootball("apisports", key="x", budget=60, transport=t), tmp_path / "api_cache").run(today=TODAY)
    cmd_export(cfg, "2026-11-21")
    md = json.loads((tmp_path / "site_data/matchday.json").read_text())
    meta = json.loads((tmp_path / "site_data/meta.json").read_text())
    epl = [f for f in md["fixtures"] if f["comp"] == "EPL"]
    assert epl and all(f["data_ok"] for f in epl)                      # API results made ratings fresh
    assert all(f["reference_book"] == "Pinnacle" for f in epl)          # anchored to reference book
    assert not [u for u in meta["unmapped_names"] if u.startswith("api:EPL")]
    sels = [s for f in epl for s in f["selections"]]
    assert sels and all(s["odds_source"] in ("Pinnacle", "Bet365") for s in sels)
    assert meta["demo"] is False
    assert md["odds"]["ah_convention"] == "own"


def test_paper_settlement_with_closing_line_value(tmp_path):
    import gzip

    import pandas as pd

    from soccer_edge.tracking import log_predictions, settle
    hist = tmp_path / "history"
    hist.mkdir()
    with gzip.open(hist / "2026-11-21.jsonl.gz", "wt") as fh:
        for fetched, odds in (("2026-11-20T07:00:00+00:00", 2.30), ("2026-11-21T07:00:00+00:00", 2.10),
                              ("2026-11-21T16:00:00+00:00", 1.50)):  # last one is after kickoff: ignored
            fh.write(json.dumps({"fixture_id": 7, "bookmaker": "Pinnacle", "market": "1X2", "selection": "H",
                                 "line": None, "odds": odds, "fetched_utc": fetched,
                                 "kickoff_utc": "2026-11-21T15:00:00+00:00"}) + "\n")
    log = tmp_path / "paper.csv"
    log_predictions([{"match_id": "m1", "market": "1X2", "selection": "H", "line": None, "odds": 2.31,
                      "odds_source": "Bet365", "decision": "BET", "api_fixture_id": 7}], log)
    matches = pd.DataFrame({"match_id": ["m1"], "hg": [2], "ag": [1]})
    out = settle(log, matches, hist, ["Pinnacle"])
    r = out.iloc[0]
    assert r.result == "2-1" and r.profit == pytest.approx(1.31)
    assert r.closing_odds == 2.10 and r.clv == pytest.approx(2.31 / 2.10 - 1)

import json
import os

import numpy as np
import pandas as pd
import pytest

from soccer_edge import markets as mk
from soccer_edge.corners import corner_matrix, corner_pmf
from soccer_edge.demo import demo_odds
from soccer_edge.dixon_coles import score_matrix
from soccer_edge.env import load_dotenv, redact
from soccer_edge.oddsapi import fetch, flatten


def test_corner_pmf_is_overdispersed_and_normalised():
    p = corner_pmf(5.0, 12.0)
    g = np.arange(len(p))
    mean, var = (p * g).sum(), (p * g ** 2).sum() - (p * g).sum() ** 2
    assert abs(p.sum() - 1) < 1e-12 and abs(mean - 5.0) < 0.05
    assert var > mean  # negative binomial: more spread than Poisson


def test_corners_market_settlement():
    M = corner_matrix(5.5, 4.5, 12.0)
    R = mk.returns("CORNERS", "over", 1.9, M.shape[-1] - 1, 9.5)
    assert R[5, 5] == pytest.approx(0.9) and R[5, 4] == -1
    tot = np.add.outer(np.arange(M.shape[0]), np.arange(M.shape[1]))
    assert mk.ev(M, R) == pytest.approx((M * (tot > 9.5)).sum() * 1.9 - 1)


def test_api_corners_bet_parsed():
    from soccer_edge.apisports import flatten_odds
    resp = [{"fixture": {"id": 1, "date": "2026-11-21T15:00:00+00:00"}, "update": "t", "bookmakers": [
        {"name": "Bet365", "bets": [{"id": 45, "name": "Corners Over Under", "values": [{"value": "Over 9.5", "odd": "1.85"}, {"value": "Under 9.5", "odd": "1.95"}]}]}]}]
    rows = flatten_odds(resp, "now")
    assert {(r["market"], r["selection"], r["line"]) for r in rows} == {("CORNERS", "over", 9.5), ("CORNERS", "under", 9.5)}


def test_demo_odds_are_labelled_and_carry_margin():
    r = type("R", (), {"date": pd.Timestamp("2026-11-21"), "home": "A", "away": "B"})()
    M = score_matrix(1.5, 1.1, -0.05)
    o = demo_odds(r, M, corner_matrix(5, 4.5, 12.0), np.random.default_rng(0))
    assert (o.source == "demo").all() and o.bookmaker.str.contains("synthetic").all()
    x = o[(o.market == "1X2") & (o.bookmaker == o.bookmaker.iloc[0])]
    assert (1 / x.odds).sum() > 1.02  # a bookmaker-style margin, so demo prices don't invent value
    assert {"CORNERS", "AH", "BTTS", "OU", "DC"} <= set(o.market)


def test_oddsapi_flatten_and_mock_fetch(tmp_path):
    ev = [{"id": "e1", "home_team": "Arsenal", "away_team": "Chelsea", "commence_time": "2026-11-22T16:30:00Z",
           "bookmakers": [{"key": "pinnacle", "title": "Pinnacle", "last_update": "2026-11-21T08:00:00Z", "markets": [
               {"key": "h2h", "outcomes": [{"name": "Arsenal", "price": 2.1}, {"name": "Chelsea", "price": 3.5}, {"name": "Draw", "price": 3.4}]},
               {"key": "totals", "outcomes": [{"name": "Over", "price": 1.9, "point": 2.5}, {"name": "Under", "price": 1.95, "point": 2.5}]}]}]}]
    rows = flatten(ev, "EPL", "now")
    assert {(r["market"], r["selection"]) for r in rows} == {("1X2", "H"), ("1X2", "A"), ("1X2", "D"), ("OU", "over"), ("OU", "under")}
    cfg = {"oddsapi": {"sports": {"EPL": "soccer_epl"}}, "api": {"reference_bookmakers": ["Pinnacle"]}}
    st = fetch(cfg, tmp_path, transport=lambda sport, params: (200, {"x-requests-remaining": "498"}, json.dumps(ev)))
    assert st["credits_remaining"] == "498" and (tmp_path / "oddsapi/latest/EPL.json").exists()
    assert "apiKey" not in (tmp_path / "oddsapi/latest/EPL.json").read_text()


def test_missing_odds_key_is_a_clean_skip(tmp_path, monkeypatch):
    monkeypatch.delenv("ODDS_API_KEY", raising=False)
    st = fetch({"oddsapi": {"sports": {"EPL": "soccer_epl"}}, "api": {}}, tmp_path)
    assert st["steps"][0]["reason"] == "ODDS_API_KEY not set"


def test_dotenv_does_not_override_and_redacts(tmp_path, monkeypatch):
    import soccer_edge.env as envmod
    monkeypatch.setattr(envmod, "ROOT", tmp_path)
    (tmp_path / ".env.local").write_text("SOCCER_API_KEY=from-file-123456\nexport ODDS_API_KEY='odds-secret-999'\n")
    monkeypatch.setenv("SOCCER_API_KEY", "from-env-abcdef")
    monkeypatch.delenv("ODDS_API_KEY", raising=False)
    load_dotenv()
    assert os.environ["SOCCER_API_KEY"] == "from-env-abcdef"   # real environment wins
    assert os.environ["ODDS_API_KEY"] == "odds-secret-999"
    assert redact("error with odds-secret-999 in it") == "error with *** in it"

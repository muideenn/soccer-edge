import numpy as np
import pandas as pd
import pytest

from soccer_edge import markets as mk
from soccer_edge.anchor import market_lambdas
from soccer_edge.dixon_coles import DixonColes, score_matrix
from soccer_edge.ingest import Loader
from soccer_edge.odds import devig_power, devig_proportional, devig_shin, overround
from soccer_edge.staking import gate, kelly_general, stake

CFG_BET = {"min_edge": 0.04, "require_lower_ev_positive": True, "max_odds": {"1X2": 6.0}, "min_odds": 1.3,
           "kelly_fraction": 0.25, "max_stake_pct": 0.02}


def test_devig_sums_to_one():
    o = np.array([1.5, 4.2, 6.5])
    assert overround(o) > 0
    for f in (devig_proportional, devig_shin, devig_power):
        assert abs(f(o).sum() - 1) < 1e-9
    # Shin/power take more margin from the longshot than proportional does
    assert devig_shin(o)[2] < devig_proportional(o)[2]


def test_score_matrix_and_1x2():
    M = score_matrix(1.6, 1.1, -0.05)
    assert abs(M.sum() - 1) < 1e-12
    assert abs(mk.p1x2(M).sum() - 1) < 1e-12
    assert mk.p_over(M, 2.5) + (1 - mk.p_over(M, 2.5)) == pytest.approx(1)


@pytest.mark.parametrize("margin,line,expected", [
    (1, -0.25, 1.0),     # win both halves
    (0, -0.25, -0.5),    # half loss
    (0, 0.25, 0.5),      # half win
    (1, -1.0, 0.0),      # push
    (2, -1.75, 0.5),     # half on -1.5 wins, half on -2 pushes
    (1, -0.3, 1.0),      # rounded quarter line snaps to -0.25
])
def test_asian_handicap_settlement(margin, line, expected):
    assert mk.ah_return(np.array(margin), line, 2.0) == pytest.approx(expected)


def test_ou_whole_line_push():
    R = mk.returns("OU", "over", 2.0, 10, 3.0)
    assert R[2, 1] == 0 and R[2, 2] == 1 and R[1, 1] == -1


def test_ev_equals_p_times_odds_minus_one():
    M = score_matrix(1.4, 1.2, 0.0)
    ph = mk.p1x2(M)[0]
    assert mk.ev(M, mk.returns("1X2", "H", 2.5)) == pytest.approx(ph * 2.5 - 1)


def test_gate_and_stake_caps():
    assert gate(0.10, 0.03, 2.0, "1X2", CFG_BET)[0]
    assert not gate(0.10, -0.01, 2.0, "1X2", CFG_BET)[0]       # not robust to uncertainty
    assert not gate(0.02, 0.01, 2.0, "1X2", CFG_BET)[0]        # below threshold
    assert not gate(0.30, 0.20, 9.0, "1X2", CFG_BET)[0]        # long shot cap
    assert not gate(0.30, 0.20, 2.0, "1X2", CFG_BET, data_ok=False)[0]
    assert stake(0.5, 2.0, CFG_BET) == pytest.approx(0.02)     # hard cap binds
    assert stake(-0.1, 2.0, CFG_BET) == 0


def test_kelly_general_matches_binary():
    p, o = 0.55, 2.0
    f = kelly_general(np.array([o - 1, -1.0]), np.array([p, 1 - p]), grid=20001)
    assert f == pytest.approx((p * (o - 1) - (1 - p)) / (o - 1), abs=1e-3)


def test_dixon_coles_recovers_strengths():
    rng = np.random.default_rng(0)
    teams = [f"T{i}" for i in range(10)]
    att = np.linspace(-0.4, 0.4, 10)
    rows = []
    d0 = pd.Timestamp("2020-01-01")
    for k in range(6):
        for i in range(10):
            for j in range(10):
                if i != j:
                    lh, la = np.exp(0.2 + 0.25 + att[i]), np.exp(0.2 + att[j])
                    rows.append({"date": d0 + pd.Timedelta(days=k), "home": teams[i], "away": teams[j],
                                 "hg": rng.poisson(lh), "ag": rng.poisson(la), "tier": 1})
    df = pd.DataFrame(rows)
    m = DixonColes(xi=0.0, l2=0.01).fit(df, d0 + pd.Timedelta(days=10))
    est = m.theta[3:13]
    assert np.corrcoef(est, att)[0, 1] > 0.95
    assert m.theta[1] == pytest.approx(0.25, abs=0.08)


def test_no_lookahead_in_walk_forward():
    """Changing results on/after a block start must not change that block's forecasts."""
    from soccer_edge.forecast import dc_block_predict
    rng = np.random.default_rng(1)
    teams = [f"T{i}" for i in range(8)]
    rows = []
    for k in range(400):
        h, a = rng.choice(8, 2, replace=False)
        rows.append({"match_id": f"m{k}", "date": pd.Timestamp("2021-01-01") + pd.Timedelta(days=k),
                     "home": teams[h], "away": teams[a], "hg": rng.poisson(1.4), "ag": rng.poisson(1.1), "tier": 1})
    hist = pd.DataFrame(rows)
    cfg = {"dixon_coles": {"xi": 0.002, "l2": 1.0, "window_days": 1000, "use_second_division": False, "max_goals": 10}}
    ref = pd.Timestamp("2021-12-01")
    blk = hist[hist.date >= ref].head(5)
    a = dc_block_predict(DixonColes(), hist, blk, cfg, ref)
    tampered = hist.copy()
    tampered.loc[tampered.date >= ref, ["hg", "ag"]] = 9
    b = dc_block_predict(DixonColes(), tampered, blk, cfg, ref)
    assert [x["dc_eta_h"] for x in a] == pytest.approx([x["dc_eta_h"] for x in b])


def test_market_lambdas_reproduce_prices():
    M = score_matrix(1.7, 1.0, -0.05)
    p3, po = mk.p1x2(M), mk.p_over(M, 2.5)
    lh, la, rmse = market_lambdas(p3, po, -0.05)
    assert lh == pytest.approx(1.7, abs=0.02) and la == pytest.approx(1.0, abs=0.02) and rmse < 1e-4


@pytest.mark.parametrize("s,exp", [
    ("1-0 (1-0)", (1, 0, 1, 0)),
    ("3-2 a.e.t. (3-0, 1-0)", (3, 0, 1, 0)),
    ("4-3 pen. 1-1 a.e.t. (1-1, 0-1)", (1, 1, 0, 1)),
])
def test_ucl_score_parser_uses_90_minutes(s, exp):
    assert Loader._parse_ucl_score(s) == exp

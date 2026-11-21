"""Goal-difference Elo across top divisions, second divisions and the UCL.

Ratings are recorded *before* each match is applied, so every stored value is leak-free.
UCL matches link the five leagues onto one scale.
"""
import numpy as np
import pandas as pd


def goal_mult(gd):
    gd = abs(gd)
    if gd <= 1:
        return 1.0
    if gd == 2:
        return 1.5
    return (11 + gd) / 8


def run_elo(matches, cfg):
    e = cfg["elo"]
    k, hfa = e["k"], e["home_adv"]
    m = matches.sort_values(["date", "match_id"]).reset_index(drop=True)
    rating, last_tier = {}, {}
    pre_h = np.empty(len(m))
    pre_a = np.empty(len(m))
    season = None
    for i, r in enumerate(m.itertuples(index=False)):
        if r.season != season:
            season = r.season
            if rating:  # regress toward the mean of the tier each team last played in
                df = pd.DataFrame({"t": list(rating), "r": list(rating.values()),
                                   "tier": [last_tier.get(t, 1) for t in rating]})
                means = df.groupby("tier").r.mean().to_dict()
                for t in rating:
                    mu = means.get(last_tier.get(t, 1), 1500)
                    rating[t] = rating[t] + e["season_regress"] * (mu - rating[t])
        for t in (r.home, r.away):
            if t not in rating:
                rating[t] = {1: e["init_top"], 2: e["init_second"]}.get(r.tier, e["init_other"])
        rh, ra = rating[r.home], rating[r.away]
        pre_h[i], pre_a[i] = rh, ra
        if np.isnan(r.hg) or np.isnan(r.ag):
            continue
        dr = rh + (0 if r.neutral else hfa) - ra
        we = 1 / (1 + 10 ** (-dr / 400))
        w = 1.0 if r.hg > r.ag else 0.5 if r.hg == r.ag else 0.0
        delta = k * goal_mult(r.hg - r.ag) * (w - we)
        rating[r.home] = rh + delta
        rating[r.away] = ra - delta
        if r.tier in (1, 2):
            last_tier[r.home] = last_tier[r.away] = r.tier
    m["elo_h"], m["elo_a"] = pre_h, pre_a
    return m[["match_id", "elo_h", "elo_a"]], rating


def attach_clubelo(df, clubelo, date_col="date"):
    """ClubElo rating from the latest snapshot strictly before the match date (no leakage)."""
    ce = clubelo.rename(columns={"club": "team", "elo": "ce"}).sort_values("date")
    out = df.copy()
    for side in ("home", "away"):
        left = out[[date_col, side]].rename(columns={side: "team"}).reset_index()
        left = left.sort_values(date_col)
        j = pd.merge_asof(left, ce[["date", "team", "ce"]].rename(columns={"date": date_col}),
                          on=date_col, by="team", allow_exact_matches=False, direction="backward",
                          tolerance=pd.Timedelta(days=45))
        out.loc[j["index"].values, f"ce_{side[0]}"] = j["ce"].values
    return out

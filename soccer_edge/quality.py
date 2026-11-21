"""Data-quality checks. Problems are reported, never silently patched."""
import numpy as np
import pandas as pd

from .odds import overround


def check(matches, fixtures, cfg, as_of):
    issues, stats = [], {}
    res = matches.dropna(subset=["hg", "ag"])
    dup = matches.duplicated(["date", "home", "away"]).sum()
    if dup:
        issues.append(f"{dup} duplicate (date, home, away) rows")
    neg = ((res.hg < 0) | (res.ag < 0)).sum()
    if neg:
        issues.append(f"{neg} rows with negative goals")
    big = ((res.hg > 10) | (res.ag > 10)).sum()
    if big:
        issues.append(f"{big} rows with >10 goals for one side (truncated at 10 in score matrices)")
    o = matches[["b365_h", "b365_d", "b365_a"]].values
    ok = np.all(np.isfinite(o), 1)
    orr = overround(o[ok])
    bad = ((orr < -0.01) | (orr > 0.30)).sum()
    stats["b365_1x2_overround_median"] = float(np.median(orr)) if ok.any() else None
    if bad:
        issues.append(f"{bad} 1X2 odds rows with implausible overround (<-1% or >30%)")
    if (o[ok] < 1.01).any():
        issues.append("1X2 odds below 1.01 present")
    for name, lg in cfg["leagues"].items():
        x = res[res.comp == name]
        last = x.date.max()
        age = (pd.Timestamp(as_of) - last).days
        stats[f"{name}_last_result"] = str(last.date())
        stats[f"{name}_days_since_last_result"] = int(age)
        past_unplayed = 0
        if fixtures is not None and len(fixtures):
            fxl = fixtures[fixtures.comp == name]
            past_unplayed = int(((fxl.date < pd.Timestamp(as_of) - pd.Timedelta(days=1)) &
                                 (fxl.date >= pd.Timestamp(as_of) - pd.Timedelta(days=60))).sum())
        stats[f"{name}_missing_results"] = past_unplayed
        if past_unplayed > cfg["betting"]["max_missing_results"]:
            issues.append(f"{name}: {past_unplayed} matches already played have no result in the data - ratings are stale")
        elif age > cfg["betting"]["stale_days"]:
            issues.append(f"{name}: latest result is {age} days before as-of date ({last.date()}) - ratings are stale")
        cur = x[x.season == x.season.max()]
        gp = pd.concat([cur.home, cur.away]).value_counts()
        if len(gp) and gp.max() - gp.min() > 3:
            issues.append(f"{name}: uneven games played this season (min {gp.min()}, max {gp.max()}) - possible missing results")
        have_odds = x[x.season >= x.season.max() - 1].b365_h.notna().mean()
        stats[f"{name}_odds_coverage_recent"] = round(float(have_odds), 3)
    ucl = res[res.comp == "UCL"]
    stats["UCL_last_result"] = str(ucl.date.max().date()) if len(ucl) else None
    stats["UCL_has_odds"] = False
    return {"issues": issues, "stats": stats}

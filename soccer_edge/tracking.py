"""Paper-tracking log: every live prediction is recorded before kickoff and settled later.

Paper results are kept separate from backtest results and should be reviewed for a
meaningful sample (hundreds of bets) before any real-money use.
"""
import datetime as dt
from pathlib import Path

import numpy as np
import pandas as pd

from . import markets as mk

COLS = ["logged_at_utc", "model_version", "config_hash", "data_as_of", "match_id", "date", "comp", "home",
        "away", "market", "selection", "line", "odds", "odds_source", "odds_timestamp", "model_p", "ev",
        "ev_lo", "decision", "reason", "stake_frac", "api_fixture_id", "kickoff_utc", "result", "profit", "closing_odds", "clv"]


def log_predictions(rows, path):
    path = Path(path)
    df = pd.DataFrame(rows)
    if df.empty:
        return 0
    df["logged_at_utc"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    for c in COLS:
        if c not in df:
            df[c] = np.nan
    df = df[COLS]
    if path.exists():
        old = pd.read_csv(path)
        key = ["match_id", "market", "selection", "line", "odds"]
        df = df[~df.set_index(key).index.isin(old.set_index(key).index)]
        df = pd.concat([old, df], ignore_index=True)
    df.to_csv(path, index=False)
    return len(df)


def closing_odds(history_dir):
    """Last pre-kickoff reference-book snapshot per (fixture, book, market, selection, line)."""
    import gzip
    import json
    hp = Path(history_dir)
    files = sorted(hp.glob("*.jsonl.gz")) if hp.exists() else []
    recs = []
    for f in files:
        with gzip.open(f, "rt") as fh:
            recs += [json.loads(line) for line in fh if line.strip()]
    if not recs:
        return {}
    h = pd.DataFrame(recs)
    h = h[pd.to_datetime(h.fetched_utc, utc=True) < pd.to_datetime(h.kickoff_utc, utc=True)]
    h = h.sort_values("fetched_utc").drop_duplicates(["fixture_id", "bookmaker", "market", "selection", "line"], keep="last")
    return {(r.fixture_id, r.bookmaker, r.market, r.selection, None if pd.isna(r.line) else round(float(r.line), 2)): r.odds
            for r in h.itertuples()}


def settle(path, matches, history_path=None, reference_books=()):
    """Fill result/profit (and closing-line value when odds history exists) for finished matches."""
    path = Path(path)
    if not path.exists():
        return pd.DataFrame()
    log = pd.read_csv(path)
    for c in COLS:
        if c not in log:
            log[c] = np.nan
    log["result"] = log["result"].astype(object)
    for c in ("profit", "closing_odds", "clv"):
        log[c] = pd.to_numeric(log[c], errors="coerce").astype(float)
    close = closing_odds(history_path) if history_path else {}
    res = matches.dropna(subset=["hg", "ag"]).set_index("match_id")[["hg", "ag"]]
    for i, r in log.iterrows():
        if pd.notna(r.result) or r.match_id not in res.index or not np.isfinite(r.odds):
            continue
        hg, ag = (int(min(x, 10)) for x in res.loc[r.match_id])
        line = r.line if pd.notna(r.line) else None
        R = mk.returns(r.market if r.market != "OU25" else "OU", r.selection, r.odds, 10,
                       2.5 if r.market == "OU25" else line)
        log.loc[i, "result"] = f"{hg}-{ag}"
        log.loc[i, "profit"] = float(R[hg, ag]) if r.decision == "BET" else np.nan
        if pd.notna(r.api_fixture_id):
            mkey = (r.market if r.market != "OU25" else "OU", r.selection, None if pd.isna(r.line) else round(float(r.line), 2))
            c = next((close[(int(r.api_fixture_id), b, *mkey)] for b in reference_books
                      if (int(r.api_fixture_id), b, *mkey) in close), None)
            if c:
                log.loc[i, "closing_odds"] = c
                log.loc[i, "clv"] = r.odds / c - 1
    log.to_csv(path, index=False)
    return log

"""Demo mode: synthetic, clearly-labelled bookmaker prices so the site works before API keys exist.

Prices are the model's own probabilities with a bookmaker-style margin and random noise.
They are NOT real odds; every row carries bookmaker 'DEMO (synthetic)' and source 'demo',
and the site shows a demo banner. Bets are never recommended on demo prices.
"""
import datetime as dt

import numpy as np
import pandas as pd

from . import markets as mk

BOOKS = ["DEMO Book A (synthetic)", "DEMO Book B (synthetic)"]


def _price(p, margin, rng):
    p = float(np.clip(p * np.exp(rng.normal(0, 0.012)), 0.01, 0.985))  # small jitter only: demo must not invent edges
    return round(max(1.01, 1 / (p * (1 + margin))), 2)


def demo_odds(r, M, Mc, rng):
    ts = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    G = M.shape[-1] - 1
    rows = []

    def add(market, sel, line, p):
        for b, margin in zip(BOOKS, (0.045, 0.065)):
            rows.append({"date": r.date, "home": r.home, "away": r.away, "market": market, "selection": sel,
                         "line": line, "odds": _price(p, margin, rng), "bookmaker": b, "timestamp_utc": ts,
                         "source": "demo"})

    h, d, a = mk.p1x2(M)
    add("1X2", "H", None, h)
    add("1X2", "D", None, d)
    add("1X2", "A", None, a)
    add("DC", "1X", None, h + d)
    add("DC", "X2", None, d + a)
    add("DC", "12", None, h + a)
    for L in (0.5, 1.5, 2.5, 3.5, 4.5):
        po = mk.p_over(M, L)
        add("OU", "over", L, po)
        add("OU", "under", L, 1 - po)
    pb = mk.p_btts(M)
    add("BTTS", "yes", None, pb)
    add("BTTS", "no", None, 1 - pb)
    for L in (-1.5, -0.5, 0.5, 1.5):
        ph = float(mk.ev(M, (mk.returns("AH", "home", 2.0, G, L) > 0).astype(float)))
        add("AH", "home", L, ph)
        add("AH", "away", -L, 1 - ph)
    i = np.arange(G + 1)
    for L in (0.5, 1.5):
        ph = float((M * (i[:, None] + 0 * i[None, :] > L)).sum())
        pa = float((M * (0 * i[:, None] + i[None, :] > L)).sum())
        add("TT_HOME", "over", L, ph)
        add("TT_HOME", "under", L, 1 - ph)
        add("TT_AWAY", "over", L, pa)
        add("TT_AWAY", "under", L, 1 - pa)
    if Mc is not None:
        c = np.arange(Mc.shape[0])
        tot = np.add.outer(c, c)
        for L in (8.5, 9.5, 10.5, 11.5):
            pc = float((Mc * (tot > L)).sum())
            add("CORNERS", "over", L, pc)
            add("CORNERS", "under", L, 1 - pc)
    return pd.DataFrame(rows)

"""Hyper-parameter selection for Dixon-Coles on validation seasons only (never test seasons)."""
import copy
import itertools
import json

import numpy as np
import pandas as pd

from .forecast import dc_probs, dc_walk_forward


def outcome_idx(df):
    return np.select([df.hg > df.ag, df.hg == df.ag], [0, 1], 2)


def tune_dc(base, cfg, grid=None):
    res = base[~base.is_fixture.astype(bool)]
    vs = cfg["backtest"]["validation_seasons"]
    start, end = pd.Timestamp(f"{min(vs)}-07-01"), pd.Timestamp(f"{max(vs) + 1}-07-01")
    grid = grid or {"xi": [0.0010, 0.0019, 0.0030], "l2": [1.0, 3.0, 8.0], "use_second_division": [True, False]}
    rows = []
    for xi, l2, sd in itertools.product(grid["xi"], grid["l2"], grid["use_second_division"]):
        c = copy.deepcopy(cfg)
        c["dixon_coles"].update(xi=xi, l2=l2, use_second_division=sd)
        dc = dc_walk_forward(res, c, start, end)
        x = res.merge(dc_probs(dc), on="match_id")
        y = outcome_idx(x)
        P = x[["dc_ph", "dc_pd", "dc_pa"]].values
        o = (x.hg + x.ag > 2.5).values
        ll = -np.mean(np.log(P[np.arange(len(y)), y]))
        llo = -np.mean(np.where(o, np.log(x.dc_po25), np.log(1 - x.dc_po25)))
        rows.append({"xi": xi, "l2": l2, "second_div": sd, "n": len(x), "logloss_1x2": ll, "logloss_ou25": llo})
        print(json.dumps(rows[-1]))
    return pd.DataFrame(rows).sort_values("logloss_1x2")

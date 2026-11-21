"""Data ingestion: every source is normalised to one canonical match table.

Sources (in priority order when the same match appears twice):
  1. drop-in football-data.co.uk CSVs placed in data/inputs/results/ (can carry closing odds)
  2. cfmd mirror of football-data.co.uk (results, shots, Bet365 + max odds)
  3. openfootball JSON (results only; fills the gap after the mirror's last update)
  4. openfootball UCL text files (results only)
"""
import datetime as dt
import json
import re
import subprocess
from pathlib import Path

import numpy as np
import pandas as pd

from .config import p
from .names import UCL_COUNTRY, NameMapper

ODDS_COLS = ["b365_h", "b365_d", "b365_a", "max_h", "max_d", "max_a", "b365_o25", "b365_u25",
             "max_o25", "max_u25", "ah_line", "b365_ahh", "b365_aha",
             "c_h", "c_d", "c_a", "c_o25", "c_u25", "c_ahh", "c_aha"]
BASE_COLS = ["date", "kickoff", "comp", "country", "tier", "season", "home", "away", "hg", "ag",
             "hthg", "htag", "neutral", "hs", "as_", "hst", "ast", "hc", "ac", "source"]


def season_of(d):
    d = pd.to_datetime(d)
    return np.where(d.dt.month >= 7, d.dt.year, d.dt.year - 1)


def _git_meta(path):
    try:
        out = subprocess.run(["git", "-C", str(path), "log", "-1", "--format=%H|%cI"],
                             capture_output=True, text=True, check=True).stdout.strip()
        h, t = out.split("|")
        return {"commit": h[:12], "commit_time": t}
    except Exception:
        return {"commit": None, "commit_time": None}


class Loader:
    def __init__(self, cfg):
        self.cfg = cfg
        self.mapper = NameMapper(p(cfg, "aliases"))
        self.manifest = {"retrieved_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                         "sources": {}}
        self.code_to_comp = {}
        for name, lg in cfg["leagues"].items():
            self.code_to_comp[lg["code"]] = (name, lg["country"], 1)
            self.code_to_comp[lg["second"]] = (lg["second"], lg["country"], 2)

    # ---------- football-data.co.uk style ----------
    def load_cfmd(self):
        path = p(self.cfg, "cfmd_matches")
        m = pd.read_csv(path, low_memory=False)
        m = m[m.Division.isin(self.code_to_comp)].copy()
        out = pd.DataFrame({
            "date": pd.to_datetime(m.MatchDate),
            "kickoff": m.MatchTime.astype("string").str.slice(0, 5),
            "home": m.HomeTeam, "away": m.AwayTeam,
            "hg": m.FTHome, "ag": m.FTAway, "hthg": m.HTHome, "htag": m.HTAway,
            "hs": m.HomeShots, "as_": m.AwayShots, "hst": m.HomeTarget, "ast": m.AwayTarget,
            "hc": m.HomeCorners, "ac": m.AwayCorners,
            "b365_h": m.OddHome, "b365_d": m.OddDraw, "b365_a": m.OddAway,
            "max_h": m.MaxHome, "max_d": m.MaxDraw, "max_a": m.MaxAway,
            "b365_o25": m.Over25, "b365_u25": m.Under25, "max_o25": m.MaxOver25, "max_u25": m.MaxUnder25,
            "ah_line": m.HandiSize, "b365_ahh": m.HandiHome, "b365_aha": m.HandiAway,
        })
        out["ah_line"] = (out.ah_line * 4).round() / 4  # stored rounded to 1 dp; restore quarter lines
        cc = m.Division.map(self.code_to_comp)
        out["comp"] = [c[0] for c in cc]
        out["country"] = [c[1] for c in cc]
        out["tier"] = [c[2] for c in cc]
        out["source"] = "cfmd"
        self.manifest["sources"]["cfmd"] = {
            "path": str(path), "repo": "github.com/xgabora/Club-Football-Match-Data-2000-2025",
            "upstream": "football-data.co.uk (Bet365 & market-max pre-match odds), ClubElo",
            **_git_meta(path.parent), "rows": int(len(out)), "max_date": str(out.date.max().date())}
        return out

    def load_dropins(self):
        d = p(self.cfg, "dropins")
        frames = []
        for f in sorted(Path(d).glob("*.csv")) if Path(d).exists() else []:
            r = pd.read_csv(f, encoding="latin-1")
            r = r[r["Div"].isin(self.code_to_comp)]
            g = lambda c: r[c] if c in r else np.nan  # noqa: E731
            o = pd.DataFrame({
                "date": pd.to_datetime(r.Date, dayfirst=True), "kickoff": g("Time"),
                "home": r.HomeTeam, "away": r.AwayTeam, "hg": r.FTHG, "ag": r.FTAG,
                "hthg": g("HTHG"), "htag": g("HTAG"), "hs": g("HS"), "as_": g("AS"),
                "hst": g("HST"), "ast": g("AST"), "hc": g("HC"), "ac": g("AC"),
                "b365_h": g("B365H"), "b365_d": g("B365D"), "b365_a": g("B365A"),
                "max_h": g("MaxH"), "max_d": g("MaxD"), "max_a": g("MaxA"),
                "b365_o25": g("B365>2.5"), "b365_u25": g("B365<2.5"),
                "max_o25": g("Max>2.5"), "max_u25": g("Max<2.5"),
                "ah_line": g("AHh"), "b365_ahh": g("B365AHH"), "b365_aha": g("B365AHA"),
                "c_h": g("B365CH"), "c_d": g("B365CD"), "c_a": g("B365CA"),
                "c_o25": g("B365C>2.5"), "c_u25": g("B365C<2.5"),
                "c_ahh": g("B365CAHH"), "c_aha": g("B365CAHA"),
            })
            o["ah_line"] = (pd.to_numeric(o.ah_line, errors="coerce") * 4).round() / 4
            cc = r.Div.map(self.code_to_comp)
            o["comp"] = [c[0] for c in cc]
            o["country"] = [c[1] for c in cc]
            o["tier"] = [c[2] for c in cc]
            o["source"] = f"dropin:{f.name}"
            frames.append(o)
            self.manifest["sources"][f"dropin:{f.name}"] = {
                "path": str(f), "rows": int(len(o)),
                "file_mtime": dt.datetime.fromtimestamp(f.stat().st_mtime).isoformat(timespec="seconds")}
        return pd.concat(frames) if frames else pd.DataFrame(columns=BASE_COLS + ODDS_COLS)

    # ---------- openfootball ----------
    def _league_candidates(self, base, country):
        return sorted(set(base.loc[(base.country == country) & (base.date >= "2014-07-01"), "home"]))

    def load_openfootball(self, base, seasons=("2025-26", "2026-27")):
        root = p(self.cfg, "openfootball_json")
        rows, fixtures = [], []
        for name, lg in self.cfg["leagues"].items():
            cands = self._league_candidates(base, lg["country"])
            for s in seasons:
                f = root / s / f"{lg['of']}.json"
                if not f.exists():
                    continue
                for x in json.load(open(f))["matches"]:
                    h = self.mapper.map(x["team1"], cands, name)
                    a = self.mapper.map(x["team2"], cands, name)
                    rec = {"date": pd.Timestamp(x["date"]), "kickoff": x.get("time"), "comp": name,
                           "country": lg["country"], "tier": 1, "home": h, "away": a,
                           "round": x.get("round"), "tz": lg["tz"], "source": f"openfootball:{s}"}
                    sc = x.get("score") or {}
                    if isinstance(sc, list):  # some rows store a bare [h, a] full-time score
                        sc = {"ft": sc} if len(sc) == 2 else {}
                    if sc.get("ft"):
                        rec.update(hg=sc["ft"][0], ag=sc["ft"][1],
                                   hthg=(sc.get("ht") or [np.nan, np.nan])[0],
                                   htag=(sc.get("ht") or [np.nan, np.nan])[1])
                        rows.append(rec)
                    else:
                        fixtures.append(rec)
        self.manifest["sources"]["openfootball"] = {
            "path": str(root), "repo": "github.com/openfootball/football.json", **_git_meta(root),
            "results_rows": len(rows), "fixture_rows": len(fixtures),
            "max_result_date": str(max(r["date"] for r in rows).date()) if rows else None}
        return pd.DataFrame(rows), pd.DataFrame(fixtures)

    _ucl_line = re.compile(
        r"^\s*(?:(\d{1,2}:\d{2})\s+)?(.+?)\s+\((\w{3})\)\s+v\s+(.+?)\s+\((\w{3})\)\s+(.*)$")
    _date_line = re.compile(r"^\s+(?:\[)?(Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+(\w{3})\s+(\d{1,2})(?:\s+(\d{4}))?")

    @staticmethod
    def _parse_ucl_score(s):
        """Return 90-minute (hg, ag, hthg, htag) from e.g. '3-2 a.e.t. (3-0, 1-0)' or '1-0 (1-0)'."""
        s = s.strip()
        if not re.match(r"^\d+-\d+", s):
            return None
        par = re.findall(r"\(([^)]*)\)", s)
        inner = [t.strip() for t in par[0].split(",")] if par else []
        if "a.e.t" in s:
            ft = inner[0] if inner else None
            ht = inner[1] if len(inner) > 1 else None
        else:
            ft = re.match(r"^(\d+-\d+)", s).group(1)
            ht = inner[0] if inner else None
        if ft is None:
            return None
        hg, ag = map(int, ft.split("-"))
        hth, hta = (map(int, ht.split("-")) if ht and re.match(r"^\d+-\d+$", ht) else (np.nan, np.nan))
        return hg, ag, hth, hta

    def load_ucl(self, base, clubelo):
        root = p(self.cfg, "openfootball_ucl")
        by_country = clubelo.groupby("country").club.apply(lambda s: sorted(set(s))).to_dict()
        top = {lg["country"]: self._league_candidates(base, lg["country"]) for lg in self.cfg["leagues"].values()}
        rows = []
        for sd in sorted(root.glob("20*")):
            f = sd / "cl.txt"
            if not f.exists():
                continue
            year = int(sd.name[:4])
            stage, cur_date, cur_time = "", None, None
            for line in f.read_text(encoding="utf-8").splitlines():
                if line.startswith("▪"):
                    stage = line.strip("▪ ").strip()
                    continue
                dm = self._date_line.match(line)
                if dm and " v " not in line:
                    mon = dt.datetime.strptime(dm.group(2), "%b").month
                    y = int(dm.group(4)) if dm.group(4) else (year if mon >= 7 else year + 1)
                    cur_date = pd.Timestamp(y, mon, int(dm.group(3)))
                    continue
                mm = self._ucl_line.match(line)
                if not mm or cur_date is None:
                    continue
                t, h, hc, a, ac, rest = mm.groups()
                cur_time = t or cur_time
                sc = self._parse_ucl_score(rest)
                if sc is None:
                    continue
                hc, ac = UCL_COUNTRY.get(hc, hc), UCL_COUNTRY.get(ac, ac)
                hc = "ROM" if hc == "ROU" else hc
                ac = "ROM" if ac == "ROU" else ac
                hn = self.mapper.map(h.strip(), top.get(hc) or by_country.get(hc, []), f"UCL:{hc}")
                an = self.mapper.map(a.strip(), top.get(ac) or by_country.get(ac, []), f"UCL:{ac}")
                rows.append({"date": cur_date, "kickoff": cur_time, "comp": "UCL", "country": "EUR",
                             "tier": 0, "home": hn, "away": an, "hg": sc[0], "ag": sc[1],
                             "hthg": sc[2], "htag": sc[3], "neutral": stage.endswith("Final") and "Semi" not in stage
                             and "Quarter" not in stage, "stage": stage, "home_country": hc,
                             "away_country": ac, "source": f"openfootball-ucl:{sd.name}"})
        out = pd.DataFrame(rows)
        self.manifest["sources"]["openfootball_ucl"] = {
            "path": str(root), "repo": "github.com/openfootball/champions-league", **_git_meta(root),
            "rows": len(out), "max_date": str(out.date.max().date()) if len(out) else None,
            "note": "results only; no odds; 90-minute scores used for extra-time matches"}
        return out

    def load_clubelo(self):
        path = p(self.cfg, "cfmd_elo")
        e = pd.read_csv(path, parse_dates=["date"])
        self.manifest["sources"]["clubelo"] = {"path": str(path), "rows": int(len(e)),
                                               "max_date": str(e.date.max().date())}
        return e

    def load_fixture_input(self, allm):
        """Optional user fixtures (e.g. UCL matchdays): date,kickoff_local,tz,comp,home,away."""
        f = p(self.cfg, "fixtures_input")
        if not f.exists():
            return pd.DataFrame()
        x = pd.read_csv(f, parse_dates=["date"])
        teams = sorted(set(allm.home) | set(allm.away))
        out = pd.DataFrame({"date": x.date, "kickoff": x.kickoff_local, "tz": x.tz, "comp": x.comp,
                            "home": [self.mapper.map(t, teams, "fixtures") for t in x.home],
                            "away": [self.mapper.map(t, teams, "fixtures") for t in x.away],
                            "round": x.get("round"), "source": f"user:{f.name}"})
        out["country"] = np.where(out.comp == "UCL", "EUR", out.comp.map(
            {k: v["country"] for k, v in self.cfg["leagues"].items()}))
        self.manifest["sources"]["fixtures_input"] = {"path": str(f), "rows": len(out)}
        return out

    # ---------- assemble ----------
    def load_all(self):
        from .apidata import load_api_matches
        clubelo = self.load_clubelo()
        cf = self.load_cfmd()
        di = self.load_dropins()
        of_res, fixtures = self.load_openfootball(cf)
        cands = {c: self._league_candidates(cf, c) for c in cf.country.unique()}
        all_teams = sorted(set(cf.home) | set(clubelo.club))
        api_res, api_fx, self.team_map, api_meta = load_api_matches(self.cfg, self.mapper, cands, all_teams)
        if api_meta["files"]:
            self.manifest["sources"]["api_football"] = {
                "provider": self.cfg["api"]["provider"], "files": len(api_meta["files"]),
                "fetched_utc": max(x["fetched_utc"] or "" for x in api_meta["files"]),
                "results_rows": int(len(api_res)), "fixture_rows": int(len(api_fx)),
                "max_date": api_meta["latest_result"], "rejected_items": api_meta["rejected_items"]}
        ucl = self.load_ucl(cf, clubelo)
        api_ucl = api_res[api_res.comp == "UCL"] if len(api_res) else api_res
        api_dom = api_res[api_res.comp != "UCL"] if len(api_res) else api_res
        dom = pd.concat([x for x in (di, cf, api_dom, of_res) if len(x)], ignore_index=True)
        src = dom.source.astype(str)
        dom["_p"] = np.select([src.str.startswith("dropin"), src.eq("cfmd"), src.str.startswith("api")], [0, 1, 2], 3)
        dom["_wk"] = season_of(dom.date)
        dom = (dom.sort_values(["_p", "date"])
               .drop_duplicates(["_wk", "comp", "home", "away"], keep="first"))
        ucl_all = pd.concat([x for x in (api_ucl, ucl) if len(x)], ignore_index=True)
        if len(ucl_all):
            ucl_all["_wk"] = season_of(ucl_all.date)
            ucl_all = ucl_all.drop_duplicates(["date", "home", "away"], keep="first").drop(columns="_wk")
        allm = pd.concat([dom.drop(columns=["_p", "_wk"]), ucl_all], ignore_index=True)
        allm["neutral"] = allm["neutral"].fillna(False).astype(bool)
        allm["season"] = season_of(allm.date)
        for c in BASE_COLS + ODDS_COLS:
            if c not in allm:
                allm[c] = np.nan
        allm = allm.sort_values(["date", "comp", "home"]).reset_index(drop=True)
        allm["match_id"] = (allm.date.dt.strftime("%Y%m%d") + "_" + allm.comp + "_" +
                            allm.home.str.replace(" ", "") + "_" + allm.away.str.replace(" ", ""))
        allm = allm.drop_duplicates("match_id")
        # fixtures: API first (UTC kickoffs + fixture ids), then openfootball, then user file
        fx_parts = [x for x in (api_fx, fixtures, self.load_fixture_input(allm)) if len(x)]
        fixtures = pd.concat(fx_parts, ignore_index=True) if fx_parts else pd.DataFrame()
        if len(fixtures):
            fixtures["season"] = season_of(fixtures.date)
            fixtures = fixtures.drop_duplicates(["season", "comp", "home", "away"], keep="first")
            played = set(zip(allm.comp, allm.home, allm.away, allm.season))
            fixtures = fixtures[[k not in played for k in zip(fixtures.comp, fixtures.home, fixtures.away, fixtures.season)]]
        self.manifest["unmapped_names"] = sorted(f"{s}:{r}" for s, r in self.mapper.unmapped)
        return allm, fixtures.reset_index(drop=True), clubelo

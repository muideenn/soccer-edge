"""Team-name reconciliation. Canonical names are the football-data.co.uk / ClubElo spellings."""
import difflib
import re
import unicodedata

import yaml

STOP = {
    "fc", "cf", "ac", "afc", "sc", "ssc", "as", "us", "rc", "rcd", "ca", "ud", "sv", "tsg", "fsv",
    "cfc", "bc", "acf", "ss", "osc", "ogc", "sco", "aj", "es", "sk", "fk", "kv", "vfb", "vfl",
    "club", "de", "del", "calcio", "futbol", "football", "the", "sd", "cd", "rsc", "psv_", "bk",
    "if", "ff", "nk", "gnk", "hnk", "pfc", "fcsb", "sfp", "pae", "real_", "balompie", "sport",
    "lisboa", "e", "clube", "cp", "olympique_", "stade_", "racing_", "and", "hove", "albion",
    "town", "city_", "united_", "athletic_", "hotspur", "wanderers", "1909", "1913", "1907", "1901",
    "04", "05", "07", "29", "1899", "1846", "1848",
}
UCL_COUNTRY = {"MCO": "FRA", "WAL": "ENG", "LIE": "SUI"}


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    toks = [t for t in s.split() if t not in STOP and not t.isdigit()]
    return " ".join(toks) or s.strip()


class NameMapper:
    def __init__(self, alias_path):
        with open(alias_path) as f:
            self.alias = yaml.safe_load(f) or {}
        self.unmapped = set()
        self._cache = {}

    def map(self, raw, candidates, scope=""):
        key = (raw, scope)
        if key in self._cache:
            return self._cache[key]
        if raw in self.alias:
            out = self.alias[raw]
        elif raw in candidates:
            out = raw
        else:
            cn = {norm(c): c for c in candidates}
            r = norm(raw)
            if r in cn:
                out = cn[r]
            else:
                # token containment first ("bayer leverkusen" vs "leverkusen")
                hits = [c for n, c in cn.items() if n and (n in r.split() or n == r or set(n.split()) <= set(r.split()))]
                if len(hits) == 1:
                    out = hits[0]
                else:
                    m = difflib.get_close_matches(r, list(cn), n=1, cutoff=0.78)
                    out = cn[m[0]] if m else None
            if out is None:
                self.unmapped.add((scope, raw))
                out = raw
        self._cache[key] = out
        return out

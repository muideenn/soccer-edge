import { useEffect, useState } from "react";

const BASE = import.meta.env.BASE_URL;

export function useJson<T>(name: string): { data: T | null; error: string | null } {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    fetch(`${BASE}data/${name}.json`, { cache: "no-cache" })
      .then((r) => {
        if (!r.ok) throw new Error(`${name}.json: HTTP ${r.status}`);
        return r.json();
      })
      .then(setData)
      .catch((e) => setError(String(e)));
  }, [name]);
  return { data, error };
}

export const pct = (x: number | null | undefined, d = 0) =>
  x === null || x === undefined || Number.isNaN(x) ? "–" : `${(x * 100).toFixed(d)}%`;
export const signedPct = (x: number | null | undefined, d = 1) =>
  x === null || x === undefined || Number.isNaN(x) ? "–" : `${x >= 0 ? "+" : "−"}${Math.abs(x * 100).toFixed(d)}%`;
export const fair = (p: number | null | undefined) => (p ? (1 / p).toFixed(2) : "–");
export const fmt = (x: number | null | undefined, d = 2) =>
  x === null || x === undefined || Number.isNaN(x) ? "–" : x.toFixed(d);

export const LEAGUE_LABEL: Record<string, string> = {
  EPL: "Premier League",
  LaLiga: "La Liga",
  Bundesliga: "Bundesliga",
  SerieA: "Serie A",
  Ligue1: "Ligue 1",
  UCL: "Champions League",
};

export const MARKET_LABEL: Record<string, string> = {
  "1X2": "Match result",
  OU: "Total goals",
  AH: "Asian handicap",
  BTTS: "Both teams score",
  DC: "Double chance",
  DNB: "Draw no bet",
  TT_HOME: "Home team total",
  TT_AWAY: "Away team total",
  CORNERS: "Total corners",
};

export function selectionLabel(s: { market: string; selection: string; line: number | null }, home: string, away: string) {
  const side = (x: string) => (x === "H" || x === "home" ? home : x === "A" || x === "away" ? away : x);
  const ln = s.line === null || s.line === undefined ? "" : ` ${s.line > 0 && s.market === "AH" ? "+" : ""}${s.line}`;
  if (s.market === "1X2") return s.selection === "D" ? "Draw" : side(s.selection);
  if (s.market === "AH") return `${side(s.selection)}${ln}`;
  if (s.market === "OU") return `${s.selection === "over" ? "Over" : "Under"}${ln} goals`;
  if (s.market === "CORNERS") return `${s.selection === "over" ? "Over" : "Under"}${ln} corners`;
  if (s.market === "TT_HOME") return `${home} ${s.selection === "over" ? "over" : "under"}${ln}`;
  if (s.market === "TT_AWAY") return `${away} ${s.selection === "over" ? "over" : "under"}${ln}`;
  if (s.market === "BTTS") return s.selection === "yes" ? "Yes" : "No";
  if (s.market === "DNB") return side(s.selection);
  if (s.market === "DC") return s.selection === "1X" ? `${home} or draw` : s.selection === "X2" ? `Draw or ${away}` : "Either team wins";
  return s.selection;
}

export const timeAgo = (iso: string | null | undefined) => {
  if (!iso) return "unknown time";
  const m = Math.round((Date.now() - Date.parse(iso)) / 60000);
  if (!Number.isFinite(m)) return iso;
  if (m < 1) return "just now";
  if (m < 60) return `${m} min ago`;
  const h = Math.round(m / 60);
  return h < 48 ? `${h} h ago` : `${Math.round(h / 24)} days ago`;
};

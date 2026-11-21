/**
 * Parlay maths.
 *
 * - Legs are only eligible if they cannot push or half-settle (1X2, double chance, BTTS, and
 *   x.5 lines for totals / team totals / handicaps / corners), so a parlay leg either wins or loses.
 * - Legs from the same match are combined EXACTLY using that match's score grid (goals) or
 *   corner grid (corners). Goal legs and corner legs from the same match are treated as
 *   independent, and legs from different matches are treated as independent: those parts are
 *   approximations and are labelled as such.
 */
import type { Fixture, Selection } from "./types";

export interface Leg {
  id: string;
  match_id: string;
  fixture: string;
  comp: string;
  date: string;
  kickoff: string;
  home: string;
  away: string;
  market: string;
  selection: string;
  line: number | null;
  odds: number;
  book: string;
  timestamp: string | null;
  p: number;              // model probability the leg wins (market-anchored where odds exist)
  implied: number;        // 1 / odds (includes bookmaker margin)
  ev: number;             // p * odds - 1
  demo: boolean;
  stale: boolean;
  unvalidated: boolean;   // corners: no historical corner odds to validate rules
}

export const PUSH_FREE_MARKETS = ["1X2", "DC", "BTTS", "OU", "TT_HOME", "TT_AWAY", "AH", "CORNERS"];

export function legId(match_id: string, s: { market: string; selection: string; line: number | null }) {
  return `${match_id}|${s.market}|${s.selection}|${s.line ?? ""}`;
}

export function isHalfLine(line: number | null) {
  return line !== null && Math.abs((Math.abs(line) % 1) - 0.5) < 1e-9;
}

export function eligible(s: Selection) {
  if (!PUSH_FREE_MARKETS.includes(s.market)) return false;
  if (["OU", "TT_HOME", "TT_AWAY", "AH", "CORNERS"].includes(s.market)) return isHalfLine(s.line);
  return true;
}

export function toLeg(f: Fixture, s: Selection): Leg {
  return {
    id: legId(f.match_id, s), match_id: f.match_id, fixture: `${f.home} v ${f.away}`, comp: f.comp, date: f.date,
    kickoff: f.kickoff_user_tz, home: f.home, away: f.away, market: s.market, selection: s.selection, line: s.line,
    odds: s.odds, book: s.odds_source, timestamp: s.odds_timestamp, p: s.model_p, implied: s.implied_p,
    ev: s.model_p * s.odds - 1, demo: !!(s.demo || f.odds_are_demo), stale: !f.data_ok,
    unvalidated: s.market === "CORNERS",
  };
}

/** Does the leg win at final score (i home goals/corners, j away)? */
export function wins(l: Pick<Leg, "market" | "selection" | "line">, i: number, j: number): boolean {
  const L = l.line ?? 0;
  switch (l.market) {
    case "1X2": return l.selection === "H" ? i > j : l.selection === "A" ? i < j : i === j;
    case "DC": return l.selection === "1X" ? i >= j : l.selection === "X2" ? i <= j : i !== j;
    case "BTTS": return l.selection === "yes" ? i > 0 && j > 0 : !(i > 0 && j > 0);
    case "OU": case "CORNERS": return l.selection === "over" ? i + j > L : i + j < L;
    case "TT_HOME": return l.selection === "over" ? i > L : i < L;
    case "TT_AWAY": return l.selection === "over" ? j > L : j < L;
    case "AH": return l.selection === "home" ? i - j + L > 0 : j - i + L > 0;
    default: return false;
  }
}

function gridJoint(grid: number[][], legs: Leg[]) {
  let tot = 0, hit = 0;
  for (let i = 0; i < grid.length; i++)
    for (let j = 0; j < grid[i].length; j++) {
      const v = grid[i][j];
      tot += v;
      if (legs.every((l) => wins(l, i, j))) hit += v;
    }
  return tot > 0 ? hit / tot : NaN;
}

export interface Combined {
  legs: number;
  odds: number;
  pIndependent: number;     // naive product of leg probabilities
  p: number;                // with same-match correlation modelled where grids exist
  ev: number;
  method: "independent" | "partially-modelled";
  notes: string[];
  risk: Risk;
}

export function combine(legs: Leg[], fixtures: Map<string, Fixture>): Combined {
  const odds = legs.reduce((a, l) => a * l.odds, 1);
  const pInd = legs.reduce((a, l) => a * l.p, 1);
  const notes: string[] = [];
  let p = 1;
  let modelled = false;
  const byMatch = new Map<string, Leg[]>();
  legs.forEach((l) => byMatch.set(l.match_id, [...(byMatch.get(l.match_id) ?? []), l]));
  for (const [mid, ls] of byMatch) {
    const f = fixtures.get(mid);
    const goal = ls.filter((l) => l.market !== "CORNERS");
    const corner = ls.filter((l) => l.market === "CORNERS");
    let pm = 1;
    if (goal.length > 1 && f?.joint_grid) { pm *= gridJoint(f.joint_grid, goal); modelled = true; }
    else pm *= goal.reduce((a, l) => a * l.p, 1);
    if (corner.length > 1 && f?.corner_grid) { pm *= gridJoint(f.corner_grid, corner); modelled = true; }
    else pm *= corner.reduce((a, l) => a * l.p, 1);
    if (goal.length && corner.length) notes.push(`${ls[0].fixture}: goal and corner legs treated as independent (approximation).`);
    p *= pm;
  }
  if (byMatch.size > 1) notes.push("Legs from different matches are treated as independent. Real outcomes can be correlated (weather, schedule, shared news), so the combined chance is an approximation.");
  if (modelled) notes.push("Legs from the same match are combined exactly from that match's simulated score grid, so correlation within a match is modelled.");
  if (legs.some((l) => l.unvalidated)) notes.push("Includes corner legs: corner probabilities are tested, but corner betting has no historical odds to validate it.");
  if (legs.some((l) => l.stale)) notes.push("Some legs come from matches whose ratings are stale (recent results missing).");
  if (legs.some((l) => l.demo)) notes.push("Demo mode: odds are synthetic, not real bookmaker prices.");
  notes.push("Bookmakers may price or refuse same-match combinations differently from the simple product of odds shown here.");
  return { legs: legs.length, odds, pIndependent: pInd, p, ev: p * odds - 1, method: modelled ? "partially-modelled" : "independent", notes, risk: riskRating(p, legs.length) };
}

export interface Risk { level: 1 | 2 | 3 | 4 | 5; label: string; icon: string; text: string }

/** Never labels a 10+ leg parlay below "Very high" risk; a parlay is never "low risk". */
export function riskRating(p: number, n: number): Risk {
  let level: Risk["level"] = p >= 0.6 ? 1 : p >= 0.35 ? 2 : p >= 0.15 ? 3 : p >= 0.03 ? 4 : 5;
  if (n >= 10 && level < 3) level = 3;
  if (n >= 2 && level < 2) level = 2;
  const table: Record<number, Omit<Risk, "level">> = {
    1: { label: "Elevated", icon: "▲", text: "A single selection can still lose." },
    2: { label: "High", icon: "▲▲", text: "Loses more often than many people expect." },
    3: { label: "Very high", icon: "▲▲▲", text: "Most likely outcome is a loss." },
    4: { label: "Extreme", icon: "▲▲▲▲", text: "Loses the large majority of the time." },
    5: { label: "Lottery-like", icon: "▲▲▲▲▲", text: "Almost always loses; any payout is rare." },
  };
  return { level, ...table[level] };
}

export type Objective = "probability" | "value" | "balanced";

export interface Criteria {
  minLegs: number;
  maxLegs: number;
  minOdds: number;
  maxOdds: number;
  minLegP: number;
  comps: Set<string>;
  markets: Set<string>;
  includeTeams: string;    // comma separated, optional
  excludeTeams: string;
  objective: Objective;
  balance: number;         // 0 = pure probability, 1 = pure value
  requirePositiveEV: boolean;
  excludeStale: boolean;
  excludeUnvalidated: boolean;
}

const norm = (s: string) => s.toLowerCase().trim();

export function filterLegs(pool: Leg[], c: Criteria) {
  const inc = c.includeTeams.split(",").map(norm).filter(Boolean);
  const exc = c.excludeTeams.split(",").map(norm).filter(Boolean);
  const hasTeam = (l: Leg, list: string[]) => list.some((t) => norm(l.home).includes(t) || norm(l.away).includes(t));
  return pool.filter((l) =>
    l.odds >= c.minOdds && l.odds <= c.maxOdds && l.p >= c.minLegP &&
    (!c.comps.size || c.comps.has(l.comp)) && (!c.markets.size || c.markets.has(l.market)) &&
    (!inc.length || hasTeam(l, inc)) && !hasTeam(l, exc) &&
    !(c.excludeStale && l.stale) && !(c.excludeUnvalidated && l.unvalidated));
}

export function legScore(l: Leg, obj: Objective, balance: number) {
  const lp = Math.log(Math.max(l.p, 1e-9));
  const lv = Math.log(Math.max(l.p * l.odds, 1e-9));
  if (obj === "probability") return lp;
  if (obj === "value") return lv;
  return (1 - balance) * lp + balance * lv;
}

/**
 * With at most one leg per match, the combined score is a sum of per-leg scores, so taking the
 * best leg from each match and then the top-n matches is the exact optimum for that objective.
 */
export function buildCandidates(pool: Leg[], c: Criteria, fixtures: Map<string, Fixture>) {
  const legs = filterLegs(pool, c);
  const best = new Map<string, Leg>();
  for (const l of legs) {
    const cur = best.get(l.match_id);
    if (!cur || legScore(l, c.objective, c.balance) > legScore(cur, c.objective, c.balance)) best.set(l.match_id, l);
  }
  const ranked = [...best.values()].sort((a, b) => legScore(b, c.objective, c.balance) - legScore(a, c.objective, c.balance));
  const out: { legs: Leg[]; combined: Combined }[] = [];
  for (let n = c.minLegs; n <= Math.min(c.maxLegs, ranked.length); n++) {
    const ls = ranked.slice(0, n);
    const combined = combine(ls, fixtures);
    if (c.requirePositiveEV && combined.ev <= 0) continue;
    out.push({ legs: ls, combined });
  }
  return { eligibleLegs: legs.length, matches: best.size, candidates: out };
}

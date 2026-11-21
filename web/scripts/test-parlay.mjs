// Unit tests for the parlay engine (run: npm test). Bundles src/parlay.ts with esbuild, no extra deps.
import { build } from "esbuild";
import assert from "node:assert/strict";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";

const dir = mkdtempSync(join(tmpdir(), "parlay-"));
const out = join(dir, "parlay.mjs");
await build({ entryPoints: ["src/parlay.ts"], bundle: true, format: "esm", platform: "node", outfile: out, logLevel: "silent" });
const P = await import(pathToFileURL(out).href);

// independent Poisson grid helper
const pois = (l, k) => Math.exp(-l) * l ** k / [1, 1, 2, 6, 24, 120, 720, 5040, 40320][k];
const grid = (lh, la) => Array.from({ length: 9 }, (_, i) => Array.from({ length: 9 }, (_, j) => pois(lh, i) * pois(la, j)));
const g = grid(1.6, 1.0);
const fx = new Map([["m1", { match_id: "m1", joint_grid: g }], ["m2", { match_id: "m2", joint_grid: grid(1.2, 1.2) }]]);
const sum = (f) => { let s = 0, t = 0; g.forEach((r, i) => r.forEach((v, j) => { t += v; if (f(i, j)) s += v; })); return s / t; };
const leg = (o) => ({ id: `${o.match_id}|${o.market}|${o.selection}|${o.line ?? ""}`, fixture: o.match_id, comp: "EPL", date: "2026-11-21", kickoff: "", home: "H", away: "A", book: "B", timestamp: null, demo: false, stale: false, unvalidated: false, implied: 1 / o.odds, ev: o.p * o.odds - 1, ...o });

// 1. same-match legs combined exactly from the grid (positively correlated: home win & over 2.5)
const a = leg({ match_id: "m1", market: "1X2", selection: "H", line: null, odds: 1.9, p: sum((i, j) => i > j) });
const b = leg({ match_id: "m1", market: "OU", selection: "over", line: 2.5, odds: 2.0, p: sum((i, j) => i + j > 2.5) });
const c = P.combine([a, b], fx);
assert.ok(Math.abs(c.p - sum((i, j) => i > j && i + j > 2.5)) < 1e-9, "joint from grid");
assert.ok(c.p > a.p * b.p, "home win and over 2.5 are positively correlated");
assert.equal(c.method, "partially-modelled");

// 2. different matches: independence, labelled as approximation
const d = leg({ match_id: "m2", market: "BTTS", selection: "yes", line: null, odds: 1.8, p: 0.5 });
const c2 = P.combine([a, d], fx);
assert.ok(Math.abs(c2.p - a.p * 0.5) < 1e-12);
assert.ok(c2.notes.some((n) => n.includes("independent")));
assert.ok(Math.abs(c2.odds - 1.9 * 1.8) < 1e-12);

// 3. risk: 10+ legs never below "Very high", even at a high combined probability
assert.ok(P.riskRating(0.9, 12).level >= 3);
assert.ok(P.riskRating(0.9, 2).level >= 2);
assert.equal(P.riskRating(0.01, 15).label, "Lottery-like");

// 4. push-capable lines are not eligible
assert.equal(P.eligible({ market: "AH", selection: "home", line: -0.25 }), false);
assert.equal(P.eligible({ market: "OU", selection: "over", line: 3.0 }), false);
assert.equal(P.eligible({ market: "OU", selection: "over", line: 2.5 }), true);
assert.equal(P.eligible({ market: "DNB", selection: "H", line: null }), false);

// 5. candidate builder: one leg per match, exact top-n, EV filter can return nothing
const pool = [];
for (let m = 0; m < 25; m++) {
  pool.push(leg({ match_id: `x${m}`, market: "1X2", selection: "H", line: null, odds: 1.3 + m * 0.01, p: 0.72 - m * 0.002 }));
  pool.push(leg({ match_id: `x${m}`, market: "OU", selection: "over", line: 1.5, odds: 1.25, p: 0.76 }));
}
const crit = { minLegs: 10, maxLegs: 20, minOdds: 1.01, maxOdds: 3, minLegP: 0.5, comps: new Set(), markets: new Set(), includeTeams: "", excludeTeams: "", objective: "probability", balance: 0.5, requirePositiveEV: false, excludeStale: false, excludeUnvalidated: false };
const r = P.buildCandidates(pool, crit, new Map());
assert.equal(r.matches, 25);
assert.equal(r.candidates.length, 11);
for (const cand of r.candidates) assert.equal(new Set(cand.legs.map((l) => l.match_id)).size, cand.legs.length);
assert.ok(r.candidates[0].legs.every((l) => l.market === "OU"), "highest-probability leg chosen per match");
const r2 = P.buildCandidates(pool, { ...crit, requirePositiveEV: true }, new Map());
assert.equal(r2.candidates.length, 0, "all legs negative EV -> no candidate");
console.log("parlay tests: all passed");

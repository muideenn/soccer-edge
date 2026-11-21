import { useMemo, useState } from "react";
import { MiniLine } from "../components/charts";
import ParlayCard from "../components/ParlayCard";
import { Empty, Tip } from "../components/ui";
import { LEAGUE_LABEL, MARKET_LABEL, pct, signedPct } from "../data";
import { buildCandidates, type Criteria, type Leg, type Objective } from "../parlay";
import type { Fixture, Meta } from "../types";

const OBJ: Record<Objective, { title: string; text: string }> = {
  probability: { title: "Highest chance", text: "Picks the most likely leg in each match. Shortest odds, smallest payout, still usually loses at 10+ legs." },
  value: { title: "Best expected value", text: "Picks legs where the model is most optimistic relative to the price. Longer odds, lower chance of winning." },
  balanced: { title: "Balanced", text: "Trades chance against value using the slider. 0 = chance only, 1 = value only." },
};

function toggle(s: Set<string>, v: string) { const n = new Set(s); if (n.has(v)) n.delete(v); else n.add(v); return n; }

export default function Featured({ pool, fixtures, comps, meta }: { pool: Leg[]; fixtures: Map<string, Fixture>; comps: string[]; meta: Meta }) {
  const markets = [...new Set(pool.map((l) => l.market))];
  const [c, setC] = useState<Criteria>({
    minLegs: 10, maxLegs: 20, minOdds: 1.1, maxOdds: 2.2, minLegP: 0.5, comps: new Set(), markets: new Set(),
    includeTeams: "", excludeTeams: "", objective: "balanced", balance: 0.5, requirePositiveEV: true,
    excludeStale: !meta.demo, excludeUnvalidated: false,
  });
  const res = useMemo(() => buildCandidates(pool, c, fixtures), [pool, c, fixtures]);
  const score = (x: (typeof res.candidates)[0]) => {
    const lp = Math.log(Math.max(x.combined.p, 1e-12)), lv = Math.log(Math.max(x.combined.p * x.combined.odds, 1e-12));
    return c.objective === "probability" ? lp : c.objective === "value" ? lv : (1 - c.balance) * lp + c.balance * lv;
  };
  const ranked = [...res.candidates].sort((a, b) => score(b) - score(a)).slice(0, 3);
  // how chance and EV evolve with leg count, ignoring the EV filter (for the tradeoff chart)
  const curve = useMemo(() => buildCandidates(pool, { ...c, requirePositiveEV: false }, fixtures).candidates, [pool, c, fixtures]);
  const set = (k: Partial<Criteria>) => setC((o) => ({ ...o, ...k }));
  return (
    <>
      <h1 className="page-title">Featured 10–20 leg parlays</h1>
      <div className="banner warn" role="note">
        <b>⚠ Read this first.</b> A 10–20 leg parlay is a <b>very high to lottery-like risk</b> bet. Even with every leg at 80%, a 10-leg parlay wins about 11% of the time and a 20-leg parlay about 1%. Every bookmaker margin compounds, so expected value is usually negative. Nothing here is low risk or likely to win. Treat it as entertainment priced in probabilities, not income.
      </div>
      {meta.demo && <div className="banner warn" role="note"><b>⚠ Demo prices.</b> Odds here are synthetic (model probability plus a bookmaker-style margin), so any expected value shown is an artefact, not a real opportunity. Connect live odds to use this page.</div>}
      <section className="glass pad criteria" aria-label="Parlay criteria">
        <div className="crit-grid">
          <label className="field"><span>Legs: {c.minLegs}–{c.maxLegs}</span>
            <div className="row">
              <input type="range" min={10} max={20} value={c.minLegs} aria-label="Minimum legs" onChange={(e) => set({ minLegs: Math.min(Number(e.target.value), c.maxLegs) })} />
              <input type="range" min={10} max={20} value={c.maxLegs} aria-label="Maximum legs" onChange={(e) => set({ maxLegs: Math.max(Number(e.target.value), c.minLegs) })} />
            </div>
          </label>
          <fieldset className="field odds"><legend>Odds per leg</legend>
            <input type="number" step={0.05} min={1.01} value={c.minOdds} aria-label="Minimum odds per leg" onChange={(e) => set({ minOdds: Number(e.target.value) || 1.01 })} /><span aria-hidden="true">–</span>
            <input type="number" step={0.05} min={1.01} value={c.maxOdds} aria-label="Maximum odds per leg" onChange={(e) => set({ maxOdds: Number(e.target.value) || 2 })} />
          </fieldset>
          <label className="field"><span>Min. probability per leg: {pct(c.minLegP)}</span>
            <input type="range" min={0.3} max={0.95} step={0.05} value={c.minLegP} onChange={(e) => set({ minLegP: Number(e.target.value) })} /></label>
          <label className="field"><span>Include teams (comma separated)</span><input value={c.includeTeams} onChange={(e) => set({ includeTeams: e.target.value })} placeholder="optional" /></label>
          <label className="field"><span>Exclude teams</span><input value={c.excludeTeams} onChange={(e) => set({ excludeTeams: e.target.value })} placeholder="optional" /></label>
        </div>
        <div className="chiprow" role="group" aria-label="Competitions (none selected = all)">
          {comps.map((x) => <button key={x} className={`chip ${c.comps.has(x) ? "on" : ""}`} aria-pressed={c.comps.has(x)} onClick={() => set({ comps: toggle(c.comps, x) })}>{LEAGUE_LABEL[x] ?? x}</button>)}
        </div>
        <div className="chiprow" role="group" aria-label="Markets (none selected = all)">
          {markets.map((m) => <button key={m} className={`chip small ${c.markets.has(m) ? "on" : ""}`} aria-pressed={c.markets.has(m)} onClick={() => set({ markets: toggle(c.markets, m) })}>{MARKET_LABEL[m] ?? m}</button>)}
        </div>
        <fieldset className="objectives"><legend>Rank by</legend>
          {(Object.keys(OBJ) as Objective[]).map((o) => (
            <label key={o} className={`obj ${c.objective === o ? "on" : ""}`}>
              <input type="radio" name="obj" checked={c.objective === o} onChange={() => set({ objective: o })} />
              <b>{OBJ[o].title}</b><span className="small muted">{OBJ[o].text}</span>
            </label>
          ))}
        </fieldset>
        {c.objective === "balanced" && <label className="field inline"><span>Chance ⟷ value: {c.balance.toFixed(2)}</span><input type="range" min={0} max={1} step={0.05} value={c.balance} onChange={(e) => set({ balance: Number(e.target.value) })} /></label>}
        <div className="row wrap">
          <label className="check"><input type="checkbox" checked={c.requirePositiveEV} onChange={(e) => set({ requirePositiveEV: e.target.checked })} /> Only show parlays with positive <Tip term="expected value" /></label>
          <label className="check"><input type="checkbox" checked={c.excludeStale} onChange={(e) => set({ excludeStale: e.target.checked })} /> Exclude matches with <Tip term="stale data" /></label>
          <label className="check"><input type="checkbox" checked={c.excludeUnvalidated} onChange={(e) => set({ excludeUnvalidated: e.target.checked })} /> Exclude <Tip term="corners">corner legs</Tip></label>
        </div>
        <p className="small muted">How candidates are built: one leg per match (so legs from different matches are the only combination, and the independence approximation is stated), best leg per match under your ranking rule, then the top 10–20 matches. Under that rule this is the exact optimum. {res.eligibleLegs} legs from {res.matches} matches pass your filters.</p>
      </section>

      {res.matches < c.minLegs ? (
        <Empty title={`Not enough eligible matches for ${c.minLegs} legs`}>
          <p>Only {res.matches} matches have a leg inside your criteria. Widen the odds range, lower the minimum leg probability, add competitions, or include stale matches.</p>
        </Empty>
      ) : !ranked.length ? (
        <Empty title="No parlay meets your criteria">
          <p>None of the {c.minLegs}–{c.maxLegs} leg combinations has positive expected value under the model{meta.demo ? " (demo prices)" : ""}. That is the normal result: bookmaker margins compound across legs. You can untick “Only show parlays with positive expected value” to see the best negative-EV candidates, clearly labelled.</p>
        </Empty>
      ) : (
        <div className="stack">
          {ranked.map((x, k) => <ParlayCard key={x.legs.map((l) => l.id).join()} rank={k} title={`#${k + 1} · ${OBJ[c.objective].title} · ${x.legs.length} legs`} legs={x.legs} c={x.combined} />)}
        </div>
      )}

      {curve.length > 1 && (
        <section className="glass pad">
          <h2 className="h3">The tradeoff: payout vs. chance of winning</h2>
          <div className="grid3">
            <MiniLine xs={curve.map((x) => x.legs.length)} ys={curve.map((x) => x.combined.p * 100)} fmt={(v) => `${v.toFixed(v < 10 ? 1 : 0)}%`} label="Estimated chance of winning (%)" />
            <MiniLine xs={curve.map((x) => x.legs.length)} ys={curve.map((x) => x.combined.odds)} fmt={(v) => (v >= 100 ? v.toFixed(0) : v.toFixed(1))} label="Combined decimal odds" />
            <MiniLine xs={curve.map((x) => x.legs.length)} ys={curve.map((x) => x.combined.ev * 100)} fmt={(v) => `${v.toFixed(0)}%`} label="Expected value per unit (%)" />
          </div>
          <p className="small muted">Built from the same ranked legs, adding one match at a time. More legs mean a bigger payout and a much smaller chance; expected value is {curve.at(-1)!.combined.ev < 0 ? `negative (${signedPct(curve.at(-1)!.combined.ev)} at ${curve.at(-1)!.legs.length} legs)` : "positive under the model, which is only as reliable as its estimates"}.</p>
        </section>
      )}
    </>
  );
}

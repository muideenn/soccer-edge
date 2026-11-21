import { useMemo, useState } from "react";
import { MiniLine } from "../components/charts";
import { LegTable, ParlayStats } from "../components/ParlayCard";
import { Empty, Tip } from "../components/ui";
import { fmt, pct } from "../data";
import { combine } from "../parlay";
import { useSlip } from "../store";
import type { Fixture } from "../types";

export default function Builder({ fixtures }: { fixtures: Map<string, Fixture> }) {
  const slip = useSlip();
  const [stake, setStake] = useState(1);
  const c = useMemo(() => (slip.legs.length ? combine(slip.legs, fixtures) : null), [slip.legs, fixtures]);
  // cumulative curve: chance and payout as legs are added in slip order
  const curve = useMemo(() => slip.legs.map((_, k) => combine(slip.legs.slice(0, k + 1), fixtures)), [slip.legs, fixtures]);
  return (
    <>
      <h1 className="page-title">Parlay builder</h1>
      <p className="lead">Add selections from <a href="#/singles">Singles</a>, a match panel, or a <a href="#/featured">featured parlay</a>. Only legs that cannot push are allowed. Every leg must win.</p>
      <div className="banner warn small" role="note"><b>⚠ Parlays usually lose.</b> Each added leg multiplies the payout but also multiplies the chance of losing, and the bookmaker's margin compounds with every leg. Estimates are uncertain. Never stake money you need, and never chase losses.</div>
      {!c ? (
        <Empty title="Your slip is empty"><p>Pick legs from <a href="#/singles">Singles</a> or load a <a href="#/featured">featured parlay</a>.</p></Empty>
      ) : (
        <>
          <section className="glass pad" aria-live="polite">
            <div className="row between">
              <h2 className="h3">{slip.legs.length}-leg parlay</h2>
              <button className="btn" onClick={slip.clear}>Clear slip</button>
            </div>
            <ParlayStats c={c} />
            <div className="row wrap">
              <label className="field inline"><span>Stake (units)</span><input type="number" min={0} step={0.5} value={stake} onChange={(e) => setStake(Math.max(0, Number(e.target.value) || 0))} /></label>
              <p className="small">If every leg wins: return <b>{fmt(stake * c.odds)}</b> units (profit {fmt(stake * (c.odds - 1))}). Estimated chance {pct(c.p, c.p < 0.01 ? 2 : 1)}; average result per bet if the model is right: <b className={c.ev > 0 ? "pos" : "neg"}>{fmt(stake * c.ev)}</b> units.</p>
            </div>
            {c.method === "partially-modelled" && Math.abs(c.p - c.pIndependent) > 1e-4 && (
              <p className="small"><Tip term="independence">Correlation check</Tip> Simply multiplying the leg probabilities would say {pct(c.pIndependent, 2)}; modelling same-match dependence gives {pct(c.p, 2)}.</p>
            )}
          </section>
          <section className="glass pad">
            <h2 className="h3">Legs</h2>
            <LegTable legs={slip.legs} removable />
          </section>
          {curve.length > 1 && (
            <section className="glass pad">
              <h2 className="h3">Payout vs. chance as legs are added</h2>
              <div className="grid2">
                <MiniLine xs={curve.map((_, k) => k + 1)} ys={curve.map((x) => x.p * 100)} fmt={(v) => `${v.toFixed(v < 10 ? 1 : 0)}%`} label="Estimated chance of winning (%) by number of legs" highlight={curve.length} />
                <MiniLine xs={curve.map((_, k) => k + 1)} ys={curve.map((x) => x.odds)} fmt={(v) => (v >= 100 ? v.toFixed(0) : v.toFixed(1))} label="Combined decimal odds by number of legs" highlight={curve.length} />
              </div>
              <p className="small muted">Two separate charts on purpose: chance falls roughly geometrically while the payout climbs, and expected value usually falls with each leg because every price carries a margin.</p>
            </section>
          )}
          <details className="glass pad notes" open><summary>Assumptions</summary><ul>{c.notes.map((n) => <li key={n}>{n}</li>)}</ul></details>
        </>
      )}
    </>
  );
}

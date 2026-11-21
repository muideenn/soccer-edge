import { useMemo, useState } from "react";
import { OddsScatter } from "../components/charts";
import Filters, { emptyFilters, type FilterState } from "../components/Filters";
import { Empty, Tip } from "../components/ui";
import { LEAGUE_LABEL, MARKET_LABEL, fmt, pct, selectionLabel, signedPct, timeAgo } from "../data";
import { eligible, toLeg, type Leg } from "../parlay";
import { useSlip } from "../store";
import type { Matchday } from "../types";
import { matchFilter } from "./Today";

type SortKey = "ev" | "p" | "odds" | "kickoff";

export default function Singles({ md }: { md: Matchday }) {
  const [f, setF] = useState<FilterState>(emptyFilters());
  const [sort, setSort] = useState<SortKey>("ev");
  const [onlyBets, setOnlyBets] = useState(false);
  const [limit, setLimit] = useState(60);
  const slip = useSlip();
  const dates = useMemo(() => [...new Set(md.fixtures.map((x) => x.date))].sort(), [md]);
  const comps = md.leagues.filter((l) => md.fixtures.some((x) => x.comp === l));
  const markets = [...new Set(md.fixtures.flatMap((x) => x.selections.map((s) => s.market)))];
  const rows = useMemo(() => {
    const fm = matchFilter(f);
    const out: { leg: Leg; ok: boolean; decision: string; reason: string; kickoff: string }[] = [];
    for (const fx of md.fixtures.filter(fm))
      for (const s of fx.selections) {
        if (f.markets.size && !f.markets.has(s.market)) continue;
        if (s.odds < f.minOdds || s.odds > f.maxOdds) continue;
        if (onlyBets && s.decision !== "BET") continue;
        out.push({ leg: toLeg(fx, s), ok: eligible(s), decision: s.decision, reason: s.reason, kickoff: fx.kickoff_utc ?? fx.date });
      }
    const key: Record<SortKey, (r: (typeof out)[0]) => number> = {
      ev: (r) => -r.leg.ev, p: (r) => -r.leg.p, odds: (r) => -r.leg.odds, kickoff: (r) => Date.parse(r.kickoff) || 0,
    };
    return out.sort((a, b) => key[sort](a) - key[sort](b));
  }, [md, f, sort, onlyBets]);
  const byId = new Map(rows.map((r) => [r.leg.id, r]));
  return (
    <>
      <h1 className="page-title">Singles</h1>
      <p className="lead">Every priced selection at the best available odds, with the model's probability next to the price's <Tip term="implied probability" />. A positive <Tip term="expected value" /> only means the model is more optimistic than the price — the backtest found the market usually right.</p>
      <Filters f={f} set={setF} dates={dates} comps={comps} markets={markets} />
      <div className="grid2">
        <div className="glass pad">
          <h2 className="h3">Probability vs price</h2>
          {rows.length ? <OddsScatter points={rows.slice(0, 400).map((r) => ({ id: r.leg.id, x: r.leg.implied, y: r.leg.p, label: `${r.leg.fixture}: ${selectionLabel(r.leg, r.leg.home, r.leg.away)}`, sub: `${MARKET_LABEL[r.leg.market]} @ ${fmt(r.leg.odds)} (${r.leg.book})`, eligible: r.ok }))}
            onPick={(id) => { const r = byId.get(id); if (r) slip.toggle(r.leg); }} isOn={slip.has} /> : <Empty title="Nothing to plot" />}
          <p className="small muted">Click or press Enter on a point to add it to the parlay slip. Showing up to 400 points.</p>
        </div>
        <div className="glass pad">
          <h2 className="h3">Reading the chart</h2>
          <ul className="small">
            <li>The dashed diagonal is where the model agrees with the bookmaker's price.</li>
            <li>Points above it (marked +) are where the model sees value; below, the price is shorter than the model thinks fair.</li>
            <li>Implied probability includes the bookmaker's margin, so most points sit slightly below the line even when the model and market agree.</li>
            <li>A single is only flagged <b>BET</b> if its edge survives the pessimistic end of the model's uncertainty and the data are current.</li>
          </ul>
          <label className="check"><input type="checkbox" checked={onlyBets} onChange={(e) => setOnlyBets(e.target.checked)} /> Only singles flagged BET</label>
          <label className="field inline"><span>Sort by</span>
            <select value={sort} onChange={(e) => setSort(e.target.value as SortKey)}>
              <option value="ev">Expected value</option><option value="p">Model probability</option><option value="odds">Odds</option><option value="kickoff">Kickoff</option>
            </select>
          </label>
          <p className="small muted">{rows.length.toLocaleString()} selections match your filters.</p>
        </div>
      </div>
      {rows.length ? (
        <div className="glass tbl">
          <table>
            <caption className="sr-only">Singles</caption>
            <thead><tr><th className="l">Match</th><th className="l">Selection</th><th>Odds</th><th className="l">Book · updated</th><th>Model</th><th>Implied</th><th>EV</th><th className="l">Decision</th><th><span className="sr-only">Add to slip</span></th></tr></thead>
            <tbody>
              {rows.slice(0, limit).map((r) => {
                const on = slip.has(r.leg.id);
                return (
                  <tr key={r.leg.id} className={on ? "inslip" : ""}>
                    <td className="l"><a href={`#/match/${encodeURIComponent(r.leg.match_id)}`}>{r.leg.fixture}</a><br /><span className="muted small">{LEAGUE_LABEL[r.leg.comp] ?? r.leg.comp} · {r.leg.kickoff.replace(/ (EST|EDT)$/, "")}</span></td>
                    <td className="l"><span className="muted small">{MARKET_LABEL[r.leg.market]}</span><br />{selectionLabel(r.leg, r.leg.home, r.leg.away)}</td>
                    <td><b>{fmt(r.leg.odds)}</b></td>
                    <td className="l small">{r.leg.book}<br /><span className="muted">{timeAgo(r.leg.timestamp)}</span></td>
                    <td>{pct(r.leg.p, 1)}</td><td>{pct(r.leg.implied, 1)}</td>
                    <td className={r.leg.ev > 0 ? "pos" : "neg"}>{r.leg.ev > 0 ? "▲" : "▼"} {signedPct(r.leg.ev)}</td>
                    <td className="l small"><span className={`badge ${r.decision === "BET" ? "bet" : ""}`}>{r.decision}</span><br /><span className="muted">{r.reason}</span></td>
                    <td><button className={`addbtn ${on ? "on" : ""}`} disabled={!r.ok} aria-pressed={on} onClick={() => slip.toggle(r.leg)}
                      aria-label={r.ok ? `${on ? "Remove" : "Add"} ${r.leg.fixture} ${selectionLabel(r.leg, r.leg.home, r.leg.away)}` : "Not parlay-eligible (can push)"}>{on ? "✓" : "+"}</button></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {rows.length > limit && <button className="btn wide" onClick={() => setLimit((l) => l + 100)}>Show more ({rows.length - limit} remaining)</button>}
        </div>
      ) : <Empty title="No selections match">Widen the odds range or clear a filter. If no odds are loaded at all, check the Data page.</Empty>}
    </>
  );
}

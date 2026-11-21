import { useMemo, useState } from "react";
import Filters, { emptyFilters, type FilterState } from "../components/Filters";
import MatchCard from "../components/MatchCard";
import { Empty, Tip } from "../components/ui";
import { LEAGUE_LABEL } from "../data";
import type { Matchday, Meta } from "../types";

export function matchFilter(f: FilterState) {
  const q = f.q.toLowerCase().trim();
  return (x: { home: string; away: string; comp: string; date: string }) =>
    (!q || `${x.home} v ${x.away} ${x.home} vs ${x.away}`.toLowerCase().includes(q)) &&
    (!f.date || x.date === f.date) && (!f.comps.size || f.comps.has(x.comp));
}

export default function Today({ md, meta }: { md: Matchday; meta: Meta }) {
  const [f, setF] = useState<FilterState>(emptyFilters());
  const dates = useMemo(() => [...new Set(md.fixtures.map((x) => x.date))].sort(), [md]);
  const comps = md.leagues.filter((l) => md.fixtures.some((x) => x.comp === l));
  const shown = md.fixtures.filter(matchFilter(f));
  const stale = [...new Set(md.fixtures.filter((x) => !x.data_ok).map((x) => LEAGUE_LABEL[x.comp] ?? x.comp))];
  const priced = md.fixtures.reduce((n, x) => n + x.selections.length, 0);
  return (
    <>
      <section className="hero">
        <p className="eyebrow">Daily board · {new Date(md.as_of + "T12:00:00").toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric" })}</p>
        <h1>Every match, <span className="accent">priced</span> and explained.</h1>
        <p className="lead">{md.n_fixtures} fixtures across {comps.length} competitions · {priced.toLocaleString()} prices screened · {md.n_bets} singles pass every gate.</p>
        <div className="cta">
          <a className="btn primary" href="#/featured">Featured 10–20 leg parlays</a>
          <a className="btn" href="#/singles">Browse singles</a>
          <a className="btn" href="#/builder">Open parlay builder</a>
        </div>
      </section>
      {meta.demo && <div className="banner warn" role="status"><b>⚠ Demo mode.</b> No live odds are configured, so prices are <b>synthetic</b> (model probabilities plus a bookmaker-style margin and noise) and ratings come from an offline snapshot. Add <code>SOCCER_API_KEY</code> to go live — see the README.</div>}
      {stale.length > 0 && <div className="banner warn" role="status"><b>⚠ <Tip term="stale data">Stale data</Tip>:</b> {stale.join(", ")}. Results for already-played matches are missing, so ratings miss recent form and no single is recommended there.</div>}
      <Filters f={f} set={setF} dates={dates} comps={comps} showMarkets={false} showOdds={false} />
      {shown.length ? (
        comps.filter((c) => shown.some((x) => x.comp === c)).map((c) => (
          <section key={c} aria-labelledby={`h-${c}`}>
            <h2 id={`h-${c}`} className="section-title">{LEAGUE_LABEL[c] ?? c}<span className="muted small"> · {shown.filter((x) => x.comp === c)[0].round ?? ""}</span></h2>
            <div className="cards">{shown.filter((x) => x.comp === c).map((x, i) => <MatchCard key={x.match_id} f={x} i={i} />)}</div>
          </section>
        ))
      ) : <Empty title="No matches match these filters">Try clearing the search or choosing another date.</Empty>}
    </>
  );
}

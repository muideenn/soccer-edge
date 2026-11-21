import { LEAGUE_LABEL, MARKET_LABEL } from "../data";

export interface FilterState {
  q: string;
  date: string;
  comps: Set<string>;
  markets: Set<string>;
  minOdds: number;
  maxOdds: number;
}

export const emptyFilters = (): FilterState => ({ q: "", date: "", comps: new Set(), markets: new Set(), minOdds: 1.01, maxOdds: 50 });

function toggle(set: Set<string>, v: string) {
  const n = new Set(set);
  if (n.has(v)) n.delete(v); else n.add(v);
  return n;
}

export default function Filters({ f, set, dates, comps, markets, showMarkets = true, showOdds = true }: {
  f: FilterState; set: (f: FilterState) => void; dates: string[]; comps: string[]; markets?: string[]; showMarkets?: boolean; showOdds?: boolean;
}) {
  return (
    <form className="filters glass" role="search" aria-label="Filter matches and markets" onSubmit={(e) => e.preventDefault()}>
      <label className="field grow">
        <span>Search team or match</span>
        <input type="search" value={f.q} placeholder="e.g. Arsenal, Inter v Milan" onChange={(e) => set({ ...f, q: e.target.value })} />
      </label>
      <label className="field">
        <span>Date</span>
        <select value={f.date} onChange={(e) => set({ ...f, date: e.target.value })}>
          <option value="">All dates</option>
          {dates.map((d) => <option key={d} value={d}>{new Date(d + "T12:00:00").toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" })}</option>)}
        </select>
      </label>
      {showOdds && (
        <fieldset className="field odds">
          <legend>Odds range</legend>
          <input aria-label="Minimum odds" type="number" step="0.05" min="1.01" value={f.minOdds} onChange={(e) => set({ ...f, minOdds: Number(e.target.value) || 1.01 })} />
          <span aria-hidden="true">–</span>
          <input aria-label="Maximum odds" type="number" step="0.05" min="1.01" value={f.maxOdds} onChange={(e) => set({ ...f, maxOdds: Number(e.target.value) || 50 })} />
        </fieldset>
      )}
      <div className="chiprow" role="group" aria-label="Competitions">
        {comps.map((c) => (
          <button type="button" key={c} className={`chip ${f.comps.has(c) ? "on" : ""}`} aria-pressed={f.comps.has(c)} onClick={() => set({ ...f, comps: toggle(f.comps, c) })}>
            {LEAGUE_LABEL[c] ?? c}
          </button>
        ))}
      </div>
      {showMarkets && markets && (
        <div className="chiprow" role="group" aria-label="Markets">
          {markets.map((m) => (
            <button type="button" key={m} className={`chip small ${f.markets.has(m) ? "on" : ""}`} aria-pressed={f.markets.has(m)} onClick={() => set({ ...f, markets: toggle(f.markets, m) })}>
              {MARKET_LABEL[m] ?? m}
            </button>
          ))}
        </div>
      )}
    </form>
  );
}

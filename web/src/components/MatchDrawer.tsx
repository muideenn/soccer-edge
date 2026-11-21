import { useEffect, useRef, useState } from "react";
import { LEAGUE_LABEL, MARKET_LABEL, fair, fmt, pct, selectionLabel, signedPct, timeAgo } from "../data";
import { eligible, toLeg } from "../parlay";
import { useSlip } from "../store";
import type { Fixture } from "../types";
import { CornerBars, ProbBar, ScoreGrid } from "./charts";
import { Team } from "./MatchCard";
import { AnimatedNumber, Tip } from "./ui";

const TABS = ["Prediction", "Markets", "Corners", "Form & inputs"] as const;

export default function MatchDrawer({ f, onClose }: { f: Fixture; onClose: () => void }) {
  const [tab, setTab] = useState<(typeof TABS)[number]>("Prediction");
  const [cline, setCline] = useState(9.5);
  const [mkt, setMkt] = useState("ALL");
  const ref = useRef<HTMLDivElement>(null);
  const slip = useSlip();
  useEffect(() => {
    const prev = document.activeElement as HTMLElement | null;
    ref.current?.querySelector<HTMLElement>("button, a")?.focus();
    const key = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      if (e.key === "Tab" && ref.current) { // keep focus inside the dialog
        const els = [...ref.current.querySelectorAll<HTMLElement>("button, a, input, select, [tabindex='0']")].filter((x) => !x.hasAttribute("disabled"));
        if (!els.length) return;
        const first = els[0], last = els[els.length - 1];
        if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
        else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
      }
    };
    document.addEventListener("keydown", key);
    document.body.style.overflow = "hidden";
    return () => { document.removeEventListener("keydown", key); document.body.style.overflow = ""; prev?.focus(); };
  }, [onClose]);
  const has = f.p_home !== undefined;
  const sels = [...f.selections].filter((s) => mkt === "ALL" || s.market === mkt).sort((a, b) => a.market.localeCompare(b.market) || b.model_p - a.model_p);
  const mkts = [...new Set(f.selections.map((s) => s.market))];
  const mi = f.model_inputs ?? {};
  return (
    <div className="overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="drawer" role="dialog" aria-modal="true" aria-labelledby="drawer-title" ref={ref}>
        <div className="drawer-head">
          <button className="iconbtn close" onClick={onClose} aria-label="Close match details">✕</button>
          <div className="muted small">{LEAGUE_LABEL[f.comp] ?? f.comp} · {f.round ?? ""} · {f.kickoff_user_tz}{f.venue ? ` · ${f.venue}` : ""}</div>
          <h2 id="drawer-title" className="vs big"><Team name={f.home} logo={f.home_logo} /><span className="v">vs</span><Team name={f.away} logo={f.away_logo} /></h2>
          <div className={`banner ${f.data_ok ? "note" : "warn"} small`}>
            <b>{f.data_ok ? "ⓘ" : "⚠"} Confidence {f.confidence}:</b> {f.confidence_reason}. Latest result in data {f.last_result_in_data}.
            {f.anchored_to_market ? ` Anchored to ${f.reference_book} prices.` : " No market anchor."}{f.odds_are_demo ? " Odds shown are synthetic demo prices." : ""} Lineups are not modelled.
          </div>
          <div className="tabs" role="tablist" aria-label="Match detail sections">
            {TABS.map((t) => (
              <button key={t} role="tab" id={`tab-${t}`} aria-selected={tab === t} aria-controls={`panel-${t}`} className={`tab ${tab === t ? "on" : ""}`}
                onClick={() => setTab(t)}
                onKeyDown={(e) => { const k = TABS.indexOf(t); if (e.key === "ArrowRight") setTab(TABS[(k + 1) % TABS.length]); if (e.key === "ArrowLeft") setTab(TABS[(k + TABS.length - 1) % TABS.length]); }}>
                {t}
              </button>
            ))}
          </div>
        </div>
        <div className="drawer-body" role="tabpanel" id={`panel-${tab}`} aria-labelledby={`tab-${tab}`} key={tab}>
          {tab === "Prediction" && (
            has ? (
              <div className="stack">
                <div className="bigprobs">
                  {([["Home", f.p_home!, f.p_home_q10, f.p_home_q90], ["Draw", f.p_draw!, f.p_draw_q10, f.p_draw_q90], ["Away", f.p_away!, f.p_away_q10, f.p_away_q90]] as const).map(([lab, p, lo, hi]) => (
                    <div key={lab} className="bigprob glass">
                      <span className="muted small">{lab}</span>
                      <b><AnimatedNumber value={p * 100} format={(v) => `${v.toFixed(0)}%`} /></b>
                      <span className="small muted">range {pct(lo)}–{pct(hi)} · fair {fair(p)}</span>
                    </div>
                  ))}
                </div>
                <ProbBar h={f.p_home!} d={f.p_draw!} a={f.p_away!} />
                <table className="kv">
                  <tbody>
                    <tr><th><Tip term="model probability">Over 1.5 / 2.5 / 3.5 goals</Tip></th><td>{pct(f["p_over1.5"])} / {pct(f["p_over2.5"])} / {pct(f["p_over3.5"])}</td></tr>
                    <tr><th><Tip term="btts">Both teams score</Tip></th><td>{pct(f.p_btts)}</td></tr>
                    <tr><th>Expected goals</th><td>{fmt(f.xg_home)} – {fmt(f.xg_away)}</td></tr>
                    {f.market_p_home !== undefined && <tr><th><Tip term="de-vig">Market (de-vigged)</Tip></th><td>{pct(f.market_p_home)} / {pct(f.market_p_draw)} / {pct(f.market_p_away)}</td></tr>}
                    <tr><th>Elo-Poisson cross-check</th><td>{pct(f.ep_p_home)} / {pct(f.ep_p_draw)} / {pct(f.ep_p_away)}</td></tr>
                    <tr><th>Likeliest scores</th><td>{f.top_scores}</td></tr>
                  </tbody>
                </table>
                {f.score_grid && <><h3>Correct-score probabilities (%)</h3><ScoreGrid grid={f.score_grid} home={f.home} away={f.away} /></>}
                <p className="small muted">The bracket is the 10th–90th percentile across 5,000 simulations of the model's parameter uncertainty. Probabilities shown here are the raw model; market prices are evaluated on the market-anchored version.</p>
              </div>
            ) : <p className="muted">{f.status}</p>
          )}
          {tab === "Markets" && (
            <div className="stack">
              <div className="chiprow" role="group" aria-label="Filter markets">
                {["ALL", ...mkts].map((m) => <button key={m} className={`chip small ${mkt === m ? "on" : ""}`} aria-pressed={mkt === m} onClick={() => setMkt(m)}>{m === "ALL" ? "All" : MARKET_LABEL[m] ?? m}</button>)}
              </div>
              {sels.length ? (
                <div className="tbl"><table>
                  <thead><tr><th className="l">Selection</th><th>Best odds</th><th className="l">Book · updated</th><th><Tip term="model probability">Model</Tip></th><th><Tip term="implied probability">Implied</Tip></th><th><Tip term="expected value">EV</Tip></th><th className="l">Decision</th><th><span className="sr-only">Slip</span></th></tr></thead>
                  <tbody>
                    {sels.map((s) => {
                      const ok = eligible(s);
                      const leg = toLeg(f, s);
                      const on = slip.has(leg.id);
                      return (
                        <tr key={leg.id} className={on ? "inslip" : ""}>
                          <td className="l"><span className="muted small">{MARKET_LABEL[s.market] ?? s.market}</span><br />{selectionLabel(s, f.home, f.away)}</td>
                          <td><b>{fmt(s.odds)}</b></td>
                          <td className="l small">{s.odds_source}<br /><span className="muted">{timeAgo(s.odds_timestamp)}</span></td>
                          <td>{pct(s.model_p, 1)}</td><td>{pct(s.implied_p, 1)}</td>
                          <td className={s.ev > 0 ? "pos" : "neg"}>{s.ev > 0 ? "▲" : "▼"} {signedPct(s.ev)}</td>
                          <td className="l small"><span className={`badge ${s.decision === "BET" ? "bet" : ""}`}>{s.decision}</span><br /><span className="muted">{s.reason}</span></td>
                          <td>
                            <button className={`addbtn ${on ? "on" : ""}`} disabled={!ok} onClick={() => slip.toggle(leg)}
                              aria-pressed={on} aria-label={ok ? `${on ? "Remove" : "Add"} ${selectionLabel(s, f.home, f.away)} ${on ? "from" : "to"} parlay slip` : "Not parlay-eligible: this line can push"}
                              title={ok ? undefined : "Whole or quarter lines can push, so they are excluded from parlays"}>
                              {on ? "✓" : "+"}
                            </button>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table></div>
              ) : <p className="muted">No odds available for this fixture yet.</p>}
            </div>
          )}
          {tab === "Corners" && (
            f.corner_grid ? (
              <div className="stack">
                <div className="bigprobs">
                  <div className="bigprob glass"><span className="muted small">{f.home}</span><b>{fmt(f.xc_home, 1)}</b><span className="small muted">expected corners</span></div>
                  <div className="bigprob glass"><span className="muted small">{f.away}</span><b>{fmt(f.xc_away, 1)}</b><span className="small muted">expected corners</span></div>
                  <div className="bigprob glass"><span className="muted small">Total</span><b>{fmt((f.xc_home ?? 0) + (f.xc_away ?? 0), 1)}</b><span className="small muted">expected</span></div>
                </div>
                <CornerBars grid={f.corner_grid} line={cline} setLine={setCline} />
                <p className="small muted"><Tip term="corners">How corners are modelled</Tip> Corner data last updated {f.corners_last_data ?? "unknown"}{f.corners_ok ? "." : " — stale, so treat these as indicative only."}</p>
              </div>
            ) : <p className="muted">No corner model for this match (not enough corner data for this competition).</p>
          )}
          {tab === "Form & inputs" && (
            <div className="stack">
              <div className="grid2">
                {([[f.home, f.form_home], [f.away, f.form_away]] as const).map(([team, rows]) => (
                  <div key={team} className="glass pad">
                    <h3>{team}: last {rows?.length ?? 0}</h3>
                    <div className="formrow" aria-label={`${team} recent results`}>
                      {(rows ?? []).map((r, k) => <span key={k} className={`fr fr-${r.result}`} title={`${r.date} ${r.venue === "H" ? "vs" : "at"} ${r.opponent} ${r.score}`}>{r.result}</span>)}
                    </div>
                    <ul className="formlist">{(rows ?? []).map((r, k) => <li key={k}><span className="muted small">{r.date}</span> {r.venue === "H" ? "vs" : "at"} {r.opponent} <b>{r.score}</b></li>)}</ul>
                  </div>
                ))}
              </div>
              <h3>Model inputs</h3>
              <table className="kv">
                <tbody>
                  <tr><th>Attack rating (log scale)</th><td>{f.home} {fmt(mi.attack_home as number)} · {f.away} {fmt(mi.attack_away as number)}</td></tr>
                  <tr><th>Defence rating (higher concedes more)</th><td>{f.home} {fmt(mi.defence_home as number)} · {f.away} {fmt(mi.defence_away as number)}</td></tr>
                  <tr><th>Home advantage (log goals)</th><td>{fmt(mi.home_advantage as number)}</td></tr>
                  <tr><th>Elo</th><td>{fmt(mi.elo_home as number, 0)} v {fmt(mi.elo_away as number, 0)} (gap incl. home edge {fmt(f.elo_diff_incl_home, 0)})</td></tr>
                  <tr><th>Rest days</th><td>{fmt(mi.rest_days_home as number, 0)} v {fmt(mi.rest_days_away as number, 0)}</td></tr>
                  <tr><th>Low-score correlation ρ</th><td>{fmt(mi.rho as number, 3)}</td></tr>
                  <tr><th>Matches in the fit</th><td>{mi.matches_in_fit ?? "–"}</td></tr>
                </tbody>
              </table>
              <p className="small muted">The goal model is a time-weighted Dixon-Coles fit (half-life about a year) refit on every update. Injuries are listed below but not yet built into the numbers.</p>
              {f.injuries.length > 0 && <><h3>Reported absences</h3><ul className="formlist">{f.injuries.map((x, k) => <li key={k}><b>{x.player}</b> ({x.team}) — {x.type ?? ""} {x.reason ?? ""}</li>)}</ul></>}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

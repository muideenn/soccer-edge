import { useState } from "react";
import { MARKET_LABEL, fmt, pct, selectionLabel, signedPct, timeAgo } from "../data";
import type { Combined, Leg } from "../parlay";
import { useSlip } from "../store";
import { AnimatedNumber, RiskBadge, Tip } from "./ui";

export function ParlayStats({ c }: { c: Combined }) {
  return (
    <div className="pstats">
      <div><span className="muted small"><Tip term="decimal odds">Combined odds</Tip></span><b><AnimatedNumber value={c.odds} format={(v) => (v >= 1000 ? v.toFixed(0) : v.toFixed(2))} /></b></div>
      <div><span className="muted small"><Tip term="model probability">Est. chance of winning</Tip></span><b><AnimatedNumber value={c.p * 100} format={(v) => `${v < 1 ? v.toFixed(2) : v.toFixed(1)}%`} /></b>
        <span className="small muted">{c.method === "independent" ? "approximation (independence)" : "same-match legs modelled"}</span></div>
      <div><span className="muted small"><Tip term="expected value">Expected value</Tip></span><b className={c.ev > 0 ? "pos" : "neg"}>{c.ev > 0 ? "▲" : "▼"} <AnimatedNumber value={c.ev * 100} format={(v) => `${v >= 0 ? "+" : "−"}${Math.abs(v).toFixed(1)}%`} /></b><span className="small muted">per unit staked, if the model is right</span></div>
      <div><span className="muted small"><Tip term="risk rating">Risk</Tip></span><RiskBadge {...c.risk} /><span className="small muted">{c.risk.text}</span></div>
      <div><span className="muted small">Loses about</span><b>{c.p >= 0.005 ? `${Math.max(1, Math.round(1 / c.p) - 1)} in ${Math.max(2, Math.round(1 / c.p))}` : "almost every time"}</b><span className="small muted">if the estimate is right</span></div>
    </div>
  );
}

export function LegTable({ legs, removable }: { legs: Leg[]; removable?: boolean }) {
  const slip = useSlip();
  return (
    <div className="tbl">
      <table>
        <thead><tr><th>#</th><th className="l">Match</th><th className="l">Leg</th><th>Odds</th><th className="l">Source · time</th><th>Est. prob.</th>{removable && <th><span className="sr-only">Remove</span></th>}</tr></thead>
        <tbody>
          {legs.map((l, k) => (
            <tr key={l.id} className="legrow" style={{ ["--i" as string]: k }}>
              <td>{k + 1}</td>
              <td className="l"><a href={`#/match/${encodeURIComponent(l.match_id)}`}>{l.fixture}</a><br /><span className="muted small">{l.kickoff.replace(/ (EST|EDT)$/, "")}</span></td>
              <td className="l"><span className="muted small">{MARKET_LABEL[l.market]}</span><br />{selectionLabel(l, l.home, l.away)}
                {l.unvalidated && <span className="tag" title="Corner betting has no historical odds to validate it">unvalidated</span>}
                {l.stale && <span className="tag warn" title="Ratings stale for this match">stale</span>}
                {l.demo && <span className="tag warn" title="Synthetic demo price">demo</span>}</td>
              <td><b>{fmt(l.odds)}</b></td>
              <td className="l small">{l.book}<br /><span className="muted">{l.timestamp ? `${new Date(l.timestamp).toLocaleString()} (${timeAgo(l.timestamp)})` : "time unknown"}</span></td>
              <td>{pct(l.p, 1)}</td>
              {removable && <td><button className="iconbtn" onClick={() => slip.remove(l.id)} aria-label={`Remove ${l.fixture} ${selectionLabel(l, l.home, l.away)}`}>✕</button></td>}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function ParlayCard({ title, legs, c, rank }: { title: string; legs: Leg[]; c: Combined; rank?: number }) {
  const [open, setOpen] = useState(rank === 0);
  const slip = useSlip();
  return (
    <article className="pcard glass" style={{ ["--i" as string]: rank ?? 0 }}>
      <header>
        <div><h3>{title}</h3><span className="muted small">{legs.length} legs · {signedPct(c.ev)} EV · {pct(c.p, c.p < 0.01 ? 2 : 1)} chance</span></div>
        <div className="row">
          <button className="btn" onClick={() => setOpen((o) => !o)} aria-expanded={open}>{open ? "Hide legs" : "Show legs"}</button>
          <button className="btn primary" onClick={() => { slip.setAll(legs); location.hash = "#/builder"; }}>Edit in builder</button>
        </div>
      </header>
      <ParlayStats c={c} />
      <div className={`collapse ${open ? "open" : ""}`}>{open && <LegTable legs={legs} />}</div>
      <details className="notes"><summary>Assumptions behind these numbers</summary><ul>{c.notes.map((n) => <li key={n}>{n}</li>)}</ul></details>
    </article>
  );
}

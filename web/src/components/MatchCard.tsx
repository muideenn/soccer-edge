import { LEAGUE_LABEL, fmt, pct } from "../data";
import type { Fixture } from "../types";
import { ProbBar } from "./charts";

export function Team({ name, logo }: { name: string; logo?: string | null }) {
  return <span className="team">{logo ? <img src={logo} alt="" loading="lazy" width={20} height={20} /> : <span className="crest" aria-hidden="true">{name.slice(0, 1)}</span>}<span>{name}</span></span>;
}

export default function MatchCard({ f, i }: { f: Fixture; i: number }) {
  const has = f.p_home !== undefined;
  const fav = has ? ([["home", f.p_home!], ["draw", f.p_draw!], ["away", f.p_away!]] as const).reduce((a, b) => (b[1] > a[1] ? b : a)) : null;
  const time = f.kickoff_user_tz.replace(/ (EST|EDT)$/, "").replace(/^\w+ /, "");
  return (
    <article className="mcard" style={{ ["--i" as string]: i }} aria-labelledby={`t-${f.match_id}`}>
      <a className="mcard-link" href={`#/match/${encodeURIComponent(f.match_id)}`} aria-label={`Open details for ${f.home} versus ${f.away}`}>
        <header>
          <span className="comp">{LEAGUE_LABEL[f.comp] ?? f.comp}</span>
          <span className="time">{time}</span>
        </header>
        <h3 id={`t-${f.match_id}`} className="vs">
          <Team name={f.home} logo={f.home_logo} />
          <span className="v">vs</span>
          <Team name={f.away} logo={f.away_logo} />
        </h3>
        {has ? (
          <>
            <ProbBar h={f.p_home!} d={f.p_draw!} a={f.p_away!} />
            <div className="probs">
              <span><b>{pct(f.p_home)}</b> home</span><span><b>{pct(f.p_draw)}</b> draw</span><span><b>{pct(f.p_away)}</b> away</span>
            </div>
            <div className="facts">
              <span title="Expected goals">xG {fmt(f.xg_home, 1)}–{fmt(f.xg_away, 1)}</span>
              <span>O2.5 {pct(f["p_over2.5"])}</span>
              <span>BTTS {pct(f.p_btts)}</span>
              {f.xc_home !== undefined && <span title="Expected corners">⚑ {fmt((f.xc_home ?? 0) + (f.xc_away ?? 0), 1)} corners</span>}
            </div>
            <div className="foot">
              <span className="lean">Model lean: <b>{fav![0]}</b></span>
              <span className={`state ${f.data_ok ? "ok" : "stale"}`}>{f.data_ok ? "✓ data current" : "⚠ stale data"}</span>
            </div>
          </>
        ) : <p className="muted small">{f.status}</p>}
      </a>
    </article>
  );
}

import { StrictMode, useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import Background from "./components/Background";
import MatchDrawer from "./components/MatchDrawer";
import { MotionProvider, Skeleton, useMotion } from "./components/ui";
import { timeAgo, useJson } from "./data";
import { eligible, toLeg, type Leg } from "./parlay";
import Builder from "./pages/Builder";
import DataStatus from "./pages/DataStatus";
import Featured from "./pages/Featured";
import Performance from "./pages/Performance";
import Singles from "./pages/Singles";
import Today from "./pages/Today";
import { SlipProvider, useSlip } from "./store";
import "./styles.css";
import type { Fixture, Matchday as MD, Meta, Paper, Performance as P } from "./types";

const NAV = [["/", "Today"], ["/singles", "Singles"], ["/builder", "Parlay builder"], ["/featured", "Featured 10–20"], ["/performance", "Performance"], ["/data", "Data"]] as const;

function useRoute() {
  const get = () => (location.hash || "#/").slice(1);
  const [r, setR] = useState(get);
  useEffect(() => {
    const f = () => setR(get());
    window.addEventListener("hashchange", f);
    return () => window.removeEventListener("hashchange", f);
  }, []);
  return r;
}

function MotionToggle() {
  const { motion, setMotion } = useMotion();
  return (
    <button className="iconbtn motion" onClick={() => setMotion(!motion)} aria-pressed={!motion}
      aria-label={motion ? "Pause background animation" : "Resume background animation"} title={motion ? "Pause animation" : "Resume animation"}>
      {motion ? "❚❚" : "▶"}<span className="hide-sm">{motion ? " Pause motion" : " Motion off"}</span>
    </button>
  );
}

function Shell({ md, meta, perf, paper, route }: { md: MD; meta: Meta; perf: P; paper: Paper | null; route: string }) {
  const slip = useSlip();
  const [base, setBase] = useState("/");
  const isMatch = route.startsWith("/match/");
  useEffect(() => { if (!isMatch) { setBase(route); window.scrollTo({ top: 0, behavior: "smooth" }); } }, [route, isMatch]);
  const page = isMatch ? base : route;
  const fixtures = useMemo(() => new Map(md.fixtures.map((f) => [f.match_id, f])), [md]);
  const pool = useMemo(() => md.fixtures.flatMap((f) => f.selections.filter(eligible).map((s) => toLeg(f, s))), [md]);
  const comps = md.leagues.filter((l) => md.fixtures.some((x) => x.comp === l));
  const drawerFixture: Fixture | undefined = isMatch ? fixtures.get(decodeURIComponent(route.slice(7))) : undefined;
  let body: JSX.Element;
  if (page.startsWith("/singles")) body = <Singles md={md} />;
  else if (page.startsWith("/builder")) body = <Builder fixtures={fixtures} />;
  else if (page.startsWith("/featured")) body = <Featured pool={pool} fixtures={fixtures} comps={comps} meta={meta} />;
  else if (page.startsWith("/performance")) body = <Performance perf={perf} paper={paper} />;
  else if (page.startsWith("/data")) body = <DataStatus meta={meta} />;
  else body = <Today md={md} meta={meta} />;
  return (
    <>
      <main id="main" className="wrap page" key={page}>{body}</main>
      {drawerFixture && <MatchDrawer f={drawerFixture} onClose={() => (location.hash = `#${base}`)} />}
      {isMatch && !drawerFixture && <div className="overlay"><div className="drawer" role="dialog" aria-modal="true" aria-label="Match not found"><p>That match is not in today's data. <a href={`#${base}`}>Close</a></p></div></div>}
      <a className={`fab ${slip.legs.length ? "show" : ""}`} href="#/builder" aria-label={`Open parlay slip, ${slip.legs.length} legs`}>
        <span className="fab-ball" aria-hidden="true" /> Slip <b>{slip.legs.length}</b>
      </a>
      <div className="sr-only" aria-live="polite">{slip.announce}</div>
      <Background teams={md.fixtures.flatMap((f) => [f.home, f.away]).slice(0, 40)} comps={comps} />
    </>
  );
}

function App() {
  const route = useRoute();
  const meta = useJson<Meta>("meta");
  const md = useJson<MD>("matchday");
  const perf = useJson<P>("performance");
  const paper = useJson<Paper>("paper");
  const err = meta.error || md.error || perf.error;
  const valid = useMemo(() => {
    const m = new Map<string, Leg>();
    md.data?.fixtures.forEach((f) => f.selections.filter(eligible).forEach((s) => { const l = toLeg(f, s); m.set(l.id, l); }));
    return m;
  }, [md.data]);
  const generated = meta.data ? Date.parse(meta.data.generated_utc) : NaN;
  const old = Number.isFinite(generated) && Date.now() - generated > 36 * 3600 * 1000;
  const nav = (route.startsWith("/match/") ? "" : route) || "/";
  return (
    <MotionProvider>
      <SlipProvider valid={valid}>
        <a className="skip" href="#main">Skip to content</a>
        <header className="top">
          <div className="wrap topbar">
            <a className="brand" href="#/" aria-label="Soccer Edge home"><span className="logo-ball" aria-hidden="true" />Soccer<b>Edge</b></a>
            <nav aria-label="Main">
              {NAV.map(([href, label]) => (
                <a key={href} href={`#${href}`} className={(href === "/" ? nav === "/" : nav.startsWith(href)) ? "on" : ""} aria-current={(href === "/" ? nav === "/" : nav.startsWith(href)) ? "page" : undefined}>{label}</a>
              ))}
            </nav>
            <div className="top-right">
              {meta.data && <span className={`stamp ${old ? "old" : ""}`} title={meta.data.generated_utc}>{old ? "⚠ " : ""}Updated {timeAgo(meta.data.generated_utc)}</span>}
              <MotionToggle />
            </div>
          </div>
        </header>
        <div className="rg wrap small" role="note">18+ · Probabilities are estimates, not guarantees · Bet only where legal and only what you can afford to lose · Never chase losses · Help: 1-800-GAMBLER · <a href="https://www.begambleaware.org" rel="noreferrer">BeGambleAware</a></div>
        {old && <div className="wrap"><div className="banner warn" role="alert">⚠ This data was generated {timeAgo(meta.data!.generated_utc)}. The scheduled update may have failed; prices and lineups have likely moved.</div></div>}
        {err ? (
          <main id="main" className="wrap"><div className="banner warn" role="alert"><b>Could not load data.</b> {err}. If you just deployed, run the "Update data and site" workflow once; locally run <code>python -m soccer_edge.cli export</code>.</div></main>
        ) : meta.data && md.data && perf.data ? (
          <Shell md={md.data} meta={meta.data} perf={perf.data} paper={paper.data} route={route} />
        ) : (
          <main id="main" className="wrap page"><h1 className="page-title">Loading today's board…</h1><Skeleton rows={8} /></main>
        )}
        <footer className="wrap foot">{meta.data?.disclaimer} Data: API-Football, The Odds API (optional), football-data.co.uk, openfootball, ClubElo. Background art is generic; no club or league logos are reproduced.</footer>
      </SlipProvider>
    </MotionProvider>
  );
}

createRoot(document.getElementById("root")!).render(<StrictMode><App /></StrictMode>);

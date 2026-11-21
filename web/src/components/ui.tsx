import { createContext, useContext, useEffect, useId, useRef, useState, type ReactNode } from "react";

export const GLOSSARY: Record<string, string> = {
  "decimal odds": "Total return per 1 unit staked, including the stake. Odds of 2.50 return 2.50 (1.50 profit) if the bet wins.",
  "implied probability": "1 ÷ decimal odds. It includes the bookmaker's margin, so implied probabilities across all outcomes add up to more than 100%.",
  "model probability": "The model's estimated chance the selection wins. Where odds exist it is anchored to a sharp reference bookmaker, because the market was more accurate than the raw model in testing.",
  "fair odds": "1 ÷ model probability: the price at which a bet would break even on average if the model were exactly right.",
  "expected value": "Average profit per 1 unit staked if the model probability is correct: probability × odds − 1. Negative means you expect to lose over many bets.",
  "edge (10th pct)": "Expected value recomputed at the pessimistic end (10th percentile) of the model's parameter uncertainty. Bets require this to stay positive.",
  "de-vig": "Removing the bookmaker margin from odds to estimate the market's own probabilities (Shin method for 1X2).",
  "reference bookmaker": "The sharp price (Pinnacle first, then Bet365) the model is anchored to. Other books' prices are compared against it.",
  parlay: "A single bet combining several selections (legs). Every leg must win. Odds multiply, and so does the chance of losing.",
  independence: "Multiplying leg probabilities assumes legs don't affect each other. Legs from the same match usually do (e.g. home win and over 2.5), so this app models them jointly when it can and labels the rest as approximate.",
  "risk rating": "Based on the estimated chance the whole parlay wins: Elevated, High, Very high, Extreme, Lottery-like. A 10+ leg parlay is never rated below Very high.",
  "asian handicap": "A head start in goals applied to one team. Only half-goal lines (e.g. −0.5, +1.5) are used in parlays, so they cannot push.",
  btts: "Both teams to score: wins if each team scores at least once.",
  "double chance": "Covers two of the three results (1X = home or draw, X2 = draw or away, 12 = either team wins).",
  corners: "Total corner kicks in the match. Modelled from team corner rates with extra variability (negative binomial). No historical corner odds exist to validate corner betting rules.",
  "team total": "Goals scored by one team, over or under a line.",
  "log loss": "Penalty for probability forecasts: lower is better. Confident wrong forecasts are punished heavily.",
  "brier score": "Mean squared error of probability forecasts: lower is better.",
  calibration: "Whether events forecast at X% happen about X% of the time.",
  clv: "Closing-line value: how much better the price you took was than the reference book's last price before kickoff. Consistently positive CLV is the best evidence of real skill.",
  kelly: "A staking rule that sizes bets by edge. This app uses a quarter of it, capped at 2% per bet, and staking rules never remove the risk of loss.",
  "stale data": "Matches that already finished have no result in the data, so ratings miss recent form. Bets are blocked until results load.",
};

/** Accessible tooltip: hover or keyboard focus shows it; Escape hides it. */
export function Tip({ term, children }: { term: string; children?: ReactNode }) {
  const id = useId();
  const [open, setOpen] = useState(false);
  const text = GLOSSARY[term.toLowerCase()] ?? term;
  return (
    <span className="tipwrap" onMouseEnter={() => setOpen(true)} onMouseLeave={() => setOpen(false)}>
      <button type="button" className="tipbtn" aria-describedby={open ? id : undefined} aria-label={`What is ${term}?`}
        onFocus={() => setOpen(true)} onBlur={() => setOpen(false)} onKeyDown={(e) => e.key === "Escape" && setOpen(false)}
        onClick={() => setOpen((o) => !o)}>
        {children ?? term}<span aria-hidden="true" className="qmark">?</span>
      </button>
      {open && <span role="tooltip" id={id} className="tooltip">{text}</span>}
    </span>
  );
}

/** Counts smoothly to a new value (skips animation under reduced motion). */
export function AnimatedNumber({ value, format }: { value: number; format: (v: number) => string }) {
  const [shown, setShown] = useState(value);
  const from = useRef(value);
  const { motion } = useMotion();
  useEffect(() => {
    if (!motion || !Number.isFinite(value)) { setShown(value); from.current = value; return; }
    const start = performance.now(), a = from.current, d = 450;
    let raf = 0;
    const tick = (t: number) => {
      const k = Math.min(1, (t - start) / d), e = 1 - Math.pow(1 - k, 3);
      setShown(a + (value - a) * e);
      if (k < 1) raf = requestAnimationFrame(tick); else from.current = value;
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [value, motion]);
  return <>{format(shown)}</>;
}

// -------- motion preference (OS setting + user toggle, persisted)
const MotionCtx = createContext<{ motion: boolean; setMotion: (b: boolean) => void }>({ motion: true, setMotion: () => {} });
export function MotionProvider({ children }: { children: ReactNode }) {
  const reduced = typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
  const [motion, setMotionState] = useState<boolean>(() => {
    try { const v = localStorage.getItem("motion"); return v === null ? !reduced : v === "on"; } catch { return !reduced; }
  });
  const setMotion = (b: boolean) => { setMotionState(b); try { localStorage.setItem("motion", b ? "on" : "off"); } catch { /* ignore */ } };
  useEffect(() => { document.documentElement.dataset.motion = motion ? "on" : "off"; }, [motion]);
  return <MotionCtx.Provider value={{ motion, setMotion }}>{children}</MotionCtx.Provider>;
}
export const useMotion = () => useContext(MotionCtx);

export function RiskBadge({ level, label, icon }: { level: number; label: string; icon: string }) {
  return <span className={`risk risk-${level}`} aria-label={`Risk: ${label}`}><span aria-hidden="true">{icon}</span> {label} risk</span>;
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return <div className="empty" role="status"><div className="empty-ball" aria-hidden="true" /><h3>{title}</h3>{children}</div>;
}

export function Skeleton({ rows = 6 }: { rows?: number }) {
  return <div aria-busy="true" aria-label="Loading">{Array.from({ length: rows }, (_, i) => <div key={i} className="skel" style={{ animationDelay: `${i * 80}ms` }} />)}</div>;
}

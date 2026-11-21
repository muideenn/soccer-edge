import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import type { Leg } from "./parlay";

interface SlipCtx {
  legs: Leg[];
  has: (id: string) => boolean;
  toggle: (l: Leg) => void;
  remove: (id: string) => void;
  clear: () => void;
  setAll: (ls: Leg[]) => void;
  announce: string;
}

const Ctx = createContext<SlipCtx | null>(null);

export function SlipProvider({ children, valid }: { children: ReactNode; valid: Map<string, Leg> }) {
  const [legs, setLegs] = useState<Leg[]>(() => {
    try { return JSON.parse(localStorage.getItem("slip") ?? "[]"); } catch { return []; }
  });
  const [announce, setAnnounce] = useState("");
  // keep the slip in sync with today's data: drop legs that no longer exist, refresh prices
  useEffect(() => {
    if (!valid.size) return;
    setLegs((ls) => ls.filter((l) => valid.has(l.id)).map((l) => valid.get(l.id)!));
  }, [valid]);
  useEffect(() => { try { localStorage.setItem("slip", JSON.stringify(legs)); } catch { /* ignore */ } }, [legs]);
  const value = useMemo<SlipCtx>(() => ({
    legs,
    has: (id) => legs.some((l) => l.id === id),
    toggle: (l) => setLegs((ls) => {
      const on = ls.some((x) => x.id === l.id);
      setAnnounce(on ? `Removed ${l.fixture} from slip` : `Added ${l.fixture} to slip`);
      return on ? ls.filter((x) => x.id !== l.id) : [...ls, l];
    }),
    remove: (id) => setLegs((ls) => ls.filter((x) => x.id !== id)),
    clear: () => { setLegs([]); setAnnounce("Slip cleared"); },
    setAll: (ls) => { setLegs(ls); setAnnounce(`Loaded ${ls.length} legs into the slip`); },
    announce,
  }), [legs, announce]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useSlip() {
  const c = useContext(Ctx);
  if (!c) throw new Error("useSlip outside provider");
  return c;
}

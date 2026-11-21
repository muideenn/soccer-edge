import { useMemo, useRef, useState } from "react";

const SERIES = ["var(--series-1)", "var(--series-2)", "var(--series-3)"];

export function ProbBar({ h, d, a }: { h: number; d: number; a: number }) {
  return (
    <div className="probbar" role="img" aria-label={`Home ${Math.round(h * 100)}%, draw ${Math.round(d * 100)}%, away ${Math.round(a * 100)}%`}>
      <span style={{ width: `${h * 100}%`, background: SERIES[0] }} />
      <span style={{ width: `${d * 100}%`, background: "var(--text-muted)", opacity: 0.55 }} />
      <span style={{ width: `${a * 100}%`, background: SERIES[1] }} />
    </div>
  );
}

interface Series {
  name: string;
  points: { x: number; y: number; label: string }[];
}

/** Multi-series line chart with a crosshair tooltip. One y-axis only. */
export function LineChart({ series, height = 260, yLabel, fmtY = (v: number) => v.toFixed(0), zero = true }: {
  series: Series[]; height?: number; yLabel: string; fmtY?: (v: number) => string; zero?: boolean;
}) {
  const ref = useRef<SVGSVGElement>(null);
  const [hover, setHover] = useState<{ x: number; px: number } | null>(null);
  const W = 900, H = height, m = { l: 54, r: 16, t: 12, b: 28 };
  const all = series.flatMap((s) => s.points);
  const xs = all.map((p) => p.x), ys = all.map((p) => p.y).concat(zero ? [0] : []);
  const x0 = Math.min(...xs), x1 = Math.max(...xs);
  let y0 = Math.min(...ys), y1 = Math.max(...ys);
  const pad = (y1 - y0) * 0.08 || 1;
  y0 -= pad; y1 += pad;
  const sx = (x: number) => m.l + ((x - x0) / (x1 - x0 || 1)) * (W - m.l - m.r);
  const sy = (y: number) => m.t + (1 - (y - y0) / (y1 - y0 || 1)) * (H - m.t - m.b);
  const yt = useMemo(() => {
    const raw = (y1 - y0) / 5, mag = 10 ** Math.floor(Math.log10(raw || 1));
    const step = [1, 2, 2.5, 5, 10].map((k) => k * mag).find((k) => k >= raw) ?? raw;
    const out: number[] = [];
    for (let v = Math.ceil(y0 / step) * step; v <= y1; v += step) out.push(Math.round(v * 1e6) / 1e6);
    return out;
  }, [y0, y1]);
  const years = useMemo(() => {
    const out: number[] = [];
    const a = new Date(x0).getFullYear(), b = new Date(x1).getFullYear();
    for (let y = a; y <= b; y++) { const t = Date.UTC(y, 0, 1); if (t >= x0 && t <= x1) out.push(t); }
    return out;
  }, [x0, x1]);
  const nearest = (s: Series, x: number) => {
    let best = s.points[0];
    for (const p of s.points) if (Math.abs(p.x - x) < Math.abs(best.x - x)) best = p;
    return best;
  };
  const onMove = (e: React.MouseEvent) => {
    const r = ref.current!.getBoundingClientRect();
    const px = ((e.clientX - r.left) / r.width) * W;
    const x = x0 + ((px - m.l) / (W - m.l - m.r)) * (x1 - x0);
    setHover({ x: Math.max(x0, Math.min(x1, x)), px: e.clientX - r.left });
  };
  return (
    <div className="chartbox">
      <div className="legend">
        {series.map((s, i) => (
          <span key={s.name}><i style={{ background: SERIES[i] }} />{s.name}</span>
        ))}
      </div>
      <svg ref={ref} viewBox={`0 0 ${W} ${H}`} width="100%" onMouseMove={onMove} onMouseLeave={() => setHover(null)} role="img" aria-label={yLabel}>
        {yt.map((v) => (
          <g key={v}>
            <line x1={m.l} x2={W - m.r} y1={sy(v)} y2={sy(v)} stroke="var(--grid)" />
            <text x={m.l - 6} y={sy(v) + 4} textAnchor="end">{fmtY(v)}</text>
          </g>
        ))}
        {zero && <line x1={m.l} x2={W - m.r} y1={sy(0)} y2={sy(0)} stroke="var(--text-muted)" />}
        {years.map((t) => (
          <text key={t} x={sx(t)} y={H - 8} textAnchor="middle">{new Date(t).getUTCFullYear()}</text>
        ))}
        {series.map((s, i) => (
          <polyline key={s.name} fill="none" stroke={SERIES[i]} strokeWidth={2} strokeLinejoin="round"
            points={s.points.map((p) => `${sx(p.x)},${sy(p.y)}`).join(" ")} />
        ))}
        {hover && <line x1={sx(hover.x)} x2={sx(hover.x)} y1={m.t} y2={H - m.b} stroke="var(--text-muted)" strokeDasharray="3 3" />}
        {hover && series.map((s, i) => { const p = nearest(s, hover.x); return p ? <circle key={s.name} cx={sx(p.x)} cy={sy(p.y)} r={4} fill={SERIES[i]} stroke="var(--surface-1)" strokeWidth={2} /> : null; })}
      </svg>
      {hover && (
        <div className="tip" style={{ left: Math.min(hover.px + 12, 640), top: 30 }}>
          {series.map((s, i) => { const p = nearest(s, hover.x); return p ? (
            <div key={s.name}><i style={{ display: "inline-block", width: 8, height: 8, borderRadius: 2, background: SERIES[i], marginRight: 6 }} />{s.name}: <b>{fmtY(p.y)}</b> <span className="muted">{p.label}</span></div>
          ) : null; })}
        </div>
      )}
      <div className="small muted">{yLabel}</div>
    </div>
  );
}

/** Reliability diagram: predicted vs observed, one panel per outcome. */
export function Calibration({ rows, models }: { rows: { model: string; outcome: string; mean_pred: number; observed: number; n: number }[]; models: [string, string][] }) {
  const [tip, setTip] = useState<{ x: number; y: number; text: string } | null>(null);
  const S = 220, m = 30;
  const s = (v: number) => m + v * (S - m - 8);
  const sy = (v: number) => S - m - v * (S - m - 8);
  return (
    <div className="chartbox">
      <div className="legend">{models.map(([k, lab], i) => <span key={k}><i style={{ background: SERIES[i] }} />{lab}</span>)}</div>
      <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
        {[["H", "Home win"], ["D", "Draw"], ["A", "Away win"]].map(([o, lab]) => (
          <svg key={o} viewBox={`0 0 ${S} ${S}`} width={S} height={S} role="img" aria-label={`Calibration ${lab}`}>
            <text x={S - 8} y={sy(0.06)} textAnchor="end" style={{ fontWeight: 600, fill: "var(--text-primary)" }}>{lab}</text>
            {[0, 0.25, 0.5, 0.75, 1].map((v) => (
              <g key={v}>
                <line x1={s(0)} x2={s(1)} y1={sy(v)} y2={sy(v)} stroke="var(--grid)" />
                <text x={m - 4} y={sy(v) + 3} textAnchor="end">{v * 100}</text>
                <text x={s(v)} y={S - 12} textAnchor="middle">{v * 100}</text>
              </g>
            ))}
            <line x1={s(0)} y1={sy(0)} x2={s(1)} y2={sy(1)} stroke="var(--text-muted)" strokeDasharray="3 3" />
            {models.map(([k, name], i) => {
              const pts = rows.filter((r) => r.model === k && r.outcome === o).sort((a, b) => a.mean_pred - b.mean_pred);
              return (
                <g key={k}>
                  <polyline fill="none" stroke={SERIES[i]} strokeWidth={2} points={pts.map((p) => `${s(p.mean_pred)},${sy(p.observed)}`).join(" ")} />
                  {pts.map((p) => (
                    <circle key={p.mean_pred} cx={s(p.mean_pred)} cy={sy(p.observed)} r={4} fill={SERIES[i]} stroke="var(--surface-1)" strokeWidth={2}
                      onMouseEnter={(e) => setTip({ x: (e.target as SVGCircleElement).getBoundingClientRect().left, y: 0, text: `${name} · ${lab}: predicted ${(p.mean_pred * 100).toFixed(1)}%, observed ${(p.observed * 100).toFixed(1)}% (n=${p.n})` })}
                      onMouseLeave={() => setTip(null)} />
                  ))}
                </g>
              );
            })}
          </svg>
        ))}
      </div>
      {tip && <div className="tip" style={{ left: 10, top: -6 }}>{tip.text}</div>}
      <div className="small muted">Predicted probability (x) vs observed frequency (y), %; dashed line = perfect calibration.</div>
    </div>
  );
}

/** Correct-score heat map (sequential single hue). */
export function ScoreGrid({ grid, home, away }: { grid: number[][]; home: string; away: string }) {
  const max = Math.max(...grid.flat());
  return (
    <div className="tbl">
      <table className="heat" style={{ width: "auto" }}>
        <thead>
          <tr><th className="l">{home} ↓ / {away} →</th>{grid[0].map((_, j) => <th key={j} style={{ textAlign: "center" }}>{j}</th>)}</tr>
        </thead>
        <tbody>
          {grid.map((row, i) => (
            <tr key={i}>
              <th className="l">{i}</th>
              {row.map((v, j) => {
                const t = v / max;
                return (
                  <td key={j} title={`${i}-${j}: ${(v * 100).toFixed(1)}%`}
                    style={{ background: `color-mix(in oklab, var(--seq-1) ${Math.round(t * 85)}%, var(--seq-0))`, color: t > 0.55 ? "#fff" : "var(--text-primary)" }}>
                    {(v * 100).toFixed(v >= 0.1 ? 0 : 1)}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Model probability vs bookmaker-implied probability for every priced selection. Points above
 *  the diagonal are where the model is more optimistic than the price. Click adds to slip. */
export function OddsScatter({ points, onPick, isOn }: {
  points: { id: string; x: number; y: number; label: string; sub: string; eligible: boolean }[];
  onPick: (id: string) => void; isOn: (id: string) => boolean;
}) {
  const [hover, setHover] = useState<string | null>(null);
  const W = 560, H = 380, m = { l: 46, r: 14, t: 12, b: 38 };
  const sx = (v: number) => m.l + v * (W - m.l - m.r);
  const sy = (v: number) => H - m.b - v * (H - m.t - m.b);
  const hp = points.find((p) => p.id === hover);
  return (
    <div className="chartbox">
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label="Scatter of model probability against implied probability">
        {[0, 0.25, 0.5, 0.75, 1].map((v) => (
          <g key={v}>
            <line x1={sx(0)} x2={sx(1)} y1={sy(v)} y2={sy(v)} stroke="var(--grid)" />
            <text x={m.l - 6} y={sy(v) + 4} textAnchor="end">{v * 100}%</text>
            <text x={sx(v)} y={H - m.b + 16} textAnchor="middle">{v * 100}%</text>
          </g>
        ))}
        <line x1={sx(0)} y1={sy(0)} x2={sx(1)} y2={sy(1)} stroke="var(--text-muted)" strokeDasharray="4 4" />
        <text x={sx(0.5)} y={H - 4} textAnchor="middle">implied by best odds</text>
        <text x={12} y={sy(0.5)} textAnchor="middle" transform={`rotate(-90 12 ${sy(0.5)})`}>model probability</text>
        {points.map((p) => {
          const on = isOn(p.id);
          return (
            <g key={p.id} className="dot" tabIndex={p.eligible ? 0 : -1} role={p.eligible ? "button" : undefined}
              aria-label={`${p.label}, model ${Math.round(p.y * 100)}%, implied ${Math.round(p.x * 100)}%${on ? ", in slip" : ""}`}
              onMouseEnter={() => setHover(p.id)} onMouseLeave={() => setHover(null)} onFocus={() => setHover(p.id)} onBlur={() => setHover(null)}
              onClick={() => p.eligible && onPick(p.id)} onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && p.eligible && (e.preventDefault(), onPick(p.id))}>
              <circle cx={sx(p.x)} cy={sy(p.y)} r={12} fill="transparent" />
              <circle cx={sx(p.x)} cy={sy(p.y)} r={on ? 6 : 4.5} fill={p.y > p.x ? "var(--series-3)" : "var(--series-1)"}
                stroke={on ? "var(--text-primary)" : "var(--surface-1)"} strokeWidth={on ? 2.5 : 1.5} opacity={p.eligible ? 0.9 : 0.35} />
              {p.y > p.x && <text x={sx(p.x) + 7} y={sy(p.y) - 6} style={{ fontSize: 10 }}>+</text>}
            </g>
          );
        })}
      </svg>
      {hp && <div className="tip" style={{ left: 12, top: 12 }}><b>{hp.label}</b><div className="muted">{hp.sub}</div><div>Model {(hp.y * 100).toFixed(1)}% · implied {(hp.x * 100).toFixed(1)}%</div></div>}
      <div className="legend"><span><i style={{ background: "var(--series-3)" }} />+ model above price</span><span><i style={{ background: "var(--series-1)" }} />model at or below price</span><span>Faded = not parlay-eligible (can push)</span></div>
    </div>
  );
}

/** Bar chart of the total-corners distribution with an adjustable line. */
export function CornerBars({ grid, line, setLine }: { grid: number[][]; line: number; setLine: (v: number) => void }) {
  const tot = new Array(33).fill(0);
  let s = 0;
  grid.forEach((row, i) => row.forEach((v, j) => { tot[i + j] += v; s += v; }));
  const dist = tot.slice(0, 21).map((v) => v / s);
  const max = Math.max(...dist);
  const over = dist.reduce((a, v, k) => a + (k > line ? v : 0), 0);
  const W = 560, H = 200, bw = (W - 40) / dist.length;
  return (
    <div>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label={`Total corners distribution; ${Math.round(over * 100)}% chance of over ${line}`}>
        {dist.map((v, k) => (
          <g key={k}>
            <rect className="bar" x={30 + k * bw + 1} y={H - 24 - (v / max) * (H - 40)} width={bw - 2} height={(v / max) * (H - 40)} rx={3}
              fill={k > line ? "var(--series-3)" : "var(--series-1)"} opacity={0.9}><title>{k} corners: {(v * 100).toFixed(1)}%</title></rect>
            {k % 2 === 0 && <text x={30 + k * bw + bw / 2} y={H - 8} textAnchor="middle">{k}</text>}
          </g>
        ))}
        <line x1={30 + (line + 0.5) * bw} x2={30 + (line + 0.5) * bw} y1={8} y2={H - 22} stroke="var(--text-primary)" strokeDasharray="3 3" />
      </svg>
      <label className="field inline">
        <span>Line: <b>{line}</b> · Over <b>{(over * 100).toFixed(1)}%</b> · Under <b>{((1 - over) * 100).toFixed(1)}%</b></span>
        <input type="range" min={6.5} max={14.5} step={1} value={line} onChange={(e) => setLine(Number(e.target.value))} aria-label="Corner line" />
      </label>
    </div>
  );
}

/** Small multiple: one series, one axis (used twice for probability and payout). */
export function MiniLine({ xs, ys, fmt, label, highlight }: { xs: number[]; ys: number[]; fmt: (v: number) => string; label: string; highlight?: number }) {
  const W = 300, H = 150, m = { l: 44, r: 10, t: 10, b: 24 };
  if (!xs.length) return null;
  const x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(0, ...ys), y1 = Math.max(...ys) * 1.08 || 1;
  const sx = (v: number) => m.l + ((v - x0) / (x1 - x0 || 1)) * (W - m.l - m.r);
  const sy = (v: number) => H - m.b - ((v - y0) / (y1 - y0 || 1)) * (H - m.t - m.b);
  return (
    <figure className="mini">
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label={label}>
        {[0, 0.5, 1].map((k) => { const v = y0 + k * (y1 - y0); return <g key={k}><line x1={m.l} x2={W - m.r} y1={sy(v)} y2={sy(v)} stroke="var(--grid)" /><text x={m.l - 4} y={sy(v) + 4} textAnchor="end">{fmt(v)}</text></g>; })}
        {xs.map((x) => <text key={x} x={sx(x)} y={H - 6} textAnchor="middle">{x}</text>)}
        <polyline fill="none" stroke="var(--series-1)" strokeWidth={2} points={xs.map((x, k) => `${sx(x)},${sy(ys[k])}`).join(" ")} />
        {xs.map((x, k) => <circle key={x} cx={sx(x)} cy={sy(ys[k])} r={x === highlight ? 6 : 3.5} fill={x === highlight ? "var(--series-2)" : "var(--series-1)"} stroke="var(--surface-1)" strokeWidth={1.5}><title>{x} legs: {fmt(ys[k])}</title></circle>)}
      </svg>
      <figcaption className="small muted">{label}</figcaption>
    </figure>
  );
}

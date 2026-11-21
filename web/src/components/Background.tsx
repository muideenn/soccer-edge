import { useEffect, useRef } from "react";
import { useMotion } from "./ui";

/**
 * Decorative animated background: drifting footballs, generic shield badges in team-like
 * colours carrying club initials and competition codes, and faint pitch markings.
 * All shapes are drawn from scratch (no club crests or league logos are reproduced).
 * It sits behind content at low opacity, pauses when the tab is hidden, and stops entirely
 * when motion is off (user toggle or prefers-reduced-motion).
 */
type Thing = { kind: "ball" | "shield" | "ring"; x: number; y: number; r: number; vx: number; vy: number; rot: number; vr: number; hue: number; text: string; alpha: number };

function hueOf(s: string) {
  let h = 0;
  for (const c of s) h = (h * 31 + c.charCodeAt(0)) % 360;
  return h;
}

function drawBall(ctx: CanvasRenderingContext2D, t: Thing) {
  ctx.save();
  ctx.translate(t.x, t.y);
  ctx.rotate(t.rot);
  ctx.globalAlpha = t.alpha;
  ctx.beginPath();
  ctx.arc(0, 0, t.r, 0, Math.PI * 2);
  ctx.fillStyle = "rgba(240,239,236,0.9)";
  ctx.fill();
  ctx.lineWidth = Math.max(1, t.r * 0.05);
  ctx.strokeStyle = "rgba(20,20,20,0.9)";
  // centre pentagon + five spokes to the rim: a generic ball pattern
  const pent = (cx: number, cy: number, s: number, rot: number) => {
    ctx.beginPath();
    for (let k = 0; k < 5; k++) {
      const a = rot + (k * 2 * Math.PI) / 5 - Math.PI / 2;
      const px = cx + s * Math.cos(a), py = cy + s * Math.sin(a);
      if (k) ctx.lineTo(px, py); else ctx.moveTo(px, py);
    }
    ctx.closePath();
    ctx.fillStyle = "rgba(20,20,20,0.92)";
    ctx.fill();
  };
  pent(0, 0, t.r * 0.32, 0);
  for (let k = 0; k < 5; k++) {
    const a = (k * 2 * Math.PI) / 5 - Math.PI / 2;
    ctx.beginPath();
    ctx.moveTo(t.r * 0.32 * Math.cos(a), t.r * 0.32 * Math.sin(a));
    ctx.lineTo(t.r * 0.78 * Math.cos(a), t.r * 0.78 * Math.sin(a));
    ctx.stroke();
    pent(t.r * 0.92 * Math.cos(a), t.r * 0.92 * Math.sin(a), t.r * 0.2, a + Math.PI);
  }
  ctx.beginPath();
  ctx.arc(0, 0, t.r, 0, Math.PI * 2);
  ctx.stroke();
  ctx.restore();
}

function drawShield(ctx: CanvasRenderingContext2D, t: Thing) {
  const w = t.r * 1.6, h = t.r * 1.9;
  ctx.save();
  ctx.translate(t.x, t.y);
  ctx.rotate(t.rot * 0.25);
  ctx.globalAlpha = t.alpha;
  ctx.beginPath();
  ctx.moveTo(-w / 2, -h / 2);
  ctx.lineTo(w / 2, -h / 2);
  ctx.lineTo(w / 2, h * 0.05);
  ctx.quadraticCurveTo(w / 2, h * 0.38, 0, h / 2);
  ctx.quadraticCurveTo(-w / 2, h * 0.38, -w / 2, h * 0.05);
  ctx.closePath();
  const g = ctx.createLinearGradient(-w / 2, -h / 2, w / 2, h / 2);
  g.addColorStop(0, `hsla(${t.hue},70%,45%,0.95)`);
  g.addColorStop(1, `hsla(${(t.hue + 40) % 360},70%,28%,0.95)`);
  ctx.fillStyle = g;
  ctx.fill();
  ctx.lineWidth = 2;
  ctx.strokeStyle = "rgba(255,255,255,0.55)";
  ctx.stroke();
  ctx.fillStyle = "rgba(255,255,255,0.92)";
  ctx.font = `700 ${Math.round(t.r * 0.55)}px "CMU Serif", "Times New Roman", serif`;
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText(t.text, 0, -h * 0.04);
  ctx.restore();
}

function drawRing(ctx: CanvasRenderingContext2D, t: Thing) {
  ctx.save();
  ctx.translate(t.x, t.y);
  ctx.globalAlpha = t.alpha;
  ctx.beginPath();
  ctx.arc(0, 0, t.r, 0, Math.PI * 2);
  ctx.strokeStyle = `hsla(${t.hue},70%,60%,0.9)`;
  ctx.lineWidth = 3;
  ctx.stroke();
  ctx.fillStyle = `hsla(${t.hue},70%,70%,0.95)`;
  ctx.font = `800 ${Math.round(t.r * 0.5)}px "CMU Serif", "Times New Roman", serif`;
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText(t.text, 0, 1);
  ctx.restore();
}

function drawPitch(ctx: CanvasRenderingContext2D, W: number, H: number, phase: number) {
  ctx.save();
  ctx.globalAlpha = 0.07;
  ctx.strokeStyle = "#7fd3a8";
  ctx.lineWidth = 2;
  const cx = W / 2 + Math.sin(phase * 0.15) * 30, cy = H / 2;
  const pw = Math.min(W * 0.9, 1400), ph = pw * 0.62;
  ctx.strokeRect(cx - pw / 2, cy - ph / 2, pw, ph);
  ctx.beginPath(); ctx.moveTo(cx, cy - ph / 2); ctx.lineTo(cx, cy + ph / 2); ctx.stroke();
  ctx.beginPath(); ctx.arc(cx, cy, ph * 0.15, 0, Math.PI * 2); ctx.stroke();
  for (const s of [-1, 1]) {
    ctx.strokeRect(cx + s * pw / 2 - (s > 0 ? pw * 0.16 : 0), cy - ph * 0.3, pw * 0.16, ph * 0.6);
    ctx.strokeRect(cx + s * pw / 2 - (s > 0 ? pw * 0.06 : 0), cy - ph * 0.14, pw * 0.06, ph * 0.28);
  }
  ctx.restore();
}

export default function Background({ teams, comps }: { teams: string[]; comps: string[] }) {
  const ref = useRef<HTMLCanvasElement>(null);
  const { motion } = useMotion();
  useEffect(() => {
    const cv = ref.current!;
    const ctx = cv.getContext("2d");
    if (!ctx) return;
    const dpr = Math.min(window.devicePixelRatio || 1, 1.5);
    let W = 0, H = 0;
    const resize = () => {
      W = window.innerWidth; H = window.innerHeight;
      cv.width = W * dpr; cv.height = H * dpr;
      cv.style.width = `${W}px`; cv.style.height = `${H}px`;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };
    resize();
    window.addEventListener("resize", resize);
    const rnd = (a: number, b: number) => a + Math.random() * (b - a);
    const initials = (n: string) => n.replace(/[^A-Za-z ]/g, "").split(" ").filter(Boolean).map((w) => w[0]).join("").slice(0, 3).toUpperCase() || n.slice(0, 3).toUpperCase();
    const small = W < 700;
    const things: Thing[] = [];
    const nBall = small ? 5 : 9, nShield = small ? 6 : 14;
    for (let k = 0; k < nBall; k++) things.push({ kind: "ball", x: rnd(0, W), y: rnd(0, H), r: rnd(14, 38), vx: rnd(-0.35, 0.35), vy: rnd(-0.25, 0.25), rot: rnd(0, 6), vr: rnd(-0.01, 0.01), hue: 0, text: "", alpha: rnd(0.08, 0.16) });
    const pool = teams.length ? teams : ["Home", "Away"];
    for (let k = 0; k < nShield; k++) {
      const t = pool[k % pool.length];
      things.push({ kind: "shield", x: rnd(0, W), y: rnd(0, H), r: rnd(18, 34), vx: rnd(-0.2, 0.2), vy: rnd(-0.3, -0.05), rot: rnd(-0.3, 0.3), vr: rnd(-0.003, 0.003), hue: hueOf(t), text: initials(t), alpha: rnd(0.07, 0.13) });
    }
    comps.slice(0, small ? 2 : 6).forEach((c) => things.push({ kind: "ring", x: rnd(0, W), y: rnd(0, H), r: rnd(26, 40), vx: rnd(-0.15, 0.15), vy: rnd(-0.12, 0.12), rot: 0, vr: 0, hue: hueOf(c), text: c.slice(0, 3).toUpperCase(), alpha: 0.09 }));

    let raf = 0, phase = 0, running = true;
    const frame = () => {
      ctx.clearRect(0, 0, W, H);
      drawPitch(ctx, W, H, phase);
      for (const t of things) {
        if (motion) {
          t.x += t.vx; t.y += t.vy; t.rot += t.vr;
          const m = t.r * 2;
          if (t.x < -m) t.x = W + m; if (t.x > W + m) t.x = -m;
          if (t.y < -m) t.y = H + m; if (t.y > H + m) t.y = -m;
        }
        if (t.kind === "ball") drawBall(ctx, t); else if (t.kind === "shield") drawShield(ctx, t); else drawRing(ctx, t);
      }
      phase += 0.01;
      if (motion && running) raf = requestAnimationFrame(frame);
    };
    const vis = () => { running = !document.hidden; cancelAnimationFrame(raf); if (running) raf = requestAnimationFrame(frame); };
    document.addEventListener("visibilitychange", vis);
    raf = requestAnimationFrame(frame);
    return () => { cancelAnimationFrame(raf); window.removeEventListener("resize", resize); document.removeEventListener("visibilitychange", vis); };
  }, [motion, teams.join("|"), comps.join("|")]);
  return <canvas ref={ref} className="bg-canvas" aria-hidden="true" />;
}

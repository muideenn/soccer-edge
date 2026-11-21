// Post-build guard: fails the build if a secret could reach the browser bundle.
// 1) Any VITE_* variable whose name looks secret (VITE_ vars are inlined into client code).
// 2) The literal value of SOCCER_API_KEY / ODDS_API_KEY / API_FOOTBALL_KEY appearing in dist/.
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

const bad = Object.keys(process.env).filter((k) => k.startsWith("VITE_") && /(KEY|SECRET|TOKEN|PASSWORD)/i.test(k));
if (bad.length) {
  console.error(`✗ Refusing to build: ${bad.join(", ")} would be embedded in the public bundle. Use a server-side name (e.g. SOCCER_API_KEY).`);
  process.exit(1);
}
const secrets = ["SOCCER_API_KEY", "ODDS_API_KEY", "API_FOOTBALL_KEY"].map((k) => process.env[k]).filter((v) => v && v.length >= 6);
const walk = (d) => readdirSync(d).flatMap((f) => { const p = join(d, f); return statSync(p).isDirectory() ? walk(p) : [p]; });
let leaks = 0;
for (const file of walk("dist")) {
  const text = readFileSync(file, "utf8");
  for (const s of secrets) if (text.includes(s)) { console.error(`✗ Secret value found in ${file}`); leaks++; }
}
if (leaks) process.exit(1);
console.log(`✓ secret check passed (${secrets.length} secret value(s) checked against dist/)`);

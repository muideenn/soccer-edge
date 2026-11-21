import { Calibration, LineChart } from "../components/charts";
import { LEAGUE_LABEL, MARKET_LABEL, fmt, pct, signedPct } from "../data";
import type { Paper, Performance as P } from "../types";

const STRAT: Record<string, string> = { raw_model: "Raw model vs market", anchored: "Market-anchored", market_residual: "Market + features" };
const MODEL: Record<string, string> = {
  uniform: "Uniform 1/3", base: "Base rates", dc: "Dixon-Coles", ep: "Elo-Poisson", elo_logit: "Elo logistic",
  logit_full: "Logistic (all features)", gbm: "Gradient boosting", ens: "Validated ensemble", anch: "Market-anchored",
  mkt: "Bet365 (de-margined)", mkt_only: "Market refit", mkt_plus: "Market + all features", market: "Bet365 (de-margined)",
  anchored: "Market-anchored", base_rate: "Base rate", elo_poisson: "Elo-Poisson",
};

export default function Performance({ perf, paper }: { perf: P; paper: Paper | null }) {
  const pm = perf.prob_metrics.filter((r) => r.subset === "with_odds").sort((a, b) => a.logloss - b.logloss);
  const mkt = pm.find((r) => r.model === "mkt")!;
  const best = pm.filter((r) => !r.model.startsWith("mkt") && r.model !== "anch")[0];
  const strategies = Object.entries(perf.strategies);
  const series = strategies.filter(([, s]) => s.equity.length).map(([k, s]) => ({
    name: `${STRAT[k] ?? k} (${s.summary.overall[0].bets} bets)`,
    points: s.equity.map((e) => ({ x: Date.parse(e.date), y: e.units, label: `${e.date}, bet #${e.n}` })),
  }));
  return (
    <>
      <h1 className="page-title">Model performance</h1>
      <div className="muted">Chronological out-of-sample test: {perf.meta.n_test_matches.toLocaleString()} league matches, 2018-19 to 2025-26. Every forecast used only data available before kickoff.</div>

      <div className="kpis">
        <div className="glass kpi"><b>{fmt(mkt.logloss, 4)}</b><span>bookmaker 1X2 log loss (lower is better)</span></div>
        <div className="glass kpi"><b>{fmt(best.logloss, 4)}</b><span>best model: {MODEL[best.model] ?? best.model}</span></div>
        {strategies.map(([k, s]) => (
          <div className="glass kpi" key={k}><b>{signedPct(s.summary.overall[0].roi_flat)}</b>
            <span>{STRAT[k] ?? k}: ROI on {s.summary.overall[0].bets} bets (95% CI {signedPct(s.summary.overall[0].roi_ci95_lo)} to {signedPct(s.summary.overall[0].roi_ci95_hi)})</span></div>
        ))}
      </div>

      <div className="banner note">
        <b>Reading this honestly.</b> The models are far better than base rates and well calibrated, but the market is better still. Betting every model-vs-market disagreement lost money with a confidence interval below zero. Validation gave the model zero weight against the market, so live recommendations only arise where one book's price is out of line with a sharp reference. Backtests do not predict future returns — track picks on paper first.
      </div>

      <h2>Cumulative profit, flat 1-unit stakes</h2>
      <div className="glass pad"><LineChart series={series} yLabel="Cumulative profit (units)" fmtY={(v) => v.toFixed(0)} /></div>

      <h2>Strategy detail</h2>
      <div className="glass tbl">
        <table>
          <thead><tr><th className="l">Strategy</th><th className="l">Market</th><th>Bets</th><th>Hit rate</th><th>Avg odds</th><th>Edge claimed</th><th>ROI</th><th>95% CI</th><th>Max drawdown</th><th>Worst run</th></tr></thead>
          <tbody>
            {strategies.flatMap(([k, s]) => s.summary.by_market.map((r) => (
              <tr key={k + r.market}>
                <td className="l">{STRAT[k] ?? k}</td><td className="l">{MARKET_LABEL[r.market === "OU25" ? "OU" : r.market!] ?? r.market}</td>
                <td>{r.bets}</td><td>{pct(r.hit_rate)}</td><td>{fmt(r.avg_odds)}</td><td>{signedPct(r.avg_ev_claimed)}</td>
                <td>{signedPct(r.roi_flat)}</td><td className="small">{signedPct(r.roi_ci95_lo)} to {signedPct(r.roi_ci95_hi)}</td>
                <td>{fmt(r.max_drawdown_units, 1)} u</td><td>{r.longest_losing_streak}</td>
              </tr>
            )))}
          </tbody>
        </table>
        <p className="small muted">Quarter-Kelly bankroll (2% cap per bet, 10% per day): {strategies.map(([k]) => `${STRAT[k] ?? k} 1.00 → ${fmt(perf.meta.bankroll[k]?.final)} (max drawdown ${pct(perf.meta.bankroll[k]?.max_drawdown_pct)})`).join(" · ")}</p>
      </div>

      <div className="grid2">
        <div>
          <h2>1X2 forecast accuracy</h2>
          <div className="glass tbl"><table>
            <thead><tr><th className="l">Model</th><th>Log loss</th><th>Brier</th><th>RPS</th><th>Accuracy</th></tr></thead>
            <tbody>{pm.map((r) => <tr key={r.model}><td className="l">{MODEL[r.model] ?? r.model}</td><td>{fmt(r.logloss, 4)}</td><td>{fmt(r.brier, 4)}</td><td>{fmt(r.rps, 4)}</td><td>{pct(r.accuracy)}</td></tr>)}</tbody>
          </table><p className="small muted">Accuracy is secondary; log loss and Brier score judge the probabilities themselves.</p></div>
        </div>
        <div>
          <h2>Totals and Champions League</h2>
          <div className="glass tbl"><table>
            <thead><tr><th className="l">Over/Under 2.5</th><th>Log loss</th><th>Brier</th></tr></thead>
            <tbody>{perf.totals.map((r) => <tr key={r.model}><td className="l">{MODEL[r.model] ?? r.model}</td><td>{fmt(r.logloss, 4)}</td><td>{fmt(r.brier, 4)}</td></tr>)}</tbody>
          </table>
          <table style={{ marginTop: 12 }}>
            <thead><tr><th className="l">UCL 1X2 (no odds history)</th><th>Log loss</th><th>Brier</th></tr></thead>
            <tbody>{perf.ucl.map((r) => <tr key={r.model}><td className="l">{MODEL[r.model] ?? r.model}</td><td>{fmt(r.logloss, 4)}</td><td>{fmt(r.brier, 4)}</td></tr>)}</tbody>
          </table></div>
        </div>
      </div>

      <h2>Calibration</h2>
      <div className="glass pad"><Calibration rows={perf.calibration} models={[["dc", "Dixon-Coles"], ["ens", "Ensemble"], ["mkt", "Market"]]} /></div>

      {perf.corners && (
        <>
          <h2>Corners model (out of sample, {perf.corners.lines[0]?.n.toLocaleString()} matches)</h2>
          <div className="grid2">
            <div className="glass tbl"><table>
              <thead><tr><th className="l">Total corners line</th><th>Observed over</th><th>Model avg</th><th>Log loss model</th><th>Log loss base rate</th></tr></thead>
              <tbody>{perf.corners.lines.map((r) => <tr key={r.line}><td className="l">Over {r.line}</td><td>{pct(r.observed_over)}</td><td>{pct(r.model_mean_p)}</td><td>{fmt(r.logloss_model, 4)}</td><td>{fmt(r.logloss_base_rate, 4)}</td></tr>)}</tbody>
            </table></div>
            <div className="glass tbl"><table>
              <thead><tr><th className="l">P(over 9.5) bucket</th><th>Predicted</th><th>Observed</th><th>Matches</th></tr></thead>
              <tbody>{perf.corners.calibration_over9_5.map((r, k) => <tr key={k}><td className="l">{k + 1}</td><td>{pct(r.mean_pred, 1)}</td><td>{pct(r.observed, 1)}</td><td>{r.n}</td></tr>)}</tbody>
            </table></div>
          </div>
          <p className="small muted">Negative-binomial dispersion k = {perf.corners.dispersion_k ?? "Poisson"} (chosen on validation seasons). Mean total corners: model {fmt(perf.corners.mean_total_pred, 2)}, observed {fmt(perf.corners.mean_total_obs, 2)}. {perf.corners.note}</p>
        </>
      )}

      <h2>Raw-model bets by league</h2>
      <div className="glass tbl"><table>
        <thead><tr><th className="l">League</th><th>Bets</th><th>ROI</th><th>95% CI</th></tr></thead>
        <tbody>{(perf.strategies.raw_model?.summary.by_league ?? []).map((r) => <tr key={r.comp}><td className="l">{LEAGUE_LABEL[r.comp!] ?? r.comp}</td><td>{r.bets}</td><td>{signedPct(r.roi_flat)}</td><td className="small">{signedPct(r.roi_ci95_lo)} to {signedPct(r.roi_ci95_hi)}</td></tr>)}</tbody>
      </table></div>

      <h2>Live paper tracking</h2>
      {paper && paper.summary.logged ? (
        <div className="kpis">
          <div className="glass kpi"><b>{paper.summary.bets}</b><span>paper bets logged ({paper.summary.settled_bets} settled)</span></div>
          <div className="glass kpi"><b>{signedPct(paper.summary.roi ?? null)}</b><span>paper ROI (kept separate from the backtest)</span></div>
          <div className="glass kpi"><b>{signedPct(paper.summary.clv_mean ?? null)}</b><span>average closing-line value</span></div>
        </div>
      ) : <p className="muted">No paper bets logged yet. Every screened price is logged before kickoff and settled automatically.</p>}
    </>
  );
}

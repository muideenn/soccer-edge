import type { Meta } from "../types";

export default function DataStatus({ meta }: { meta: Meta }) {
  const s = meta.sync;
  return (
    <>
      <h1 className="page-title">Data status</h1>
      <div className="muted">Generated {new Date(meta.generated_utc).toLocaleString()} · model v{meta.model_version} · config {meta.config_hash}</div>

      <h2>Sources</h2>
      <div className="glass tbl"><table>
        <thead><tr><th className="l">Source</th><th className="l">Detail</th><th className="l">Snapshot</th><th className="l">Latest match</th><th>Rows</th></tr></thead>
        <tbody>{Object.entries(meta.sources).map(([k, v]) => (
          <tr key={k}><td className="l">{k}</td><td className="l small">{String(v.repo ?? v.provider ?? v.path ?? "")}</td>
            <td className="l small">{String(v.commit_time ?? v.fetched_utc ?? v.file_mtime ?? "")}</td>
            <td className="l">{String(v.max_date ?? v.max_result_date ?? "")}</td><td>{String(v.rows ?? v.results_rows ?? "")}</td></tr>
        ))}</tbody>
      </table></div>

      <h2>Last API sync</h2>
      {s ? (
        <div className="glass pad">
          <p>Provider <b>{s.provider}</b> · {s.requests_used ?? 0} requests used · {s.remaining_today ?? "?"} remaining today · finished {s.finished ? new Date(s.finished).toLocaleString() : "–"}</p>
          {s.warnings.length > 0 && <div className="banner warn">{s.warnings.map((w) => <div key={w}>{w}</div>)}</div>}
          <div className="tbl"><table>
            <thead><tr><th className="l">Step</th><th className="l">Result</th><th>Items</th></tr></thead>
            <tbody>{s.steps.map((x) => <tr key={x.step}><td className="l">{x.step}</td><td className="l">{x.ok ? <span className="pill-ok">ok</span> : <span className="pill-bad">{x.reason}</span>}</td><td>{x.items ?? ""}</td></tr>)}</tbody>
          </table></div>
        </div>
      ) : <div className="banner warn">No API sync has run yet. Add <code>SOCCER_API_KEY</code> as a repository secret and run the “Update data” workflow.</div>}

      <h2>Odds provider 2 (The Odds API)</h2>
      {meta.odds_sync ? (
        <div className="glass pad small">
          <p>Credits remaining this month: <b>{meta.odds_sync.credits_remaining ?? "unknown"}</b></p>
          <ul>{meta.odds_sync.steps.map((x, k) => <li key={k}>{x.step}: {x.ok ? <span className="pill-ok">ok</span> : <span className="pill-bad">failed</span>} {x.reason ?? ""} {x.items !== undefined ? `(${x.items} events)` : ""}</li>)}</ul>
        </div>
      ) : <p className="muted">Not configured (optional). Set <code>ODDS_API_KEY</code> to add a second odds source.</p>}

      <h2>Data-quality flags</h2>
      {meta.quality.issues.length ? <div className="banner warn"><ul style={{ margin: 0 }}>{meta.quality.issues.map((i) => <li key={i}>{i}</li>)}</ul></div> : <p className="pill-ok">No issues flagged.</p>}

      <h2>Unmatched team names</h2>
      <p className="small muted">Names from a source that could not be matched to the historical spelling. Add them to <code>team_aliases.yaml</code> so a club's history isn't split in two.</p>
      {meta.unmapped_names.length ? <div className="glass pad small">{meta.unmapped_names.join(" · ")}</div> : <p className="pill-ok">All names matched.</p>}

      <h2>Betting rules in force</h2>
      <div className="glass pad"><pre className="small" style={{ margin: 0, whiteSpace: "pre-wrap" }}>{JSON.stringify(meta.betting_rules, null, 2)}</pre></div>
    </>
  );
}

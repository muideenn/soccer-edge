export type Num = number | null;

export interface Selection {
  match_id: string;
  market: string;
  selection: string;
  line: Num;
  odds: number;
  odds_source: string;
  odds_timestamp: string | null;
  n_books: number;
  ref_odds: Num;
  implied_p: number;
  model_p: number;
  ev: number;
  ev_lo: number;
  edge_pct: number;
  decision: "BET" | "NO BET";
  reason: string;
  stake_frac: number;
  fair_odds: Num;
  demo?: boolean;
}

export interface FormRow { date: string; comp: string; opponent: string; venue: "H" | "A"; score: string; result: "W" | "D" | "L" }

export interface Injury {
  team: string;
  player: string;
  type: string | null;
  reason: string | null;
}

export interface Fixture {
  match_id: string;
  comp: string;
  round: string | null;
  date: string;
  kickoff_user_tz: string;
  kickoff_utc: string | null;
  venue: string | null;
  home: string;
  away: string;
  home_logo: string | null;
  away_logo: string | null;
  status: string;
  data_ok: boolean;
  missing_results?: number;
  last_result_in_data: string;
  days_since_last_result: number;
  elo_diff_incl_home: Num;
  p_home?: number;
  p_draw?: number;
  p_away?: number;
  "p_over2.5"?: number;
  p_btts?: number;
  "p_over1.5"?: number;
  "p_over3.5"?: number;
  p_home_q10?: number;
  p_home_q90?: number;
  p_draw_q10?: number;
  p_draw_q90?: number;
  p_away_q10?: number;
  p_away_q90?: number;
  "p_over2.5_q10"?: number;
  "p_over2.5_q90"?: number;
  p_btts_q10?: number;
  p_btts_q90?: number;
  xg_home?: number;
  xg_away?: number;
  ep_p_home?: Num;
  ep_p_draw?: Num;
  ep_p_away?: Num;
  top_scores?: string;
  score_grid?: number[][];
  anchored_to_market?: boolean;
  reference_book?: string | null;
  market_p_home?: number;
  market_p_draw?: number;
  market_p_away?: number;
  confidence: "LOW" | "MEDIUM" | "HIGH";
  confidence_reason: string;
  injuries: Injury[];
  decision: "BET" | "NO BET";
  selections: Selection[];
  joint_grid?: number[][];
  corner_grid?: number[][];
  xc_home?: number;
  xc_away?: number;
  corners_ok?: boolean;
  corners_last_data?: string | null;
  "p_corners_over7.5"?: number;
  "p_corners_over8.5"?: number;
  "p_corners_over9.5"?: number;
  "p_corners_over10.5"?: number;
  "p_corners_over11.5"?: number;
  "p_corners_over12.5"?: number;
  form_home?: FormRow[];
  form_away?: FormRow[];
  model_inputs?: Record<string, number | null>;
  odds_are_demo?: boolean;
}

export interface Matchday {
  as_of: string;
  user_timezone: string;
  leagues: string[];
  n_fixtures: number;
  n_bets: number;
  odds: { sources?: string[]; ah_convention?: string; bookmakers?: string[]; n_rows?: number };
  fixtures: Fixture[];
}

export interface SummaryRow {
  bets: number;
  hit_rate: number;
  avg_odds: number;
  avg_ev_claimed: number;
  roi_flat: number;
  roi_ci95_lo: Num;
  roi_ci95_hi: Num;
  profit_units: number;
  max_drawdown_units: number;
  longest_losing_streak: number;
  market?: string;
  comp?: string;
  season?: number;
}

export interface Strategy {
  summary: Record<string, SummaryRow[]>;
  equity: { date: string; units: number; n: number }[];
  bankroll: { date: string; bankroll: number }[];
}

export interface Performance {
  meta: {
    ensemble: { weights: Record<string, number>; bet_model: string };
    anchor_weight_model: number;
    bankroll: Record<string, { final: number; min: number; max_drawdown_pct: number }>;
    n_test_matches: number;
  };
  prob_metrics: { model: string; subset: string; n: number; logloss: number; brier: number; rps: number; accuracy: number }[];
  totals: { model: string; n: number; logloss: number; brier: number }[];
  ucl: { model: string; n: number; logloss: number; brier: number; rps: number }[];
  calibration: { model: string; outcome: string; bin: string; n: number; mean_pred: number; observed: number }[];
  strategies: Record<string, Strategy>;
  corners?: {
    dispersion_k: number | null;
    lines: { line: number; n: number; observed_over: number; model_mean_p: number; logloss_model: number; logloss_base_rate: number; brier_model: number; brier_base_rate: number }[];
    calibration_over9_5: { mean_pred: number; observed: number; n: number }[];
    mean_total_pred: number;
    mean_total_obs: number;
    note: string;
  } | null;
}

export interface Paper {
  rows: Record<string, string | number | null>[];
  summary: { logged: number; bets: number; settled_bets: number; roi?: Num; profit_units?: number; clv_mean?: Num };
}

export interface Meta {
  generated_utc: string;
  as_of: string;
  model_version: string;
  config_hash: string;
  demo: boolean;
  disclaimer: string;
  sources: Record<string, Record<string, string | number | null>>;
  quality: { issues: string[]; stats: Record<string, string | number | boolean | null> };
  unmapped_names: string[];
  sync: null | {
    provider: string;
    started: string;
    finished?: string;
    requests_used?: number;
    remaining_today?: Num;
    steps: { step: string; ok: boolean; items?: number; reason?: string }[];
    warnings: string[];
  };
  betting_rules: Record<string, unknown>;
  sportmonks_sync?: { steps: { step: string; ok: boolean; reason?: string; items?: number }[]; warnings: string[]; calls_used?: number; rate_limit?: Record<string, unknown> | null } | null;
  source_conflicts?: { comp: string; home: string; away: string; reports: { source: string; date: string; score: string }[] }[];
  odds_sync?: { provider: string; steps: { step: string; ok: boolean; reason?: string; items?: number }[]; credits_remaining?: string | null } | null;
}

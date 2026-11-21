# Soccer Edge

Match probabilities, singles, a parlay builder and a daily **featured 10–20 leg parlay** generator for the Premier League, La Liga, Bundesliga, Serie A, Ligue 1 and the Champions League. It covers goals markets **and corners**.

How it runs:
- A Python pipeline pulls data, retrains the models and publishes JSON. It runs on GitHub Actions, which is server side and holds the keys.
- A React site (dark, animated, accessible) reads that JSON and is hosted on **GitHub Pages** or **Vercel**.

> **Gambling risk.** Every number here is an estimate. Parlays have a high chance of losing, and 10–20 leg parlays lose the large majority of the time. Out-of-sample testing found no demonstrated edge over bookmaker prices from results data alone, so the default single decision is **NO BET**. Bet only where legal, only with money you can afford to lose, and never chase losses or borrow to bet. US help: 1-800-GAMBLER · UK: BeGambleAware.

---

## 1. Quick start (demo mode, no keys)

```bash
git clone <your-repo> soccer-edge && cd soccer-edge
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
./fetch_data.sh                       # ~120 MB of public historical data
python -m soccer_edge.cli export      # builds web/public/data/*.json (demo odds when no keys)
cd web && npm install && npm test && npm run dev    # http://localhost:5173
```

Without keys the site runs in **demo mode**:
- Ratings come from the bundled historical snapshot.
- Prices are **synthetic**: model probability plus a bookmaker-style margin. They are labelled "DEMO (synthetic)" everywhere and are never paper-logged or recommended.
- The site shows a demo banner on every page that uses them.

## 2. Adding your API keys

| Variable | Needed? | Provider | Used for |
|---|---|---|---|
| `SOCCER_API_KEY` | for live data | API-Football v3 (direct or via RapidAPI) | fixtures, results, pre-match odds (incl. corners), injuries, match statistics |
| `SOCCER_API_PROVIDER` | optional | `apisports` (default) or `rapidapi` | which API-Football endpoint and header to use |
| `ODDS_API_KEY` | optional | The Odds API v4 | second odds source for 1X2 and goal totals (more bookmakers to shop) |

Keys are read **only** by the Python pipeline (`soccer_edge/env.py`):
- They are never written to disk, logs or the published JSON; error messages are redacted.
- The web app never sees them.
- `npm run build` fails if any `VITE_*` variable looks like a secret, or if a key's value appears anywhere in `dist/`.
- Never create `VITE_…` or `NEXT_PUBLIC_…` versions of these.

### Option A: local Bash
```bash
cp .env.example .env.local          # .env.local is in .gitignore — check with: git check-ignore .env.local
nano .env.local                     # paste your keys after the = signs
python -m soccer_edge.cli check-env # prints "set"/"missing" without revealing values
python -m soccer_edge.cli update    # sync APIs + refit + export JSON
cd web && npm run build             # site builds from the JSON; keys are not involved
```
Alternatively, export for one shell session only (nothing is saved):
```bash
read -rs SOCCER_API_KEY && export SOCCER_API_KEY   # type/paste, press Enter; not echoed, not in history
export SOCCER_API_PROVIDER=apisports
python -m soccer_edge.cli update
```

### Option B: GitHub Secrets (production)
1. Repository → **Settings → Secrets and variables → Actions → New repository secret**:
   - `SOCCER_API_KEY` = your API-Football key
   - `ODDS_API_KEY` = your The Odds API key (optional)
2. **Variables** tab (optional): `SOCCER_API_PROVIDER` = `rapidapi` if your key came from RapidAPI.
3. **Actions → "Update data and site" → Run workflow.**

The workflow passes the secrets only to the Python step (`.github/workflows/update.yml`). The web build step has no secrets in its environment. The same workflow runs twice a day.

Or with the GitHub CLI:
```bash
gh secret set SOCCER_API_KEY          # prompts for the value; nothing lands in shell history
gh secret set ODDS_API_KEY
gh variable set SOCCER_API_PROVIDER --body apisports
gh workflow run "Update data and site"
```

## 3. Build and deploy

| Command | What it does |
|---|---|
| `python -m soccer_edge.cli update` | sync API-Football + The Odds API (budgeted), refit models, price every market, paper-log, settle, export JSON |
| `python -m soccer_edge.cli export` | same without network calls (demo mode if no odds cached) |
| `python -m soccer_edge.cli backtest` / `corners-eval` | full walk-forward evaluation (~6 min) / corners evaluation (~20 s) |
| `cd web && npm run build` | type-check, bundle to `web/dist/`, run the secret-leak check |
| `cd web && npm test` / `python -m pytest -q tests` | parlay-maths tests / 34 pipeline tests incl. a full mocked-API run |

**Hosting:**
- **GitHub Pages:** *Settings → Pages → Source: GitHub Actions*. `update.yml` builds with `BASE_PATH=/<repo>/` and deploys.
- **Vercel:** import the repository; `vercel.json` sets `cd web && npm ci && npm run build` with output `web/dist`. Then add a repository **variable** `DEPLOY_TARGET=vercel` so the workflow stops deploying to Pages. Vercel rebuilds whenever the workflow commits fresh data. No environment variables are needed on Vercel, because the site only reads committed JSON.

**The build never needs keys.** CI (`ci.yml`) builds and tests in demo mode on every push.

## 4. What's on the site
- **Today:** animated match cards with home/draw/away probabilities, xG, over 2.5, BTTS and expected corners, plus stale-data badges. Search by team or match; filter by date and competition.
- **Match panel:** keyboard-accessible dialog with four tabs:
  - **Prediction:** probability ranges, correct-score heat map, market vs model.
  - **Markets:** every price at the best available book, with update time, model probability, implied probability, EV, decision and reason. Add to slip.
  - **Corners:** an interactive distribution with an adjustable line.
  - **Form & inputs:** last five results, attack/defence ratings, Elo, rest days, injuries.
- **Singles:** every priced selection with filters (date, league, team/match, market, odds range), sorting, and an interactive probability-vs-price scatter (click or press Enter to add to the slip).
- **Parlay builder:** add and remove legs. It shows:
  - combined odds, estimated chance, EV, risk rating and "loses about N in M";
  - a stake calculator;
  - payout-vs-chance charts;
  - every assumption behind the numbers.
- **Featured 10–20:** generates candidates from your criteria:
  - **Criteria:** leg count, odds per leg, minimum leg probability, competitions, markets, teams to include or exclude, ranking rule (highest chance / best EV / balanced slider), positive-EV-only, exclude stale data, exclude corners.
  - **Results:** up to three ranked candidates, plus a tradeoff chart of chance, odds and EV against leg count.
  - **When nothing qualifies,** it says so and explains why.
- **Performance:** backtest accuracy versus the market, strategy equity curves, calibration, the corners evaluation, and live paper tracking with closing-line value.
- **Data:** sources and timestamps, sync logs, remaining API quota, plan warnings, quality flags, and team names still needing an alias.

### How parlays are computed (and why "favourable and winnable" has limits)
- **Eligible legs** cannot push or half-settle: 1X2, double chance, BTTS, and x.5 lines for totals, team totals, Asian handicaps and corners.
- **Probability per leg** is the model's, anchored to a sharp reference bookmaker (Pinnacle, then Bet365, else the consensus), because the market beat the raw model in testing. A leg only shows positive EV when another book's price is better than the reference's fair price, which is line shopping.
- **Same-match legs** are combined **exactly** from that match's simulated score grid (goals) or corner grid (corners), so correlation inside a match is modelled. Goal and corner legs in the same match, and legs from different matches, are treated as independent and **labelled as an approximation**.
- **Featured candidates** use one leg per match. They take the best leg in each match under your ranking rule, then the top N matches. That is the exact optimum for the rule, and it keeps cross-match independence as the only assumption.
- **Risk ratings:** Elevated / High / Very high / Extreme / Lottery-like, always shown as an icon plus words. A 10+ leg parlay is never rated below *Very high*.
- **The honest arithmetic:** at 80% per leg, a 10-leg parlay wins about 11% of the time and a 20-leg parlay about 1%. Each leg's bookmaker margin compounds, so most long parlays have **negative** expected value. By default the featured section only shows positive-EV candidates and will often say none exist. That is the correct output, not a bug.

## 5. Data providers and their limitations
- **API-Football v3** (`SOCCER_API_KEY`). The free plan is 100 requests/day; Pro is 7,500/day.
  - **Budget:** each run is capped by `api.run_budget` (45) and stops when the API reports ≤2 requests left. API-Football's own plan messages appear on the Data page.
  - **Odds:** pre-match odds include the documented "Corners Over Under" bet. Asian handicap text is parsed with an auto-detected sign convention.
  - **Per-match statistics** (corners, shots) cost 1 request per match. They're off by default (`sync_fixture_statistics`); turn them on with a paid plan so corner ratings stay current.
  - **Team logos** come from API-Football and are shown only beside team names. Check API-Football's terms for your use; the animated background never uses real crests or league logos. It draws generic footballs, pitch lines and abstract shields with team initials.
- **The Odds API v4** (`ODDS_API_KEY`):
  - **Markets:** only its documented featured markets are used, h2h (1X2) and totals. Corners are not requested from it.
  - **Cost:** each call costs markets × regions credits; the free plan is 500 credits/month. The default (2 markets × 1 region × 6 competitions, at most once every 20 h) is about 370 credits/month.
- **Historical archive** (football-data.co.uk via a GitHub mirror, openfootball, ClubElo): results, shots, corners and Bet365 odds used for training and backtesting.
- **Gaps:** no lineups or xG. Injuries are displayed, not modelled. UCL and corner betting rules can't be validated because there are no historical UCL or corner odds. Corner ratings go stale without per-match statistics. Kickoff times from openfootball can be provisional.

If a provider is down, slow or incomplete, the site keeps working from the last good data:
- Stale ratings block bets and show "stale data" badges.
- A data file older than 36 h triggers a top-of-page warning.
- Missing odds produce clear empty states.
- Malformed API items are rejected and counted on the Data page.

{findings}{method}### Corners model
- **Ratings:** each team gets time-weighted corners-won and corners-conceded ratings (penalised Poisson regression; half-life about 9 months; strong shrinkage chosen on validation).
- **Counts:** match counts follow negative-binomial marginals (dispersion k = 12, chosen on 2019–21).
- **Out of sample (2022–26, 7,044 matches):** it beats base rates on every total line (e.g. over 9.5 log loss 0.684 vs 0.697), with mean total 9.63 predicted vs 9.65 observed.
- **Calibration:** reasonable in the middle and slightly under-predicts overs in low-corner matchups.
- **Odds:** there is no historical corner-odds archive, so corner prices are screened and usable in parlays (tagged *unvalidated*) but never recommended as singles.

## 6. Typography
The site uses **CMU Serif** (Computer Modern, the default LaTeX typeface), bundled from `web/src/fonts/` under the SIL Open Font License (`OFL-CMU.txt`). It is subset to Latin characters and punctuation (~165 KB total), so it loads the same everywhere without a font CDN. If it fails to load, the stack falls back to Latin Modern, then **Times New Roman**, then the system serif. To switch to plain Times New Roman, edit `--font` at the top of `web/src/styles.css`.

## 7. Accessibility and motion
- **Keyboard:** every control works from the keyboard, with a skip link, visible focus rings, a match dialog that traps focus and closes on Esc, and arrow keys to switch tabs.
- **Labels:** charts and controls have accessible labels; tooltips open on focus and close on Esc.
- **Not colour alone:** predictions, risk and decisions use icons and words as well as colour.
- **Contrast:** dark-theme contrast meets WCAG AA for body text.
- **Motion:** the animated background pauses when the tab is hidden, can be stopped with the **Pause motion** button (remembered), and is off by default when the OS asks for reduced motion. Forced-colours mode hides it.

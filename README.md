# FX research dashboard

A static research page for 28 major and minor FX pairs. It has two views of the same weekday window:

- **OLS regression matrix** — daily log returns, and log prices (`ln Y = a + b ln X`).
- **Kalman hedge & spread** — a time-varying hedge ratio, and tests on the tradeable re-hedged spread.

Research only. The page does not place orders, size positions, or recommend trades. There are no exotic pairs.

The generated file is one self-contained `site/index.html` (vanilla JS and SVG, no network once it is open). The same payload is written to `site/data.json`. GitHub Actions rebuilds that site on weekday nights and publishes it with GitHub Pages.

## Universe

EURUSD, GBPUSD, USDJPY, USDCHF, AUDUSD, USDCAD, NZDUSD, EURGBP, EURJPY, EURCHF, EURAUD, EURCAD, EURNZD, GBPJPY, GBPCHF, GBPAUD, GBPCAD, GBPNZD, AUDJPY, AUDCHF, AUDCAD, AUDNZD, NZDJPY, NZDCHF, NZDCAD, CADJPY, CADCHF, CHFJPY.

## Landing page

The page opens on one table of pairs that pass the Kalman screen (ADF p < 0.05, KPSS p > 0.05, half-life 3–30 days, |z| ≥ 2), sorted by |z|. A watchlist underneath uses the same stationarity and half-life filters with 1.5 ≤ |z| < 2. Columns are the pair, Kalman z, half-life, current beta, and Rolling agrees.

Rolling agrees is yes when the 120-day rolling OLS z has the same sign as the Kalman z and |rolling z| ≥ 1.5. The older rolling stationarity flag is still computed and stored; it is not the column on the landing table.

Clicking a row opens `#pair=EURUSD_GBPUSD` with the Kalman z-score and lines at 0 and ±2. The OLS and Kalman matrices, currency overlap, and method notes are behind **More** (`#more`). The header says “Research only, not trading advice” and “Data as of …”. A warning appears when that timestamp is more than three days old.

## Opportunities

The landing view is a research screen, not a trade list. A pair is an opportunity only when all of these hold on the Kalman tradeable spread:

- ADF p < 0.05 and KPSS p > 0.05
- half-life between 3 and 30 trading days
- current |z| ≥ 2

The table sorts by |z|. Positive z is labelled spread rich (the spread is high in its own window); negative z is spread cheap. The watchlist uses the same stationarity and half-life filters with 1.5 ≤ |z| < 2.

Each row has a 120-day rolling OLS cross-check. The hedge for each day is ordinary least squares of ln Y on ln X over the previous 120 closes, not including that day. The re-hedged spread is then tested the same way. The column is yes only when that spread is stationary and its |z| is at least 2.

Currency tags are the currencies inside the two pair names. A banner counts how many opportunities share each currency. Two opportunities are marked similar when the correlation of their daily spread changes is above 0.8.

Clicking a row, or a cell on either full-screen heatmap, opens `#pair=EURUSD_GBPUSD` (Y_X in the Kalman orientation). That view charts the Kalman z-score with ±1 and ±2 bands, the filtered beta with its ±2 filter-standard-deviation band, and the rolling-OLS z-score.

The header and the footer both say “Research only, not trading advice”. If the snapshot timestamp is more than three days behind the clock on the machine opening the page, a stale-data warning is shown.

The OLS and Kalman matrices are unchanged and sit under **Full screen**.

## What the numbers are

Both tabs share the last 250 weekday sessions. Weekend bars are dropped. A date is kept only when every pair has a positive close that day. Nothing is interpolated.

The fetch asks Yahoo Finance for about 1,400 calendar days (`EURUSD=X` and the same `=X` suffix for the other pairs), retries when a response is short, and uses Stooq only for pairs Yahoo still cannot supply. The build stops if fewer than 28 pairs survive, or if the aligned history is shorter than 750 weekday closes (500 to estimate the Kalman variances, plus the 250-day window).

### OLS

- Returns are `r_t = ln(P_t / P_{t-1})`, regressed as `y = a + b x` for every ordered pair. Beta is the slope. R² and correlation are symmetric. The slope p-value is the two-sided t test.
- Log prices use the same 250 dates: `ln Y = a + b ln X`. Beta is a log hedge ratio (an elasticity), so it is comparable across pairs without rebasing. The residual `ln Y − a − b ln X` is the log spread.
- The residual ADF test includes a constant and selects its lag by AIC. The p-value is an ordinary ADF p-value, which is slightly liberal relative to MacKinnon cointegration critical values. It is not a Johansen test. Durbin–Watson is reported on the same residual.
- A directed fit is marked likely spurious when R² ≥ 0.5 and the residual ADF p-value ≥ 0.05.
- ADF p and Durbin–Watson exist only for log prices. While either metric is selected, the returns heatmap stays on R².

### Kalman

For each unordered pair the filter is oriented like the OLS upper triangle: Y is the earlier name in the pair list, X the later one (378 pairs).

- State: `ln Y_t = α_t + β_t ln X_t + e_t`, with a random-walk intercept and hedge ratio.
- Observation variance and the two state variances are fit by the Shumway–Stoffer EM algorithm on the 500 weekday closes that end the day before the window, then frozen. The filter runs through that sample and the window.
- The tested spread is the tradeable re-hedged spread. It starts at 0 on the first day of the window and accumulates `Δln Y − β_{t|t−1} Δln X`, using the hedge ratio known before that close.
- The level residual `ln Y − α_{t|t−1} − β_{t|t−1} ln X` is the filter innovation. On this basket it behaves like near-white noise, so it is not the stationarity verdict. The page states the median half-life from the run you are looking at.
- Tests on the tradeable spread: ADF (same settings as the OLS residual), KPSS with a constant and automatic lags (statsmodels caps those p-values at 0.01 and 0.10), an AR(1) half-life, and a variance-of-lagged-differences Hurst exponent (lags 2–20). The z-score uses the 250-day mean and sample standard deviation. It describes where the spread sits in its own window. It is not an entry or exit rule.
- Stationary, by default, means ADF p < 0.05 and KPSS p > 0.05. The table can be switched to ADF only.
- Static beta: the filtered beta’s standard deviation over the window is under 0.5% of |mean beta|, or the EM ratio `q_β / V_e` is under `1e-9`.
- Weak hedge: |beta| stays below 0.1 for the whole window, so the spread is close to Y alone.
- The OLS log-spread ADF is refit on the same 250 closes and shown next to the Kalman result.

The regression and filter code follows the previous research pipeline. Given the same closes, the OLS matrices and the Kalman EM match that implementation.

## Run it locally

Python 3.12.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m pipeline.build
```

Then open `site/index.html` in a browser. The fetch needs network access to Yahoo Finance. A partial download is retried; if 28 pairs are still not available the script exits with an error and does not write a new page.

Useful flags:

```bash
python -m pipeline.build --workers 4
python -m pipeline.build --from-csv pipeline/.cache/closes.csv
python -m pipeline.build --render-only
```

The first successful fetch stores the aligned panel in `pipeline/.cache/closes.csv` (gitignored). `--from-csv` refits from that file. `--render-only` rewrites `site/index.html` from the existing `site/data.json`.

Times on the page are South African Standard Time (Africa/Johannesburg, UTC+2, no daylight saving).

## GitHub Pages

The workflow `.github/workflows/pages.yml`:

- runs at **22:30 UTC, Monday–Friday** (00:30 SAST, Tuesday–Saturday),
- runs on a manual **workflow_dispatch**,
- runs on every **push to `main`**.

It installs `requirements.txt`, runs `python -m pipeline.build`, and deploys the `site/` directory with `actions/configure-pages`, `actions/upload-pages-artifact`, and `actions/deploy-pages`.

The committed `site/index.html` is a snapshot, so the page can be opened without waiting for Actions. The scheduled run does not commit a new HTML file back to the repository (that would retrigger the push event). Pages serves the artifact from the latest successful run, which can be newer than the snapshot in git.

### One-time setting

GitHub will not publish the site until Pages is switched to Actions:

1. Open this repository on GitHub.
2. Go to **Settings → Pages**.
3. Under **Build and deployment**, set **Source** to **GitHub Actions**.

After that, merge to `main` or run **Build and deploy FX dashboard** from the Actions tab. The site is served at:

https://yuvishkrishna-hash.github.io/FX-Dashboard-/

`site/data.json` is published next to the page at `data.json` on that same path. The HTML does not fetch it; the data is embedded so the file still works offline.

## Caveats

- If the page is built while the FX session is open, Yahoo’s latest daily bar can still be incomplete. The weekday job is timed for after the New York close.
- ADF p-values here are standard ADF p-values, not MacKinnon cointegration critical values.
- KPSS p-values are capped at 0.01 and 0.10 by the test’s published tables. A value of 0.10 means “0.10 or larger”.
- A static-beta Kalman fit is close to ordinary least squares. A weak hedge can look stationary because one leg is stationary on its own. Both are flagged.
- The z-score, half-life, and Hurst exponent are descriptions of the estimated spread. They are not trading signals.
- Yahoo’s daily FX print is the source of the closes. A bad print changes the matrices. The pipeline does not repair or fill prices.

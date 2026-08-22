# Magic Formula Dashboard

Daily-refreshed Magic Formula stock screener for NSE-listed companies with server-side AI stock analysis.

## Architecture

| Piece | Where | Notes |
|---|---|---|
| Frontend | `src/` (React + Vite + TS) | Static site; contains **no API keys** |
| Data pipeline | `data_pipeline/` (Python) | Scrapes Moneycontrol → ranks Magic Formula → writes `public/data/latest.json` |
| AI endpoint | `api/ai.ts` (Vercel Edge) | Gemini → Groq → HuggingFace fallback chain, keys stay server-side |
| Market context | `api/stock-context.ts` (Vercel Edge) | Yahoo Finance price/PE/news with 5-min TTL cache |

**Vercel is the primary deployment** (`https://mf-dashboard-three.vercel.app`) because it hosts the edge functions. GitHub Pages is a static mirror; it points at the Vercel API via `VITE_API_BASE_URL`.

AI provider keys live **only** as Vercel project environment variables:
- `GOOGLE_API_KEY` (or legacy `VITE_GOOGLE_API_KEY`)
- `GROQ_API_KEY` (or legacy `VITE_GROQ_API_KEY`)
- `HUGGINGFACE_API_KEY` (or legacy `VITE_HUGGINGFACE_API_KEY`)

Set them in Vercel → Project → Settings → Environment Variables.

## Commands

```bash
npm ci                        # frontend deps
npm run dev                   # local UI (API calls fail gracefully without vercel dev)
npm run build                 # typecheck + production build
npm run lint                  # eslint
npm run test:data             # python parser/model tests (pytest)

python -m pip install -r data_pipeline/requirements.txt      # pipeline deps
python -m pip install -r data_pipeline/requirements-dev.txt  # + pytest

npm run data:build            # rebuild rankings from cached/seed CSV
npm run data:scrape           # full live Moneycontrol scrape (~2000 symbols)
```

## Data refresh & deployment

`.github/workflows/deploy-pages.yml` runs on:

- every **push** (full scrape)
- daily **cron** at 22:30 UTC = 04:00 IST (full scrape)
- manual `workflow_dispatch` with modes: `scrape`, `test-scrape`, `seed`
- `repository_dispatch` of type `refresh-data`

Each run: scrape → success-rate gate → build frontend → lint/tests already done → deploy `dist` to **GitHub Pages** and to **Vercel** (`VERCEL_TOKEN` secret).

### Success-rate gate

If fewer than `MF_MIN_SUCCESS_RATE` (default `0.6`) of attempted symbols produce rows, the job fails instead of deploying a gutted dataset. A `[Summary] Scraped X/Y symbols` line always prints.

## Valuation methodology

- **EPV (intrinsic value):** `PBIT/share × (1 − tax_rate) ÷ required_earnings_yield`, defaults 25% and 10% (`MF_VALUATION_TAX_RATE`, `MF_VALUATION_REQUIRED_EARNINGS_YIELD`)
- **Graham Number:** `√(22.5 × TTM EPS × BVPS)`
- **PBIT/share:** derived from annual EBIT (profit-loss page) scaled by `previous_close / market_cap`
- **Enterprise Value:** *market-cap proxy* — net debt is not subtracted
- **Return on Capital:** EBIT ÷ book equity, where book equity = BVPS × market_cap ÷ previous_close

These are screen-level estimates, not a DCF. Banks/financials often yield NaN PBIT/ROCE and are naturally filtered out by ranking. Current method metadata ships inside `latest.json` under `valuation`.

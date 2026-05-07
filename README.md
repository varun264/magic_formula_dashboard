# Magic Formula Dashboard

Automated React + Vite dashboard for monthly Magic Formula stock recommendations.

## Local dashboard

```bash
npm install
npm run data:build
npm run dev
```

Open the local Vite URL and the dashboard will load `public/data/latest.json`.

## Refresh data

Use the bundled seed dataset:

```bash
npm run data:build
```

Scrape fresh Moneycontrol data:

```bash
python -m pip install -r data_pipeline/requirements.txt
npm run data:scrape
```

Generated dashboard assets:

- `public/data/latest.json`
- `public/data/magic_formula_top50.csv`

Each displayed stock in `latest.json` includes a `details` object with the fetched Moneycontrol fields and computed dashboard metrics. In the dashboard, click a recommendation card or table row to view those fields.

## Intrinsic value estimate

The dashboard displays a simple earnings-power intrinsic value estimate:

```text
intrinsic_value = PBIT/share * (1 - tax_rate) / required_earnings_yield
margin_of_safety = intrinsic_value / previous_close - 1
```

Default assumptions:

- `tax_rate`: `25%`
- `required_earnings_yield`: `10%`

These can be changed in workflow/environment variables:

- `MF_VALUATION_TAX_RATE`
- `MF_VALUATION_REQUIRED_EARNINGS_YIELD`

This is a screen-level estimate, not a full DCF.

## GitHub Pages

The workflow in `.github/workflows/deploy-pages.yml`:

- builds seed dashboard data on every push to `main`
- scrapes fresh Moneycontrol data every day at 00:30 UTC, which is 06:00 IST
- supports manual runs with `scrape`, `test-scrape`, or `seed` data modes
- supports `repository_dispatch` events of type `refresh-data`
- deploys the static dashboard to GitHub Pages

After pushing to GitHub, open **Settings > Pages** and set **Source** to **GitHub Actions**.

Manual test scrape example:

1. Open **Actions > Deploy dashboard to GitHub Pages > Run workflow**.
2. Set `data_mode` to `test-scrape`.
3. Set `symbol_limit` to a small number like `50`.

API trigger example:

```bash
curl -X POST \
  -H "Accept: application/vnd.github+json" \
  -H "Authorization: Bearer YOUR_GITHUB_TOKEN" \
  https://api.github.com/repos/varun264/magic_formula_dashboard/dispatches \
  -d '{"event_type":"refresh-data","client_payload":{"data_mode":"scrape"}}'
```

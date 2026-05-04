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

## GitHub Pages

The workflow in `.github/workflows/deploy-pages.yml`:

- builds seed dashboard data on every push to `main`
- scrapes fresh Moneycontrol data on the 5th day of every month at 03:00 UTC
- deploys the static dashboard to GitHub Pages

After pushing to GitHub, open **Settings > Pages** and set **Source** to **GitHub Actions**.

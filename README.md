# Magic Formula Dashboard

React + Vite dashboard for ranking Magic Formula candidates from CSV uploads.

## Run locally

```bash
npm install
npm run dev
```

## Build

```bash
npm run build
```

The production build is written to `dist/`.

## Deploy to GitHub Pages

This repo includes `.github/workflows/deploy-pages.yml`. After pushing to the `main` branch:

1. Open the GitHub repository.
2. Go to **Settings > Pages**.
3. Set **Source** to **GitHub Actions**.
4. Push to `main` or run the workflow manually from the **Actions** tab.

The Vite build uses a relative asset base, so it works from a user/organization Pages site or a project Pages path.

## CSV columns

Fundamentals CSV:

```text
ticker,ebit,market_cap,total_debt,preferred_equity,minority_interest,cash,net_ppe,working_capital,sector,country
```

Holdings CSV:

```text
ticker,buy_date,shares
```

import { useEffect, useMemo, useState } from "react";
import "./App.css";

type Recommendation = {
  magic_formula_rank: number;
  name: string;
  sc_sector: string | null;
  market_cap_cr: number;
  previous_close: number;
  enterprise_value_cr: number;
  earnings_yield: number;
  return_on_capital: number;
  ey_rank: number;
  roc_rank: number;
  combined_rank: number;
};

type DashboardData = {
  generated_at: string;
  source: string;
  scraped: boolean;
  filters: {
    minimum_market_cap_rs: number;
    top_n: number;
  };
  counts: {
    raw_rows: number;
    ranked_rows: number;
    recommendation_rows: number;
  };
  recommendations: Recommendation[];
};

const pctFmt = (value: number, digits = 1) => `${(value * 100).toFixed(digits)}%`;
const numFmt = (value: number, digits = 0) =>
  new Intl.NumberFormat(undefined, { maximumFractionDigits: digits }).format(value);
const dateFmt = (value: string) =>
  new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));

function App() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pickCount, setPickCount] = useState(3);
  const [query, setQuery] = useState("");
  const [sector, setSector] = useState("All sectors");

  useEffect(() => {
    fetch("./data/latest.json", { cache: "no-store" })
      .then((response) => {
        if (!response.ok) {
          throw new Error(`Data request failed with ${response.status}`);
        }
        return response.json() as Promise<DashboardData>;
      })
      .then((payload) => {
        setData(payload);
        setError(null);
      })
      .catch((caught: unknown) => {
        setError(caught instanceof Error ? caught.message : "Unable to load dashboard data.");
      });
  }, []);

  const sectors = useMemo(() => {
    if (!data) return [];
    return Array.from(new Set(data.recommendations.map((row) => row.sc_sector).filter(Boolean) as string[])).sort();
  }, [data]);

  const filtered = useMemo(() => {
    if (!data) return [];
    const normalizedQuery = query.trim().toLowerCase();
    return data.recommendations.filter((row) => {
      const matchesQuery = !normalizedQuery || row.name.toLowerCase().includes(normalizedQuery);
      const matchesSector = sector === "All sectors" || row.sc_sector === sector;
      return matchesQuery && matchesSector;
    });
  }, [data, query, sector]);

  const monthlyPicks = filtered.slice(0, pickCount);
  const allRows = filtered;

  if (error) {
    return (
      <main className="app-shell">
        <section className="panel error-panel">
          <h1>Magic Formula Dashboard</h1>
          <p>Dashboard data could not be loaded.</p>
          <code>{error}</code>
        </section>
      </main>
    );
  }

  if (!data) {
    return (
      <main className="app-shell">
        <section className="panel loading-panel">
          <h1>Magic Formula Dashboard</h1>
          <p>Loading latest recommendations...</p>
        </section>
      </main>
    );
  }

  return (
    <main className="app-shell">
      <header className="hero">
        <div>
          <p className="eyebrow">Magic Formula</p>
          <h1>Monthly Buy Recommendations</h1>
          <p className="lede">
            Ranked from {numFmt(data.counts.ranked_rows)} eligible stocks. Last refreshed {dateFmt(data.generated_at)}.
          </p>
        </div>
        <div className="hero-actions">
          <a className="button secondary" href="./data/magic_formula_top50.csv" download>
            Download CSV
          </a>
          <a className="button primary" href="./data/latest.json" target="_blank" rel="noreferrer">
            View Data
          </a>
        </div>
      </header>

      <section className="metric-grid">
        <Metric label="Top recommendations" value={data.counts.recommendation_rows} />
        <Metric label="Eligible universe" value={data.counts.ranked_rows} />
        <Metric label="Raw rows scraped" value={data.counts.raw_rows} />
        <Metric label="Min market cap" value={`Rs ${numFmt(data.filters.minimum_market_cap_rs / 1e7)} Cr`} />
      </section>

      <section className="panel">
        <div className="panel-header">
          <div>
            <h2>This Month</h2>
            <p>Highest combined Earnings Yield and Return on Capital ranks.</p>
          </div>
          <label className="compact-field">
            <span>Picks</span>
            <select value={pickCount} onChange={(event) => setPickCount(Number(event.target.value))}>
              {[1, 2, 3, 4, 5, 10].map((count) => (
                <option key={count} value={count}>
                  {count}
                </option>
              ))}
            </select>
          </label>
        </div>

        <div className="pick-grid">
          {monthlyPicks.map((row) => (
            <article className="pick-card" key={row.name}>
              <span className="rank-badge">#{row.magic_formula_rank}</span>
              <h3>{row.name}</h3>
              <p>{row.sc_sector ?? "Sector unavailable"}</p>
              <div className="pick-stats">
                <span>
                  <strong>{pctFmt(row.earnings_yield)}</strong>
                  EY
                </span>
                <span>
                  <strong>{pctFmt(row.return_on_capital)}</strong>
                  ROC
                </span>
                <span>
                  <strong>Rs {numFmt(row.market_cap_cr)} Cr</strong>
                  Mkt cap
                </span>
              </div>
            </article>
          ))}
        </div>
      </section>

      <section className="panel">
        <div className="panel-header table-tools">
          <div>
            <h2>Top 50 Ranking</h2>
            <p>Source: {data.source}. Build mode: {data.scraped ? "fresh scrape" : "seed data"}.</p>
          </div>
          <div className="toolbar">
            <label className="compact-field">
              <span>Search</span>
              <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Company" />
            </label>
            <label className="compact-field">
              <span>Sector</span>
              <select value={sector} onChange={(event) => setSector(event.target.value)}>
                <option>All sectors</option>
                {sectors.map((item) => (
                  <option key={item}>{item}</option>
                ))}
              </select>
            </label>
          </div>
        </div>

        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>#</th>
                <th>Company</th>
                <th>Sector</th>
                <th>EY</th>
                <th>ROC</th>
                <th>EY Rank</th>
                <th>ROC Rank</th>
                <th>Combined</th>
                <th>Mkt Cap</th>
                <th>EV</th>
                <th>Close</th>
              </tr>
            </thead>
            <tbody>
              {allRows.length === 0 ? (
                <tr>
                  <td className="empty" colSpan={11}>
                    No matching recommendations.
                  </td>
                </tr>
              ) : (
                allRows.map((row) => (
                  <tr key={row.name}>
                    <td>{row.magic_formula_rank}</td>
                    <td className="company-cell">{row.name}</td>
                    <td>{row.sc_sector ?? "-"}</td>
                    <td>{pctFmt(row.earnings_yield, 2)}</td>
                    <td>{pctFmt(row.return_on_capital, 2)}</td>
                    <td>{numFmt(row.ey_rank)}</td>
                    <td>{numFmt(row.roc_rank)}</td>
                    <td>{numFmt(row.combined_rank)}</td>
                    <td>Rs {numFmt(row.market_cap_cr)} Cr</td>
                    <td>Rs {numFmt(row.enterprise_value_cr)} Cr</td>
                    <td>Rs {numFmt(row.previous_close, 2)}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </section>

      <p className="disclaimer">Educational screen only. Verify financial statements, liquidity, and portfolio fit before placing trades.</p>
    </main>
  );
}

function Metric({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="metric">
      <strong>{value}</strong>
      <span>{label}</span>
    </div>
  );
}

export default App;

import { useEffect, useMemo, useState } from "react";
import "./App.css";
import { analyzeStock, parseAnalysis, type AnalysisResult } from "./services/ai";

type Recommendation = {
  magic_formula_rank: number;
  name: string;
  sc_sector: string | null;
  market_cap_cr: number;
  previous_close: number;
  pbit_per_share: number;
  owner_earnings_per_share: number;
  intrinsic_value: number;
  margin_of_safety: number;
  enterprise_value_cr: number;
  earnings_yield: number;
  return_on_capital: number;
  ey_rank: number;
  roc_rank: number;
  combined_rank: number;
  details?: Record<string, string | number | boolean | null>;
};

type DashboardData = {
  generated_at: string;
  source: string;
  scraped: boolean;
  filters: {
    minimum_market_cap_rs: number;
    top_n: number;
  };
  valuation: {
    method: string;
    formula: string;
    tax_rate: number;
    required_earnings_yield: number;
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
  const [selectedStock, setSelectedStock] = useState<Recommendation | null>(null);

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
        <Metric label="Required yield" value={pctFmt(data.valuation.required_earnings_yield)} />
        <Metric label="Min market cap" value={`Rs ${numFmt(data.filters.minimum_market_cap_rs / 1e7)} Cr`} />
      </section>

      <section className="panel valuation-panel">
        <div>
          <h2>Intrinsic Value Estimate</h2>
          <p>
            Estimated with earnings power value: PBIT/share after a {pctFmt(data.valuation.tax_rate)} tax assumption,
            capitalized at a {pctFmt(data.valuation.required_earnings_yield)} required earnings yield.
          </p>
        </div>
        <code>Intrinsic value = PBIT/share * (1 - tax rate) / required earnings yield</code>
      </section>

      <section className="panel">
        <div className="panel-header">
          <div>
            <h2>This Month</h2>
            <p>Highest combined Earnings Yield and Return on Capital ranks. Click a stock to inspect fetched data.</p>
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
            <button className="pick-card" key={row.name} onClick={() => setSelectedStock(row)} type="button">
              <span className="rank-badge">#{row.magic_formula_rank}</span>
              <h3>{row.name}</h3>
              <p>{row.sc_sector ?? "Sector unavailable"}</p>
              <div className="pick-stats">
                <span>
                  <strong>Rs {numFmt(row.intrinsic_value, 2)}</strong>
                  Intrinsic
                </span>
                <span>
                  <strong className={row.margin_of_safety >= 0 ? "positive" : "negative"}>
                    {pctFmt(row.margin_of_safety)}
                  </strong>
                  Margin
                </span>
                <span>
                  <strong>Rs {numFmt(row.previous_close, 2)}</strong>
                  Close
                </span>
              </div>
            </button>
          ))}
        </div>
      </section>

      <section className="panel">
        <div className="panel-header table-tools">
          <div>
            <h2>Top 50 Ranking</h2>
            <p>Source: {data.source}. Build mode: {data.scraped ? "fresh scrape" : "seed data"}. Click any row for full fetched fields.</p>
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
                <th>Intrinsic</th>
                <th>Margin</th>
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
                  <td className="empty" colSpan={13}>
                    No matching recommendations.
                  </td>
                </tr>
              ) : (
                allRows.map((row) => (
                  <tr className="clickable-row" key={row.name} onClick={() => setSelectedStock(row)}>
                    <td>{row.magic_formula_rank}</td>
                    <td className="company-cell">{row.name}</td>
                    <td>{row.sc_sector ?? "-"}</td>
                    <td>{pctFmt(row.earnings_yield, 2)}</td>
                    <td>{pctFmt(row.return_on_capital, 2)}</td>
                    <td>Rs {numFmt(row.intrinsic_value, 2)}</td>
                    <td className={row.margin_of_safety >= 0 ? "positive" : "negative"}>{pctFmt(row.margin_of_safety, 1)}</td>
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

      {selectedStock ? <StockDetails stock={selectedStock} onClose={() => setSelectedStock(null)} /> : null}
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

function StockDetails({ stock, onClose }: { stock: Recommendation; onClose: () => void }) {
  const details = Object.entries(stock.details ?? {})
    .filter(([, value]) => value !== null && value !== "")
    .sort(([left], [right]) => left.localeCompare(right));

  const [analysis, setAnalysis] = useState<AnalysisResult | null>(null);
  const [loading, setLoading] = useState(false);

  const handleAnalyze = () => {
    if (analysis || loading) return;
    setLoading(true);
    analyzeStock({
      name: stock.name,
      sector: stock.sc_sector,
      marketCapCr: stock.market_cap_cr,
      previousClose: stock.previous_close,
      intrinsicValue: stock.intrinsic_value,
      marginOfSafety: stock.margin_of_safety,
      earningsYield: stock.earnings_yield,
      returnOnCapital: stock.return_on_capital,
      rank: stock.magic_formula_rank,
      eyRank: stock.ey_rank,
      rocRank: stock.roc_rank,
      details: stock.details,
    }).then((text) => {
      setAnalysis(parseAnalysis(text));
      setLoading(false);
    });
  };

  const verdictClass = analysis?.verdict === "BUY" ? "verdict-buy" : analysis?.verdict === "SELL" ? "verdict-sell" : "verdict-hold";

  return (
    <div className="modal-backdrop" role="presentation" onClick={onClose}>
      <section className="stock-modal" role="dialog" aria-modal="true" aria-labelledby="stock-detail-title" onClick={(event) => event.stopPropagation()}>
        <div className="modal-header">
          <div>
            <p className="eyebrow">Fetched Stock Data</p>
            <h2 id="stock-detail-title">{stock.name}</h2>
            <p>
              Rank #{stock.magic_formula_rank} - Intrinsic value Rs {numFmt(stock.intrinsic_value, 2)} - Margin{" "}
              <span className={stock.margin_of_safety >= 0 ? "positive" : "negative"}>{pctFmt(stock.margin_of_safety, 1)}</span>
            </p>
          </div>
          <button className="secondary close-button" onClick={onClose} type="button">
            Close
          </button>
        </div>

        <div className="detail-grid">
          <Metric label="Previous close" value={`Rs ${numFmt(stock.previous_close, 2)}`} />
          <Metric label="Intrinsic value" value={`Rs ${numFmt(stock.intrinsic_value, 2)}`} />
          <Metric label="Margin of safety" value={pctFmt(stock.margin_of_safety, 1)} />
          <Metric label="Sector" value={stock.sc_sector ?? "Unavailable"} />
        </div>

        <div className="ai-section">
          {!analysis && !loading ? (
            <button className="button secondary ai-trigger" onClick={handleAnalyze} type="button">
              Analyze with AI
            </button>
          ) : loading ? (
            <div className="ai-loading">Analyzing...</div>
          ) : (() => {
            const a = analysis!;
            return (
              <div className="ai-analysis">
                <span className={`verdict-badge ${verdictClass}`}>{a.verdict}</span>
                {a.reasons.length > 0 && (
                  <div className="analysis-block">
                    <p className="analysis-heading">Why</p>
                    <ul className="analysis-list">{a.reasons.map((r, i) => <li key={i}>{r}</li>)}</ul>
                  </div>
                )}
                {a.risks.length > 0 && (
                  <div className="analysis-block">
                    <p className="analysis-heading">Risks</p>
                    <ul className="analysis-list">{a.risks.map((r, i) => <li key={i}>{r}</li>)}</ul>
                  </div>
                )}
                {a.outlook && (
                  <div className="analysis-block">
                    <p className="analysis-heading">12-Month Outlook</p>
                    <p className="analysis-outlook">{a.outlook}</p>
                  </div>
                )}
              </div>
            );
          })()}
        </div>

        <div className="detail-table-wrap">
          <table>
            <thead>
              <tr>
                <th>Field</th>
                <th>Value</th>
              </tr>
            </thead>
            <tbody>
              {details.map(([key, value]) => (
                <tr key={key}>
                  <td className="field-cell">{humanizeKey(key)}</td>
                  <td>{formatDetailValue(value)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}

function humanizeKey(key: string) {
  return key
    .replace(/_/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function formatDetailValue(value: string | number | boolean | null) {
  if (value === null) return "-";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "number") {
    return Number.isInteger(value) ? numFmt(value) : numFmt(value, 4);
  }
  return value;
}

export default App;

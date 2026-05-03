import { useEffect, useMemo, useState } from "react";
import type { ChangeEvent } from "react";
import "./App.css";

type FundRow = {
  ticker: string;
  ebit: number | null;
  market_cap: number | null;
  total_debt: number | null;
  preferred_equity: number | null;
  minority_interest: number | null;
  cash: number | null;
  net_ppe: number | null;
  working_capital: number | null;
  sector: string | null;
  country: string | null;
};

type MFRow = FundRow & {
  enterprise_value: number | null;
  roc_denom: number | null;
  earnings_yield: number | null;
  roc: number | null;
  ey_rank: number;
  roc_rank: number;
  combined_rank: number;
  magic_rank: number;
};

type Holding = {
  ticker: string;
  buy_date: string;
  shares: number | null;
};

type CsvRecord = Record<string, string>;

const requiredCols = [
  "ticker",
  "ebit",
  "market_cap",
  "total_debt",
  "preferred_equity",
  "minority_interest",
  "cash",
  "net_ppe",
  "working_capital",
];

const sampleFundamentals: FundRow[] = [
  {
    ticker: "TST1",
    ebit: 120000000,
    market_cap: 1500000000,
    total_debt: 200000000,
    preferred_equity: 0,
    minority_interest: 0,
    cash: 100000000,
    net_ppe: 300000000,
    working_capital: 50000000,
    sector: "Industrials",
    country: "IN",
  },
  {
    ticker: "TST2",
    ebit: 80000000,
    market_cap: 900000000,
    total_debt: 100000000,
    preferred_equity: 0,
    minority_interest: 0,
    cash: 50000000,
    net_ppe: 250000000,
    working_capital: 60000000,
    sector: "Technology",
    country: "IN",
  },
];

const todayISO = () => new Date().toISOString().slice(0, 10);

const toNum = (value: string | number | null | undefined): number | null => {
  if (value === null || value === undefined) return null;
  if (typeof value === "number") return Number.isFinite(value) ? value : null;
  const text = value.trim().replace(/[,\s]/g, "");
  if (!text || text.toLowerCase() === "na" || text === "--") return null;
  const parsed = Number(text);
  return Number.isFinite(parsed) ? parsed : null;
};

const numFmt = (value: number | null | undefined, digits = 2) =>
  value === null || value === undefined || !Number.isFinite(value)
    ? "-"
    : new Intl.NumberFormat(undefined, { maximumFractionDigits: digits }).format(value);

const pctFmt = (value: number | null | undefined, digits = 2) =>
  value === null || value === undefined || !Number.isFinite(value) ? "-" : `${(value * 100).toFixed(digits)}%`;

const loadLocal = <T,>(key: string, fallback: T): T => {
  try {
    const saved = localStorage.getItem(key);
    return saved ? (JSON.parse(saved) as T) : fallback;
  } catch {
    return fallback;
  }
};

const saveLocal = (key: string, value: unknown) => {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    // Ignore storage failures in private windows or restricted browsers.
  }
};

const splitCsvLine = (line: string): string[] => {
  const cells: string[] = [];
  let current = "";
  let quoted = false;

  for (let i = 0; i < line.length; i += 1) {
    const char = line[i];
    const next = line[i + 1];

    if (char === '"' && quoted && next === '"') {
      current += '"';
      i += 1;
    } else if (char === '"') {
      quoted = !quoted;
    } else if (char === "," && !quoted) {
      cells.push(current.trim());
      current = "";
    } else {
      current += char;
    }
  }

  cells.push(current.trim());
  return cells;
};

const parseCSVText = (text: string): CsvRecord[] => {
  const rows = text
    .replace(/^\uFEFF/, "")
    .split(/\r?\n/)
    .filter((line) => line.trim().length > 0);

  if (rows.length === 0) return [];

  const headers = splitCsvLine(rows[0]).map((header) => header.trim());
  return rows.slice(1).map((row) => {
    const values = splitCsvLine(row);
    return headers.reduce<CsvRecord>((record, header, index) => {
      record[header] = values[index] ?? "";
      return record;
    }, {});
  });
};

const readCSVFile = async (file: File): Promise<CsvRecord[]> => {
  const text = await file.text();
  return parseCSVText(text);
};

const normalizedColumn = (row: CsvRecord, column: string) =>
  Object.keys(row).find((key) => key.trim().toLowerCase() === column);

const cell = (row: CsvRecord, column: string) => {
  const key = normalizedColumn(row, column);
  return key ? row[key] : "";
};

const normalizeFundRow = (row: CsvRecord): FundRow => ({
  ticker: String(cell(row, "ticker") || Object.values(row)[0] || "").trim().toUpperCase(),
  ebit: toNum(cell(row, "ebit")),
  market_cap: toNum(cell(row, "market_cap")),
  total_debt: toNum(cell(row, "total_debt")) ?? 0,
  preferred_equity: toNum(cell(row, "preferred_equity")) ?? 0,
  minority_interest: toNum(cell(row, "minority_interest")) ?? 0,
  cash: toNum(cell(row, "cash")) ?? 0,
  net_ppe: toNum(cell(row, "net_ppe")),
  working_capital: toNum(cell(row, "working_capital")),
  sector: cell(row, "sector") || null,
  country: cell(row, "country") || null,
});

const computeMF = (rows: FundRow[]): MFRow[] => {
  const enriched = rows.map((row) => {
    const ev =
      (row.market_cap ?? 0) +
      (row.total_debt ?? 0) +
      (row.preferred_equity ?? 0) +
      (row.minority_interest ?? 0) -
      (row.cash ?? 0);
    const rocDenom = (row.net_ppe ?? 0) + (row.working_capital ?? 0);
    const earningsYield = ev > 0 && row.ebit !== null ? row.ebit / ev : null;
    const roc = rocDenom > 0 && row.ebit !== null ? row.ebit / rocDenom : null;

    return {
      ...row,
      enterprise_value: ev > 0 ? ev : null,
      roc_denom: rocDenom > 0 ? rocDenom : null,
      earnings_yield: earningsYield,
      roc,
    };
  });

  const valid = enriched.filter((row) => row.earnings_yield !== null && row.roc !== null);
  const byEY = [...valid].sort((a, b) => b.earnings_yield! - a.earnings_yield!);
  const byROC = [...valid].sort((a, b) => b.roc! - a.roc!);
  const eyRank = new Map(byEY.map((row, index) => [row.ticker, index + 1]));
  const rocRank = new Map(byROC.map((row, index) => [row.ticker, index + 1]));

  return valid
    .map((row) => {
      const ey_rank = eyRank.get(row.ticker) ?? valid.length;
      const roc_rank = rocRank.get(row.ticker) ?? valid.length;
      return {
        ...row,
        ey_rank,
        roc_rank,
        combined_rank: ey_rank + roc_rank,
        magic_rank: 0,
      };
    })
    .sort((a, b) => {
      if (a.combined_rank !== b.combined_rank) return a.combined_rank - b.combined_rank;
      if (b.earnings_yield! !== a.earnings_yield!) return b.earnings_yield! - a.earnings_yield!;
      return b.roc! - a.roc!;
    })
    .map((row, index) => ({ ...row, magic_rank: index + 1 }));
};

const unique = (values: Array<string | null>) =>
  Array.from(new Set(values.filter((value): value is string => Boolean(value)))).sort();

const daysBetween = (fromIso: string, toIso: string) => {
  const from = new Date(`${fromIso}T00:00:00`);
  const to = new Date(`${toIso}T00:00:00`);
  if (!Number.isFinite(from.getTime()) || !Number.isFinite(to.getTime())) return Number.POSITIVE_INFINITY;
  return Math.floor((to.getTime() - from.getTime()) / 86400000);
};

const downloadCSV = (rows: Record<string, unknown>[], filename: string) => {
  const headers = Array.from(new Set(rows.flatMap((row) => Object.keys(row))));
  const escapeCell = (value: unknown) => {
    const text = value === null || value === undefined ? "" : String(value);
    return /[",\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
  };
  const csv = [headers.join(","), ...rows.map((row) => headers.map((header) => escapeCell(row[header])).join(","))].join("\n");
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
};

function App() {
  const [fundRaw, setFundRaw] = useState<FundRow[]>([]);
  const [holdings, setHoldings] = useState<Holding[]>(() => loadLocal("mf_holdings", []));
  const [asOf, setAsOf] = useState(() => loadLocal("mf_asof", todayISO()));
  const [minMktCap, setMinMktCap] = useState(() => loadLocal("mf_min_mkt_cap", 0));
  const [posEbit, setPosEbit] = useState(() => loadLocal("mf_pos_ebit", true));
  const [exSectors, setExSectors] = useState<string[]>(() => loadLocal("mf_ex_sectors", ["Financials", "Utilities"]));
  const [buysPerMonth, setBuysPerMonth] = useState(() => loadLocal("mf_buys_pm", 3));
  const [message, setMessage] = useState("Upload fundamentals to generate rankings.");

  useEffect(() => saveLocal("mf_holdings", holdings), [holdings]);
  useEffect(() => saveLocal("mf_asof", asOf), [asOf]);
  useEffect(() => saveLocal("mf_min_mkt_cap", minMktCap), [minMktCap]);
  useEffect(() => saveLocal("mf_pos_ebit", posEbit), [posEbit]);
  useEffect(() => saveLocal("mf_ex_sectors", exSectors), [exSectors]);
  useEffect(() => saveLocal("mf_buys_pm", buysPerMonth), [buysPerMonth]);

  const sectors = useMemo(() => unique(fundRaw.map((row) => row.sector)), [fundRaw]);

  const filtered = useMemo(
    () =>
      fundRaw.filter((row) => {
        const marketCapOk = (row.market_cap ?? 0) >= minMktCap;
        const ebitOk = !posEbit || (row.ebit ?? 0) > 0;
        const sectorOk = row.sector ? !exSectors.includes(row.sector) : true;
        return marketCapOk && ebitOk && sectorOk;
      }),
    [exSectors, fundRaw, minMktCap, posEbit],
  );

  const mf = useMemo(() => computeMF(filtered), [filtered]);

  const sells = useMemo(
    () => holdings.filter((holding) => daysBetween(holding.buy_date, asOf) >= 365),
    [asOf, holdings],
  );

  const buys = useMemo(() => {
    const sellTickers = new Set(sells.map((holding) => holding.ticker));
    const activeTickers = new Set(holdings.filter((holding) => !sellTickers.has(holding.ticker)).map((holding) => holding.ticker));
    return mf.filter((row) => !activeTickers.has(row.ticker)).slice(0, Math.max(1, buysPerMonth));
  }, [buysPerMonth, holdings, mf, sells]);

  const eqWeight = 1 / Math.max(1, holdings.length - sells.length + buys.length);

  const onUploadFund = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;
    const parsed = await readCSVFile(file);
    const rows = parsed.map(normalizeFundRow).filter((row) => row.ticker);
    setFundRaw(rows);

    const cols = new Set(Object.keys(parsed[0] ?? {}).map((column) => column.trim().toLowerCase()));
    const missing = requiredCols.filter((column) => !cols.has(column));
    setMessage(
      missing.length
        ? `Loaded ${rows.length} rows. Missing columns: ${missing.join(", ")}.`
        : `Loaded ${rows.length} fundamentals rows.`,
    );
  };

  const onUploadHoldings = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;
    const parsed = await readCSVFile(file);
    const rows = parsed
      .map((row) => ({
        ticker: String(cell(row, "ticker") || cell(row, "symbol") || Object.values(row)[0] || "").trim().toUpperCase(),
        buy_date: cell(row, "buy_date") || cell(row, "date") || todayISO(),
        shares: toNum(cell(row, "shares")),
      }))
      .filter((row) => row.ticker);
    setHoldings(rows);
    setMessage(`Imported ${rows.length} holdings.`);
  };

  const commitTrades = () => {
    const sellTickers = new Set(sells.map((holding) => holding.ticker));
    const kept = holdings.filter((holding) => !sellTickers.has(holding.ticker));
    const added = buys.map((buy) => ({ ticker: buy.ticker, buy_date: asOf, shares: null }));
    setHoldings([...kept, ...added]);
    setMessage(`Committed ${added.length} buys and ${sellTickers.size} sells to local session holdings.`);
  };

  const downloadFundTemplate = () =>
    downloadCSV(
      sampleFundamentals.map((row) => ({ ...row })),
      "magic_formula_template.csv",
    );

  return (
    <main className="app-shell">
      <header className="hero">
        <div>
          <p className="eyebrow">Magic Formula</p>
          <h1>Monthly Picks Dashboard</h1>
          <p className="lede">Upload fundamentals and holdings CSVs, screen candidates, and export this month's buy/sell list.</p>
        </div>
        <div className="hero-actions">
          <button className="secondary" onClick={downloadFundTemplate} type="button">
            Download Template
          </button>
          <button className="primary" onClick={() => downloadCSV(mf, "full_ranking.csv")} type="button" disabled={mf.length === 0}>
            Export Ranking
          </button>
        </div>
      </header>

      <section className="status-bar" aria-live="polite">
        <span>{message}</span>
        <span>{fundRaw.length} loaded / {mf.length} ranked</span>
      </section>

      <section className="layout-grid">
        <div className="panel wide">
          <div className="panel-header">
            <div>
              <h2>Data & Filters</h2>
              <p>Use one currency and unit scale across every financial column.</p>
            </div>
          </div>

          <div className="form-grid">
            <label>
              <span>Fundamentals CSV</span>
              <input type="file" accept=".csv" onChange={onUploadFund} />
            </label>
            <label>
              <span>Holdings CSV</span>
              <input type="file" accept=".csv" onChange={onUploadHoldings} />
            </label>
            <label>
              <span>As-of date</span>
              <input type="date" value={asOf} onChange={(event) => setAsOf(event.target.value)} />
            </label>
            <label>
              <span>Minimum market cap</span>
              <input type="number" value={minMktCap} min={0} onChange={(event) => setMinMktCap(Number(event.target.value || 0))} />
            </label>
            <label className="checkbox-row">
              <input type="checkbox" checked={posEbit} onChange={(event) => setPosEbit(event.target.checked)} />
              <span>Require positive EBIT</span>
            </label>
            <label>
              <span>Buys this month: {buysPerMonth}</span>
              <input
                type="range"
                min={1}
                max={10}
                value={buysPerMonth}
                onChange={(event) => setBuysPerMonth(Number(event.target.value))}
              />
            </label>
          </div>

          <div className="sector-list">
            <span className="label">Excluded sectors</span>
            {sectors.length === 0 ? <span className="muted">No sectors loaded</span> : null}
            {sectors.map((sector) => (
              <button
                key={sector}
                className={exSectors.includes(sector) ? "chip active" : "chip"}
                onClick={() =>
                  setExSectors((current) =>
                    current.includes(sector) ? current.filter((value) => value !== sector) : [...current, sector],
                  )
                }
                type="button"
              >
                {sector}
              </button>
            ))}
          </div>
        </div>

        <div className="panel">
          <div className="panel-header">
            <div>
              <h2>This Month</h2>
              <p>Equal weight target: {pctFmt(eqWeight, 1)}</p>
            </div>
          </div>

          <div className="summary-grid">
            <div>
              <strong>{buys.length}</strong>
              <span>Buys</span>
            </div>
            <div>
              <strong>{sells.length}</strong>
              <span>Sells</span>
            </div>
            <div>
              <strong>{holdings.length}</strong>
              <span>Holdings</span>
            </div>
          </div>

          <div className="button-row">
            <button className="secondary" onClick={() => downloadCSV(buys, "buys.csv")} disabled={buys.length === 0} type="button">
              Export Buys
            </button>
            <button className="secondary" onClick={() => downloadCSV(sells, "sells.csv")} disabled={sells.length === 0} type="button">
              Export Sells
            </button>
          </div>

          <button className="primary full" onClick={commitTrades} disabled={buys.length === 0 && sells.length === 0} type="button">
            Commit Trades Locally
          </button>
        </div>
      </section>

      <section className="layout-grid">
        <div className="panel">
          <div className="panel-header">
            <div>
              <h2>Buys</h2>
              <p>Top ranked names not currently held.</p>
            </div>
          </div>
          <DataTable
            empty="No buy candidates"
            headers={["Rank", "Ticker", "EY", "ROC"]}
            rows={buys.map((row) => [row.magic_rank, row.ticker, pctFmt(row.earnings_yield), pctFmt(row.roc)])}
          />
        </div>

        <div className="panel">
          <div className="panel-header">
            <div>
              <h2>Sells</h2>
              <p>Positions at least 365 days old.</p>
            </div>
          </div>
          <DataTable empty="No mandatory sells" headers={["Ticker", "Buy Date"]} rows={sells.map((row) => [row.ticker, row.buy_date])} />
        </div>
      </section>

      <section className="panel">
        <div className="panel-header">
          <div>
            <h2>Full Ranking</h2>
            <p>Rows with invalid enterprise value or capital denominator are excluded.</p>
          </div>
        </div>
        <DataTable
          empty="Upload fundamentals to see rankings"
          headers={["#", "Ticker", "Sector", "EY", "ROC", "EY Rank", "ROC Rank", "Combined", "EV", "Mkt Cap"]}
          rows={mf.map((row) => [
            row.magic_rank,
            row.ticker,
            row.sector ?? "-",
            pctFmt(row.earnings_yield),
            pctFmt(row.roc),
            row.ey_rank,
            row.roc_rank,
            row.combined_rank,
            numFmt(row.enterprise_value),
            numFmt(row.market_cap),
          ])}
        />
      </section>

      <p className="disclaimer">For educational use only. Not investment advice. Verify source data before acting.</p>
    </main>
  );
}

function DataTable({ headers, rows, empty }: { headers: string[]; rows: Array<Array<string | number>>; empty: string }) {
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            {headers.map((header) => (
              <th key={header}>{header}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 ? (
            <tr>
              <td className="empty" colSpan={headers.length}>
                {empty}
              </td>
            </tr>
          ) : (
            rows.map((row, rowIndex) => (
              <tr key={rowIndex}>
                {row.map((cellValue, cellIndex) => (
                  <td key={`${rowIndex}-${cellIndex}`}>{cellValue}</td>
                ))}
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}

export default App;

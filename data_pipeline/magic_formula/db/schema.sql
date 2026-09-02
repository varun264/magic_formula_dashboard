-- Centralized fundamentals schema — FMP-inspired, SQLite compatible.
-- Instruments: frozen NSE universe, slowly-changing profile separate.

CREATE TABLE IF NOT EXISTS instruments (
    symbol TEXT PRIMARY KEY,
    name TEXT,
    isin TEXT,
    sc_id TEXT,
    moneycontrol_slug TEXT,
    series TEXT,
    face_value REAL,
    isin_number TEXT,
    listing_date TEXT,
    created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    updated_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE TABLE IF NOT EXISTS company_profile (
    symbol TEXT NOT NULL REFERENCES instruments(symbol) ON DELETE CASCADE,
    sc_sector_id TEXT,
    sc_sector TEXT,
    industry TEXT,
    link_src TEXT,
    pdt_dis_nm TEXT,
    valid_from TEXT DEFAULT (date('now')),
    valid_to TEXT,
    PRIMARY KEY (symbol, valid_from)
);

CREATE TABLE IF NOT EXISTS daily_prices (
    symbol TEXT NOT NULL REFERENCES instruments(symbol) ON DELETE CASCADE,
    trade_date TEXT NOT NULL,
    close REAL,
    market_cap_cr REAL,
    pe_ttm REAL,
    pb REAL,
    dividend_yield REAL,
    volume INTEGER,
    source TEXT DEFAULT 'moneycontrol',
    source_hash TEXT,
    fetched_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    PRIMARY KEY (symbol, trade_date)
);

CREATE TABLE IF NOT EXISTS income_statement (
    symbol TEXT NOT NULL REFERENCES instruments(symbol) ON DELETE CASCADE,
    period_end TEXT NOT NULL,
    period TEXT NOT NULL CHECK (period IN ('Q1','Q2','Q3','Q4','FY','TTM')),
    consolidation_basis TEXT NOT NULL DEFAULT 'consolidated' CHECK (consolidation_basis IN ('consolidated','standalone')),
    calendar_year INTEGER,
    revenue_cr REAL,
    ebit_cr REAL,
    interest_cr REAL,
    net_profit_cr REAL,
    eps_basic REAL,
    eps_diluted REAL,
    cash_eps REAL,
    filing_date TEXT,
    source_hash TEXT,
    fetched_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    PRIMARY KEY (symbol, period_end, period, consolidation_basis)
);

CREATE TABLE IF NOT EXISTS balance_sheet (
    symbol TEXT NOT NULL REFERENCES instruments(symbol) ON DELETE CASCADE,
    period_end TEXT NOT NULL,
    period TEXT NOT NULL CHECK (period IN ('Q1','Q2','Q3','Q4','FY')),
    consolidation_basis TEXT NOT NULL DEFAULT 'consolidated' CHECK (consolidation_basis IN ('consolidated','standalone')),
    total_assets_cr REAL,
    total_debt_cr REAL,
    cash_and_equivalents_cr REAL,
    equity_cr REAL,
    book_value_per_share REAL,
    shares_outstanding INTEGER,
    source_hash TEXT,
    fetched_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    PRIMARY KEY (symbol, period_end, period, consolidation_basis)
);

CREATE TABLE IF NOT EXISTS ratios (
    symbol TEXT NOT NULL REFERENCES instruments(symbol) ON DELETE CASCADE,
    period_end TEXT NOT NULL,
    period TEXT NOT NULL CHECK (period IN ('Q1','Q2','Q3','Q4','FY','TTM')),
    consolidation_basis TEXT NOT NULL DEFAULT 'consolidated',
    roe_pct REAL,
    roce_pct REAL,
    roa_pct REAL,
    debt_equity REAL,
    current_ratio REAL,
    quick_ratio REAL,
    interest_coverage REAL,
    asset_turnover REAL,
    dividend_yield REAL,
    payout_ratio REAL,
    retention_ratio REAL,
    pb REAL,
    pe REAL,
    source_hash TEXT,
    fetched_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    PRIMARY KEY (symbol, period_end, period, consolidation_basis)
);

CREATE TABLE IF NOT EXISTS enterprise_value (
    symbol TEXT NOT NULL REFERENCES instruments(symbol) ON DELETE CASCADE,
    trade_date TEXT NOT NULL,
    enterprise_value_cr REAL,
    market_cap_cr REAL,
    computed_method TEXT DEFAULT 'proxy',
    fetched_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    PRIMARY KEY (symbol, trade_date),
    FOREIGN KEY (symbol, trade_date) REFERENCES daily_prices(symbol, trade_date) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS earnings_calendar (
    symbol TEXT NOT NULL REFERENCES instruments(symbol) ON DELETE CASCADE,
    event_date TEXT NOT NULL,
    source TEXT NOT NULL CHECK (source IN ('NSE','BSE','MC','MANUAL')),
    source_url TEXT,
    result_type TEXT DEFAULT 'quarterly' CHECK (result_type IN ('quarterly','annual','unknown')),
    confidence REAL DEFAULT 1.0,
    discovered_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    status TEXT DEFAULT 'pending' CHECK (status IN ('pending','fetched','failed','skipped')),
    PRIMARY KEY (symbol, event_date, source)
);

CREATE TABLE IF NOT EXISTS scrape_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    table_name TEXT NOT NULL,
    fetched_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    http_status INTEGER,
    source_hash TEXT,
    latency_ms INTEGER,
    success INTEGER DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_daily_prices_trade_date ON daily_prices(trade_date);
CREATE INDEX IF NOT EXISTS idx_income_symbol_period ON income_statement(symbol, period_end);
CREATE INDEX IF NOT EXISTS idx_earnings_event_date ON earnings_calendar(event_date, status);
CREATE INDEX IF NOT EXISTS idx_scrape_log_symbol_table ON scrape_log(symbol, table_name, fetched_at);

-- View: latest fundamentals per symbol (for ranking)
CREATE VIEW IF NOT EXISTS v_latest_fundamentals AS
SELECT
    i.symbol,
    i.name,
    i.sc_id,
    cp.sc_sector,
    cp.sc_sector_id,
    inc.ebit_cr,
    inc.revenue_cr,
    inc.net_profit_cr,
    inc.interest_cr,
    bs.book_value_per_share,
    r.roce_pct,
    r.roe_pct,
    inc.period_end AS fundamentals_date
FROM instruments i
LEFT JOIN company_profile cp ON cp.symbol = i.symbol AND cp.valid_to IS NULL
LEFT JOIN income_statement inc ON inc.symbol = i.symbol AND inc.consolidation_basis='consolidated' AND inc.period='FY'
    AND inc.period_end = (SELECT MAX(period_end) FROM income_statement WHERE symbol=i.symbol AND period='FY' AND consolidation_basis='consolidated')
LEFT JOIN balance_sheet bs ON bs.symbol = i.symbol AND bs.period_end = inc.period_end AND bs.consolidation_basis='consolidated'
LEFT JOIN ratios r ON r.symbol = i.symbol AND r.period_end = inc.period_end AND r.consolidation_basis='consolidated';

-- View: magic input (daily + latest fundamentals) for ranking
CREATE VIEW IF NOT EXISTS v_magic_input AS
SELECT
    lf.symbol,
    lf.name,
    lf.sc_sector,
    lf.ebit_cr,
    lf.book_value_per_share,
    lf.roce_pct,
    dp.close AS previous_close,
    dp.market_cap_cr,
    dp.trade_date
FROM v_latest_fundamentals lf
JOIN daily_prices dp ON dp.symbol = lf.symbol
WHERE dp.trade_date = (SELECT MAX(trade_date) FROM daily_prices WHERE symbol = lf.symbol)
  AND lf.ebit_cr IS NOT NULL
  AND dp.close IS NOT NULL
  AND dp.market_cap_cr IS NOT NULL;

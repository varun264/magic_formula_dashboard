export const config = { runtime: "edge" };

const CACHE_TTL_MS = 5 * 60_000;
const REQUEST_TIMEOUT_MS = 8_000;

type WebContext = {
  symbol?: string;
  price: string | null;
  change: string | null;
  changePct: string | null;
  trailingPE: string | null;
  forwardPE: string | null;
  eps: string | null;
  bookValue: string | null;
  priceToBook: string | null;
  dividendYield: string | null;
  headlines: Array<{ title: string; source: string }>;
};

const cache = new Map<string, { value: WebContext; expires: number }>();

function corsHeaders(req: Request): Record<string, string> {
  const origin = req.headers.get("origin") ?? "";
  const allowed = [
    "https://mf-dashboard-three.vercel.app",
    "https://varun264.github.io",
    "http://localhost:5173",
    "http://localhost:4173",
    "http://127.0.0.1:5173",
  ];
  const allowOrigin = allowed.find((a) => origin === a || origin.startsWith(a)) ?? "";
  return {
    "Access-Control-Allow-Origin": allowOrigin,
    "Access-Control-Allow-Methods": "GET, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
    Vary: "Origin",
  };
}

async function fetchWithTimeout(url: string): Promise<Response> {
  return fetch(url, {
    headers: { "User-Agent": "Mozilla/5.0" },
    signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
  });
}

function extractHeadlines(newsJson: unknown): Array<{ title: string; source: string }> {
  const candidates: unknown[] = [
    newsJson,
    (newsJson as Record<string, unknown>)?.finance,
    ((newsJson as Record<string, unknown>)?.data as Record<string, unknown>)?.items,
  ];

  for (const candidate of candidates) {
    let list: unknown = candidate;
    if (list && typeof list === "object" && !Array.isArray(list)) {
      const keys = ["news", "items", "results"];
      list = keys.map((k) => (candidate as Record<string, unknown>)[k]).find((v) => Array.isArray(v));
    }
    if (Array.isArray(list)) {
      return (list as Array<{ title?: string; publisher?: string; source?: string }>)
        .filter((n) => typeof n?.title === "string" && n.title)
        .slice(0, 5)
        .map((n) => ({ title: n.title!, source: n.publisher ?? n.source ?? "Yahoo Finance" }));
    }
  }
  return [];
}

async function buildContext(symbol: string): Promise<WebContext> {
  const yahooSymbol = `${symbol}.NS`;

  const [chartRes, quoteRes, newsRes] = await Promise.all([
    fetchWithTimeout(`https://query1.finance.yahoo.com/v8/finance/chart/${yahooSymbol}?range=5d&interval=1d`),
    fetchWithTimeout(`https://query2.finance.yahoo.com/v10/finance/quoteSummary/${yahooSymbol}?modules=summaryDetail,financialData,defaultKeyStatistics`),
    fetchWithTimeout(`https://query1.finance.yahoo.com/v8/finance/news/${yahooSymbol}`),
  ]);

  const empty: WebContext = {
    price: null,
    change: null,
    changePct: null,
    trailingPE: null,
    forwardPE: null,
    eps: null,
    bookValue: null,
    priceToBook: null,
    dividendYield: null,
    headlines: [],
  };

  if (chartRes.ok) {
    try {
      const chartJson: { chart?: { result?: Array<{ meta?: Record<string, unknown> }> } } = await chartRes.json();
      const m = chartJson?.chart?.result?.[0]?.meta;
      if (m) {
        const mp = m.regularMarketPrice as number | undefined;
        const prev = m.chartPreviousClose as number | undefined;
        if (mp != null) empty.price = mp.toFixed(2);
        if (mp != null && prev != null) {
          const diff = mp - prev;
          empty.change = diff.toFixed(2);
          empty.changePct = ((diff / prev) * 100).toFixed(2);
        }
      }
    } catch { /* keep defaults */ }
  }

  if (quoteRes.ok) {
    try {
      const qj: { quoteSummary?: { result?: Array<Record<string, unknown>> } } = await quoteRes.json();
      const q = qj?.quoteSummary?.result?.[0];
      if (q) {
        const g = (v: unknown, path: string): string | null => {
          let cur: unknown = v;
          for (const k of path.split(".")) {
            if (cur && typeof cur === "object") cur = (cur as Record<string, unknown>)[k];
            else return null;
          }
          if (cur && typeof cur === "object") {
            const raw = (cur as Record<string, unknown>).raw as number | undefined;
            return raw != null ? raw.toFixed(2) : null;
          }
          return null;
        };
        empty.trailingPE = g(q, "summaryDetail.trailingPE");
        empty.forwardPE = g(q, "summaryDetail.forwardPE");
        empty.eps = g(q, "defaultKeyStatistics.earningsPerShare");
        empty.bookValue = g(q, "defaultKeyStatistics.bookValue");
        empty.priceToBook = g(q, "defaultKeyStatistics.priceToBook");
        empty.dividendYield = g(q, "summaryDetail.dividendYield");
      }
    } catch { /* keep defaults */ }
  }

  if (newsRes.ok) {
    try {
      empty.headlines = extractHeadlines(await newsRes.json());
    } catch { /* keep defaults */ }
  }

  return empty;
}

export default async function handler(req: Request): Promise<Response> {
  const headers = { "Content-Type": "application/json", ...corsHeaders(req) };

  if (req.method === "OPTIONS") return new Response(null, { status: 204, headers });

  const url = new URL(req.url);
  const pdt = url.searchParams.get("pdt");
  if (!pdt) return Response.json({ error: "Missing pdt param" }, { status: 400, headers });

  const symMatch = pdt.match(/, ([A-Z0-9]+),/);
  if (!symMatch) return Response.json({ error: "Could not parse symbol" }, { status: 400, headers });
  const symbol = symMatch[1];

  const cached = cache.get(symbol);
  if (cached && Date.now() < cached.expires) {
    return Response.json(cached.value, { headers });
  }

  try {
    const value = await buildContext(symbol);
    cache.set(symbol, { value, expires: Date.now() + CACHE_TTL_MS });
    if (cache.size > 200) {
      const oldest = cache.keys().next().value;
      if (oldest) cache.delete(oldest);
    }
    return Response.json(value, { headers });
  } catch {
    return Response.json(
      { symbol, price: null, change: null, changePct: null, trailingPE: null, forwardPE: null, eps: null, bookValue: null, priceToBook: null, dividendYield: null, headlines: [] },
      { status: 200, headers },
    );
  }
}

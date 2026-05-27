export default async function handler(req: Request): Promise<Response> {
  const url = new URL(req.url);
  const pdt = url.searchParams.get("pdt");
  if (!pdt) return Response.json({ error: "Missing pdt param" }, { status: 400 });

  const symMatch = pdt.match(/, ([A-Z0-9]+),/);
  if (!symMatch) return Response.json({ error: "Could not parse symbol" }, { status: 400 });
  const symbol = symMatch[1];
  const yahooSymbol = `${symbol}.NS`;

  try {
    const [chartRes, quoteRes, newsRes] = await Promise.all([
      fetch(`https://query1.finance.yahoo.com/v8/finance/chart/${yahooSymbol}?range=5d&interval=1d`, {
        headers: { "User-Agent": "Mozilla/5.0" },
      }),
      fetch(`https://query2.finance.yahoo.com/v10/finance/quoteSummary/${yahooSymbol}?modules=summaryDetail,financialData,defaultKeyStatistics`, {
        headers: { "User-Agent": "Mozilla/5.0" },
      }),
      fetch(`https://query1.finance.yahoo.com/v8/finance/news/${yahooSymbol}`, {
        headers: { "User-Agent": "Mozilla/5.0" },
      }),
    ]);

    let price: string | null = null;
    let change: string | null = null;
    let changePct: string | null = null;
    let trailingPE: string | null = null;
    let forwardPE: string | null = null;
    let eps: string | null = null;
    let bookValue: string | null = null;
    let priceToBook: string | null = null;
    let dividendYield: string | null = null;

    if (chartRes.ok) {
      const chartJson: { chart?: { result?: Array<{ meta?: Record<string, unknown> }> } } = await chartRes.json();
      const m = chartJson?.chart?.result?.[0]?.meta;
      if (m) {
        const mp = m.regularMarketPrice as number | undefined;
        const prev = m.chartPreviousClose as number | undefined;
        if (mp != null) price = mp.toFixed(2);
        if (mp != null && prev != null) {
          const diff = mp - prev;
          change = diff.toFixed(2);
          changePct = ((diff / prev) * 100).toFixed(2);
        }
      }
    }

    if (quoteRes.ok) {
      const qj: { quoteSummary?: { result?: Array<Record<string, unknown>> } } = await quoteRes.json();
      const q = qj?.quoteSummary?.result?.[0];
      if (q) {
        const g = (v: unknown, path: string): string | null => {
          const keys = path.split(".");
          let cur: unknown = v;
          for (const k of keys) {
            if (cur && typeof cur === "object") cur = (cur as Record<string, unknown>)[k];
            else return null;
          }
          if (cur && typeof cur === "object") {
            const raw = (cur as Record<string, unknown>).raw as number | undefined;
            return raw != null ? raw.toFixed(2) : null;
          }
          return null;
        };
        trailingPE = g(q, "summaryDetail.trailingPE");
        forwardPE = g(q, "summaryDetail.forwardPE");
        eps = g(q, "defaultKeyStatistics.earningsPerShare");
        bookValue = g(q, "defaultKeyStatistics.bookValue");
        priceToBook = g(q, "defaultKeyStatistics.priceToBook");
        dividendYield = g(q, "summaryDetail.dividendYield");
      }
    }

    let headlines: Array<{ title: string; source: string }> = [];
    if (newsRes.ok) {
      const newsJson: Array<{ title: string; publisher?: string }> = await newsRes.json();
      headlines = (Array.isArray(newsJson) ? newsJson : []).slice(0, 5).map((n) => ({
        title: n.title,
        source: n.publisher ?? "Yahoo Finance",
      }));
    }

    return Response.json({ symbol, price, change, changePct, trailingPE, forwardPE, eps, bookValue, priceToBook, dividendYield, headlines });
  } catch {
    return Response.json({ symbol, price: null, change: null, changePct: null, trailingPE: null, forwardPE: null, eps: null, bookValue: null, priceToBook: null, dividendYield: null, headlines: [] });
  }
}

export const config = { runtime: "edge" };

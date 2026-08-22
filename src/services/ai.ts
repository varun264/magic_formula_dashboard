const CACHE_TTL = 86_400_000;
const MAX_CACHE = 100;

const API_BASE = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/+$/, "");

function makeCache() {
  const store = new Map<string, { value: string; expires: number }>();
  return {
    get(key: string): string | undefined {
      const entry = store.get(key);
      if (!entry) return undefined;
      if (Date.now() > entry.expires) { store.delete(key); return undefined; }
      return entry.value;
    },
    set(key: string, value: string) {
      if (store.size >= MAX_CACHE) {
        const oldest = store.keys().next().value!;
        store.delete(oldest);
      }
      store.set(key, { value, expires: Date.now() + CACHE_TTL });
    },
  };
}

const cache = makeCache();
let pending: Promise<string> | null = null;

async function callAI(prompt: string): Promise<string> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}/api/ai`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ prompt }),
    });
  } catch {
    return "AI analysis is unavailable (network error). Try again later.";
  }
  const data = await res.json().catch(() => null);
  if (!res.ok || !data?.text) {
    return typeof data?.error === "string" && data.error
      ? data.error
      : "AI analysis is unavailable right now. Try again in a few minutes.";
  }
  return data.text as string;
}

// ── Web context ─────────────────────────────────────────────────

type WebContext = {
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

async function fetchWebContext(pdtDisNm: string): Promise<WebContext | null> {
  try {
    const res = await fetch(`${API_BASE}/api/stock-context?pdt=${encodeURIComponent(pdtDisNm)}`);
    if (!res.ok) return null;
    return await res.json() as WebContext;
  } catch {
    return null;
  }
}

function extractPdtDisNm(details: Record<string, string | number | boolean | null> | undefined): string | null {
  if (!details) return null;
  const v = details["pdt_dis_nm"];
  return typeof v === "string" && v.length > 0 ? v : null;
}

// ── Build prompts ───────────────────────────────────────────────

function stockPrompt(stock: {
  name: string;
  sector: string | null;
  marketCapCr: number;
  previousClose: number;
  intrinsicValue: number;
  marginOfSafety: number;
  earningsYield: number;
  returnOnCapital: number;
  rank: number;
  eyRank: number;
  rocRank: number;
  details?: Record<string, string | number | boolean | null>;
  web?: WebContext | null;
}) {
  const lines: string[] = ["Analyze this Magic Formula stock pick:", ""];
  lines.push(`Company: ${stock.name}`);
  lines.push(`Sector: ${stock.sector ?? "N/A"}`);
  lines.push(`Magic Formula Rank: #${stock.rank}`);
  lines.push(`Earnings Yield Rank: #${stock.eyRank} | Return on Capital Rank: #${stock.rocRank}`);
  lines.push(`Earnings Yield: ${(stock.earningsYield * 100).toFixed(2)}%`);
  lines.push(`Return on Capital: ${(stock.returnOnCapital * 100).toFixed(2)}%`);
  lines.push(`Current Price: Rs ${stock.previousClose.toFixed(2)}`);
  lines.push("");

  // ── Valuation estimates ──
  const epv = stock.intrinsicValue;
  const epvMargin = stock.marginOfSafety;

  const d = stock.details;
  let graham: number | null = null;
  let epsVal: string | null = null;
  let bvVal: string | null = null;

  if (d) {
    const pick = (key: string) => {
      const v = d[key];
      if (v == null || v === "") return null;
      const s = String(v).replace(/,/g, "");
      const n = parseFloat(s);
      return isNaN(n) ? null : n;
    };

    const epsNum = pick("TTM EPS");
    const bvNum = pick("Book Value [ExclRevalReserve]/Share (Rs.)") ?? pick("Book Value [InclRevalReserve]/Share (Rs.)");
    epsVal = epsNum != null ? epsNum.toFixed(2) : null;
    bvVal = bvNum != null ? bvNum.toFixed(2) : null;

    // Graham Number = sqrt(22.5 × EPS × BVPS)
    if (epsNum != null && bvNum != null && epsNum > 0 && bvNum > 0) {
      graham = Math.sqrt(22.5 * epsNum * bvNum);
    }

    const pe = pick("TTM PE");
    const pb = pick("Price/BV (X)") ?? pick("Price To Book Value (X)");
    const roe = pick("Return on Networth/Equity (%)") ?? pick("Return On Equity/Networth (%)");
    const de = pick("Total Debt/Equity (X)");
    const divPayout = pick("Dividend Payout Ratio (NP) (%)");
    const roce = pick("Return on Capital Employed (%)");
    const evEbitda = pick("EV/EBITDA (X)");
    const currentRatio = pick("Current Ratio (X)");
    const faceValue = pick("Face Value");

    const ratios: string[] = [];
    if (pe) ratios.push(`P/E: ${pe.toFixed(2)}`);
    if (pb) ratios.push(`P/B: ${pb.toFixed(2)}`);
    if (epsVal) ratios.push(`TTM EPS: Rs ${epsVal}`);
    if (roe) ratios.push(`ROE: ${roe.toFixed(2)}%`);
    if (roce) ratios.push(`ROCE: ${roce.toFixed(2)}%`);
    if (de) ratios.push(`Debt/Equity: ${de.toFixed(2)}`);
    if (evEbitda) ratios.push(`EV/EBITDA: ${evEbitda}`);
    if (currentRatio) ratios.push(`Current Ratio: ${currentRatio}`);
    if (bvVal) ratios.push(`Book Value: Rs ${bvVal}`);
    if (divPayout) ratios.push(`Div Payout: ${divPayout}%`);
    if (faceValue) ratios.push(`Face Value: Rs ${faceValue}`);

    if (ratios.length > 0) {
      lines.push("Key Financial Ratios:");
      lines.push(ratios.join(" | "));
      lines.push("");
    }
  }

  // Valuation comparison block
  lines.push("Valuation Estimates:");
  lines.push(`EPV (Earnings Power Value): Rs ${epv.toFixed(2)} (margin: ${(epvMargin * 100).toFixed(1)}%)`);
  if (graham != null) {
    const grahamMargin = (graham / stock.previousClose) - 1;
    lines.push(`Graham Number: Rs ${graham.toFixed(2)} (margin: ${(grahamMargin * 100).toFixed(1)}%)`);
  }
  lines.push(`Current Price: Rs ${stock.previousClose.toFixed(2)}`);

  if (stock.web) {
    const w = stock.web;
    if (w.price) {
      lines.push(`Live Price: Rs ${w.price} (${w.changePct ? (Number(w.changePct) >= 0 ? "+" : "") + w.changePct + "%" : "N/A"})`);
    }
    const yhPE: string[] = [];
    if (w.trailingPE) yhPE.push(`Trailing P/E: ${w.trailingPE}`);
    if (w.forwardPE) yhPE.push(`Forward P/E: ${w.forwardPE}`);
    if (w.eps) yhPE.push(`EPS: Rs ${w.eps}`);
    if (w.bookValue) yhPE.push(`Book Value: Rs ${w.bookValue}`);
    if (w.priceToBook) yhPE.push(`P/B: ${w.priceToBook}`);
    if (w.dividendYield) yhPE.push(`Div Yield: ${(Number(w.dividendYield) * 100).toFixed(2)}%`);
    if (yhPE.length > 0) {
      lines.push("Yahoo Finance Data:");
      lines.push(yhPE.join(" | "));
    }
  }
  lines.push("");

  lines.push("Return your analysis in this exact format (use the headings exactly as shown):",
    "",
    "VERDICT: BUY / SELL / HOLD",
    "",
    "REASONS:",
    "- <reason 1>",
    "- <reason 2>",
    "",
    "RISKS:",
    "- <risk 1>",
    "- <risk 2>",
    "",
    "OUTLOOK:",
    "<2-3 sentence outlook for the next 12 months>",
    "",
    "Be direct and data-driven. Keep reasons and risks to 2-3 bullet points each.",
    "Use plain '-' hyphens for bullets and no markdown formatting.");

  return lines.join("\n");
}

function portfolioPrompt(recommendations: Array<{
  name: string; sector: string | null;
  earningsYield: number; returnOnCapital: number; marginOfSafety: number;
}>) {
  const top5 = recommendations.slice(0, 5);
  const lines = top5.map((r, i) =>
    `${i + 1}. ${r.name} (${r.sector ?? "N/A"}) - EY: ${(r.earningsYield * 100).toFixed(1)}%, ROC: ${(r.returnOnCapital * 100).toFixed(1)}%, Margin: ${(r.marginOfSafety * 100).toFixed(1)}%`
  ).join("\n");
  return `These are the top Magic Formula stock picks this month:

${lines}

Give a 2-sentence summary of what stands out about this portfolio. Mention sector concentration or diversification if relevant. Keep it under 80 words.`;
}

// ── Exported API ────────────────────────────────────────────────

export async function analyzeStock(stock: {
  name: string;
  sector: string | null;
  marketCapCr: number;
  previousClose: number;
  intrinsicValue: number;
  marginOfSafety: number;
  earningsYield: number;
  returnOnCapital: number;
  rank: number;
  eyRank: number;
  rocRank: number;
  details?: Record<string, string | number | boolean | null>;
}): Promise<string> {
  const cacheKey = stock.name;
  const cached = cache.get(cacheKey);
  if (cached) return cached;

  while (pending) {
    await pending;
    const recheck = cache.get(cacheKey);
    if (recheck) return recheck;
  }

  const pdt = extractPdtDisNm(stock.details);
  const web = pdt ? await fetchWebContext(pdt) : null;

  const prompt = stockPrompt({ ...stock, web });

  pending = callAI(prompt).then((text) => {
    pending = null;
    if (text && !text.includes("auth error") && !text.includes("unavailable") && !text.includes("rate-limited") && !text.includes("blocked")) {
      cache.set(cacheKey, text);
    }
    return text;
  });

  return pending;
}

export type AnalysisResult = {
  verdict: string;
  reasons: string[];
  risks: string[];
  outlook: string;
};

export function parseAnalysis(text: string): AnalysisResult | null {
  if (!text || text.includes("auth error") || text.includes("unavailable") || text.includes("rate-limited") || text.includes("blocked")) return null;

  const normalized = text.replace(/\*\*/g, "").replace(/\r\n?/g, "\n");

  const isBullet = (line: string) => /^\s*(?:[-*•·▪◦–—]|\d+[.)])\s+/.test(line);
  const bulletText = (line: string) => line.replace(/^\s*(?:[-*•·▪◦–—]|\d+[.)])\s+/, "").trim();

  const extractBullets = (section: string): string[] => {
    const lines = section.split("\n").map((l) => l.trim()).filter(Boolean);
    const items = lines.filter(isBullet).map(bulletText);
    if (items.length > 0) return items;

    // Fallback: model skipped bullets entirely; use plain lines, skipping headings.
    return lines
      .filter((l) => !/^(VERDICT|REASONS?|RISKS?|OUTLOOK)\b/i.test(l))
      .slice(0, 5);
  };

  const verdictMatch = normalized.match(/VERDICT:\s*\**\s*(BUY|SELL|HOLD)/i);
  const reasonsMatch = normalized.match(/REASONS?:\s*([\s\S]*?)(?=\n\s*(?:RISKS?|$))/i);
  const risksMatch = normalized.match(/RISKS?:\s*([\s\S]*?)(?=\n\s*(?:OUTLOOK|$))/i);
  const outlookMatch = normalized.match(/OUTLOOK:\s*([\s\S]*?)$/i);

  if (!verdictMatch) return null;

  return {
    verdict: verdictMatch[1].toUpperCase(),
    reasons: reasonsMatch ? extractBullets(reasonsMatch[1]) : [],
    risks: risksMatch ? extractBullets(risksMatch[1]) : [],
    outlook: outlookMatch ? outlookMatch[1].trim() : "",
  };
}

export async function analyzePortfolio(recommendations: Array<{
  name: string; sector: string | null;
  earningsYield: number; returnOnCapital: number; marginOfSafety: number;
}>): Promise<string> {
  if (recommendations.length === 0) return "";
  return callAI(portfolioPrompt(recommendations));
}

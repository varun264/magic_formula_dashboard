import { GoogleGenerativeAI } from "@google/generative-ai";

const CACHE_TTL = 86_400_000;
const MAX_CACHE = 100;

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

function sleep(ms: number) {
  return new Promise((r) => setTimeout(r, ms));
}

function isRateLimit(msg: string): boolean {
  const signals = [
    "429", "rate", "quota", "RATE_LIMIT", "RESOURCE_EXHAUSTED",
    "Too many requests", "503", "overloaded", "try again later",
    "limit reached", "capacity",
  ];
  return signals.some((s) => msg.toLowerCase().includes(s.toLowerCase()));
}

function isAuthError(msg: string): boolean {
  return msg.includes("API_KEY_INVALID") || msg.includes("API key not valid") ||
    msg.includes("401") || msg.includes("unauthorized") || msg.includes("forbidden") ||
    msg.includes("403");
}

// ── Gemini ──────────────────────────────────────────────────────

function geminiInit() {
  const key = import.meta.env.VITE_GOOGLE_API_KEY;
  if (!key) return null;
  const genAI = new GoogleGenerativeAI(key);
  return genAI.getGenerativeModel({ model: "gemini-2.0-flash" });
}

async function tryGemini(prompt: string): Promise<string> {
  const model = geminiInit();
  if (!model) throw new Error("no_key");
  for (let attempt = 0; ; attempt++) {
    try {
      const result = await model.generateContent(prompt);
      return result.response.text();
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      if (msg.toLowerCase().includes("safety") || msg.toLowerCase().includes("blocked")) {
        throw new Error("safety");
      }
      if (isRateLimit(msg) && attempt < 2) {
        await sleep(2000 * 2 ** attempt + Math.random() * 1000);
        continue;
      }
      if (isAuthError(msg)) throw new Error("auth:gemini");
      if (isRateLimit(msg)) throw new Error("rate:gemini");
      throw new Error("error:gemini");
    }
  }
}

// ── Groq ─────────────────────────────────────────────────────────

async function tryGroq(prompt: string): Promise<string> {
  const key = import.meta.env.VITE_GROQ_API_KEY;
  if (!key) throw new Error("no_key");

  for (let attempt = 0; ; attempt++) {
    try {
      const res = await fetch("https://api.groq.com/openai/v1/chat/completions", {
        method: "POST",
        headers: { Authorization: `Bearer ${key}`, "Content-Type": "application/json" },
        body: JSON.stringify({
          model: "llama-3.3-70b-versatile",
          messages: [
            { role: "system", content: "You are a concise value investing analyst. Respond in plain text without markdown." },
            { role: "user", content: prompt },
          ],
          max_tokens: 600,
          temperature: 0.3,
        }),
      });
      if (!res.ok) {
        if (res.status === 429 || res.status === 503) throw new Error("rate:groq");
        if (res.status === 401 || res.status === 403) throw new Error("auth:groq");
        throw new Error(`error:groq (${res.status})`);
      }
      const data = await res.json();
      return data.choices[0].message.content;
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      if (msg.startsWith("rate") && attempt < 2) {
        await sleep(3000 * 2 ** attempt + Math.random() * 1000);
        continue;
      }
      throw err;
    }
  }
}

// ── Hugging Face ─────────────────────────────────────────────────

async function tryHuggingFace(prompt: string): Promise<string> {
  const key = import.meta.env.VITE_HUGGINGFACE_API_KEY;
  if (!key) throw new Error("no_key");

  const body = JSON.stringify({
    inputs: `<|system|>\nYou are a concise value investing analyst. Respond in plain text.\n<|user|>\n${prompt}\n<|assistant|>\n`,
    parameters: { max_new_tokens: 600, temperature: 0.3, return_full_text: false },
  });

  for (let attempt = 0; ; attempt++) {
    try {
      const res = await fetch(
        "https://api-inference.huggingface.co/models/mistralai/Mistral-7B-Instruct-v0.3",
        {
          method: "POST",
          headers: { Authorization: `Bearer ${key}`, "Content-Type": "application/json" },
          body,
        }
      );
      if (!res.ok) {
        if (res.status === 429 || res.status === 503) throw new Error("rate:huggingface");
        if (res.status === 401 || res.status === 403) throw new Error("auth:huggingface");
        throw new Error(`error:huggingface (${res.status})`);
      }
      if (res.headers.get("content-type")?.includes("text")) {
        if (attempt < 2) {
          await sleep(5000 * (attempt + 1));
          continue;
        }
        throw new Error("error:huggingface (model loading)");
      }
      const data = await res.json();
      return Array.isArray(data) ? (data[0]?.generated_text ?? "") : "";
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      if (msg.startsWith("rate") && attempt < 2) {
        await sleep(5000 * 2 ** attempt + Math.random() * 2000);
        continue;
      }
      throw err;
    }
  }
}

// ── Fallback chain ──────────────────────────────────────────────

async function generateWithFallback(prompt: string): Promise<string> {
  const trials: Array<{ label: string; fn: (p: string) => Promise<string> }> = [
    { label: "gemini", fn: tryGemini },
    { label: "groq", fn: tryGroq },
    { label: "huggingface", fn: tryHuggingFace },
  ];

  for (const { label, fn } of trials) {
    try {
      return await fn(prompt);
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      if (msg.startsWith("auth:")) return `${label} auth error – check VITE_${label.toUpperCase()}_API_KEY`;
      if (msg.startsWith("error:") || msg.startsWith("rate:")) continue;
      if (msg === "no_key" || msg === "safety") return msg === "no_key" ? `AI analysis unavailable (no ${label} key).` : "Analysis blocked by content safety filters.";
    }
  }
  return "All AI providers are currently rate-limited. Try again in a few minutes.";
}

// ── Web context ─────────────────────────────────────────────────

type WebContext = {
  price: string | null;
  change: string | null;
  changePct: string | null;
  headlines: Array<{ title: string; source: string }>;
};

async function fetchWebContext(pdtDisNm: string): Promise<WebContext | null> {
  try {
    const res = await fetch(`/api/stock-context?pdt=${encodeURIComponent(pdtDisNm)}`);
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
  lines.push(`Market Cap: Rs ${stock.marketCapCr.toFixed(0)} Cr`);
  lines.push(`Current Price: Rs ${stock.previousClose.toFixed(2)}`);
  lines.push(`Intrinsic Value (EPV): Rs ${stock.intrinsicValue.toFixed(2)}`);
  lines.push(`Margin of Safety: ${(stock.marginOfSafety * 100).toFixed(1)}%`);
  lines.push("");

  const d = stock.details;
  if (d) {
    const pick = (key: string) => {
      const v = d[key];
      return v != null && v !== "" ? String(v) : null;
    };

    const pe = pick("TTM PE");
    const eps = pick("TTM EPS");
    const pb = pick("Price/BV (X)") ?? pick("Price To Book Value (X)");
    const roe = pick("Return on Networth/Equity (%)") ?? pick("Return On Equity/Networth (%)");
    const de = pick("Total Debt/Equity (X)");
    const divPayout = pick("Dividend Payout Ratio (NP) (%)");
    const bv = pick("Book Value [ExclRevalReserve]/Share (Rs.)") ?? pick("Book Value [InclRevalReserve]/Share (Rs.)");
    const roce = pick("Return on Capital Employed (%)");
    const evEbitda = pick("EV/EBITDA (X)");
    const currentRatio = pick("Current Ratio (X)");
    const faceValue = pick("Face Value");

    const ratios: string[] = [];
    if (pe) ratios.push(`P/E: ${pe}`);
    if (pb) ratios.push(`P/B: ${pb}`);
    if (eps) ratios.push(`TTM EPS: Rs ${eps}`);
    if (roe) ratios.push(`ROE: ${roe}%`);
    if (roce) ratios.push(`ROCE: ${roce}%`);
    if (de) ratios.push(`Debt/Equity: ${de}`);
    if (evEbitda) ratios.push(`EV/EBITDA: ${evEbitda}`);
    if (currentRatio) ratios.push(`Current Ratio: ${currentRatio}`);
    if (bv) ratios.push(`Book Value: Rs ${bv}`);
    if (divPayout) ratios.push(`Div Payout: ${divPayout}%`);
    if (faceValue) ratios.push(`Face Value: Rs ${faceValue}`);

    if (ratios.length > 0) {
      lines.push("Key Financial Ratios:");
      lines.push(ratios.join(" | "));
      lines.push("");
    }
  }

  if (stock.web) {
    const w = stock.web;
    if (w.price) {
      lines.push(`Recent Price: Rs ${w.price} (${w.changePct ? (Number(w.changePct) >= 0 ? "+" : "") + w.changePct + "%" : "N/A"})`);
    }
    if (w.headlines.length > 0) {
      lines.push("Recent News:");
      w.headlines.forEach((h) => lines.push(`- ${h.title}`));
    }
    lines.push("");
  }

  lines.push("Based on all the data above, provide:",
    "1. A clear BUY / SELL / HOLD verdict for the next 12 months",
    "2. Key reasons supporting your verdict (quality, valuation, risks)",
    "3. What catalysts or risks could change the outlook",
    "Keep it under 150 words. Be direct and data-driven.");

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

  pending = generateWithFallback(prompt).then((text) => {
    pending = null;
    if (text && !text.includes("auth error") && !text.includes("unavailable") && !text.includes("rate-limited") && !text.includes("blocked")) {
      cache.set(cacheKey, text);
    }
    return text;
  });

  return pending;
}

export async function analyzePortfolio(recommendations: Array<{
  name: string; sector: string | null;
  earningsYield: number; returnOnCapital: number; marginOfSafety: number;
}>): Promise<string> {
  if (recommendations.length === 0) return "";
  return generateWithFallback(portfolioPrompt(recommendations));
}

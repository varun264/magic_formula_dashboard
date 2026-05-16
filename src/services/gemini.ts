import { GoogleGenerativeAI } from "@google/generative-ai";

const API_KEY = import.meta.env.VITE_GOOGLE_API_KEY;

let genAI: GoogleGenerativeAI | null = null;
let model: ReturnType<GoogleGenerativeAI["getGenerativeModel"]> | null = null;

function init() {
  if (!API_KEY) return null;
  if (!genAI) {
    genAI = new GoogleGenerativeAI(API_KEY);
    model = genAI.getGenerativeModel({ model: "gemini-2.0-flash" });
  }
  return model;
}

const CACHE_TTL = 86_400_000; // 24h
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

// concurrency guard: max 1 in-flight request
let pending: Promise<string> | null = null;
const QUEUE_MAX_RETRIES = 3;

function sleep(ms: number) {
  return new Promise((r) => setTimeout(r, ms));
}

async function generateWithRetry(prompt: string): Promise<string> {
  const m = init();
  if (!m) return "";

  for (let attempt = 0; ; attempt++) {
    try {
      const result = await m.generateContent(prompt);
      return result.response.text();
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      const isRateLimit =
        msg.includes("429") ||
        msg.includes("rate") ||
        msg.includes("quota") ||
        msg.includes("RATE_LIMIT") ||
        msg.includes("RESOURCE_EXHAUSTED") ||
        msg.includes("Too many requests") ||
        msg.includes("safety") ||
        msg.includes("blocked");

      if (!isRateLimit || attempt >= QUEUE_MAX_RETRIES) {
        if (msg.includes("API_KEY_INVALID") || msg.includes("API key not valid")) {
          return "Invalid API key. Check your VITE_GOOGLE_API_KEY.";
        }
        if ((msg.includes("SAFETY") || msg.includes("blocked")) && !msg.includes("429")) {
          return "Analysis was blocked by content safety filters.";
        }
        if (isRateLimit) {
          return "Rate limit reached. The free tier allows ~1,500 requests/day and ~30 requests/minute. Please wait before trying again.";
        }
        return "Analysis temporarily unavailable. Try again later.";
      }

      // exponential backoff with jitter: 2s, 4s, 8s
      const delay = Math.min(1000 * 2 ** (attempt + 1), 10_000) + Math.random() * 1000;
      await sleep(delay);
    }
  }
}

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
}): Promise<string> {
  const key = stock.name;
  const cached = cache.get(key);
  if (cached) return cached;

  while (pending) {
    await pending;
    const recheck = cache.get(key);
    if (recheck) return recheck;
  }

  const prompt = `You are a value investing analyst. Analyze this Magic Formula stock pick:

Company: ${stock.name}
Sector: ${stock.sector ?? "N/A"}
Magic Formula Rank: #${stock.rank}
Earnings Yield Rank: #${stock.eyRank}
Return on Capital Rank: #${stock.rocRank}
Earnings Yield: ${(stock.earningsYield * 100).toFixed(2)}%
Return on Capital: ${(stock.returnOnCapital * 100).toFixed(2)}%
Current Price: Rs ${stock.previousClose.toFixed(2)}
Intrinsic Value: Rs ${stock.intrinsicValue.toFixed(2)}
Margin of Safety: ${(stock.marginOfSafety * 100).toFixed(1)}%

Provide a concise 3-paragraph analysis covering:
1. Magic Formula positioning and what the ranks indicate
2. Valuation assessment (intrinsic value vs market price)
3. Key considerations for an investor

Keep it under 120 words total. Be direct and factual.`;

  pending = generateWithRetry(prompt).then((text) => {
    pending = null;
    if (text && !text.startsWith("Invalid") && !text.startsWith("Rate") && !text.startsWith("Analysis")) {
      cache.set(key, text);
    }
    return text;
  });

  return pending;
}

export async function analyzePortfolio(recommendations: Array<{
  name: string;
  sector: string | null;
  earningsYield: number;
  returnOnCapital: number;
  marginOfSafety: number;
}>): Promise<string> {
  const top5 = recommendations.slice(0, 5);
  if (top5.length === 0) return "";

  const lines = top5.map((r, i) =>
    `${i + 1}. ${r.name} (${r.sector ?? "N/A"}) - EY: ${(r.earningsYield * 100).toFixed(1)}%, ROC: ${(r.returnOnCapital * 100).toFixed(1)}%, Margin: ${(r.marginOfSafety * 100).toFixed(1)}%`
  ).join("\n");

  const prompt = `These are the top Magic Formula stock picks for this month:

${lines}

Give a 2-sentence summary of what stands out about this portfolio. Mention sector concentration or diversification if relevant. Keep it under 80 words.`;

  return generateWithRetry(prompt);
}

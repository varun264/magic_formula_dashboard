export const config = { runtime: "edge" };

const MAX_PROMPT_CHARS = 20_000;
const REQUEST_TIMEOUT_MS = 30_000;

const HF_MODELS = [
  "microsoft/Phi-3-mini-4k-instruct",
  "HuggingFaceH4/zephyr-7b-beta",
  "mistralai/Mistral-7B-Instruct-v0.3",
];

function env(name: string): string | undefined {
  const value = process.env[name];
  return value && value.trim() !== "" ? value.trim() : undefined;
}

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
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
    Vary: "Origin",
  };
}

function sleep(ms: number) {
  return new Promise((r) => setTimeout(r, ms));
}

function stripThinking(text: string): string {
  return text.replace(/<think>[\s\S]*?<\/think>\s*/gi, "").trim();
}

async function fetchJson(url: string, init: RequestInit): Promise<Response> {
  return fetch(url, { ...init, signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS) });
}

async function tryGemini(prompt: string): Promise<string> {
  const key = env("GOOGLE_API_KEY") ?? env("VITE_GOOGLE_API_KEY");
  if (!key) throw new Error("no_key");

  for (let attempt = 0; ; attempt++) {
    try {
      const res = await fetchJson(
        `https://generativelanguage.googleapis.com/v1beta/models/gemini-3.6-flash:generateContent?key=${key}`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            contents: [{ parts: [{ text: prompt }] }],
            generationConfig: { temperature: 0.3, maxOutputTokens: 600 },
          }),
        }
      );
      if (!res.ok) {
        if (res.status === 401 || res.status === 403) throw new Error("auth:gemini");
        if (res.status === 429 || res.status === 503) throw new Error("rate:gemini");
        throw new Error("error:gemini");
      }
      const data = await res.json();
      const text = data?.candidates?.[0]?.content?.parts?.map((p: { text?: string }) => p.text ?? "").join("") ?? "";
      if (!text) throw new Error("error:gemini");
      return stripThinking(text);
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      if (msg.startsWith("rate") && attempt < 2) {
        await sleep(2000 * 2 ** attempt + Math.random() * 1000);
        continue;
      }
      throw err;
    }
  }
}

async function tryGroq(prompt: string): Promise<string> {
  const key = env("GROQ_API_KEY") ?? env("VITE_GROQ_API_KEY");
  if (!key) throw new Error("no_key");

  for (let attempt = 0; ; attempt++) {
    try {
      const res = await fetchJson("https://api.groq.com/openai/v1/chat/completions", {
        method: "POST",
        headers: { Authorization: `Bearer ${key}`, "Content-Type": "application/json" },
        body: JSON.stringify({
          model: "qwen/qwen3.6-27b",
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
        throw new Error("error:groq");
      }
      const data = await res.json();
      const text = data?.choices?.[0]?.message?.content ?? "";
      if (!text) throw new Error("error:groq");
      return stripThinking(text);
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

async function tryHuggingFace(prompt: string): Promise<string> {
  const key = env("HUGGINGFACE_API_KEY") ?? env("VITE_HUGGINGFACE_API_KEY");
  if (!key) throw new Error("no_key");

  const hfCall = async (model: string): Promise<string> => {
    const res = await fetchJson(`https://api-inference.huggingface.co/models/${model}`, {
      method: "POST",
      headers: { Authorization: `Bearer ${key}`, "Content-Type": "application/json" },
      body: JSON.stringify({
        inputs: prompt,
        parameters: { max_new_tokens: 600, temperature: 0.3, return_full_text: false },
      }),
    });
    if (!res.ok) {
      const body = await res.text();
      if (body.includes("image") || body.includes("does not support")) throw new Error("skip");
      if (res.status === 429 || res.status === 503) throw new Error("rate:huggingface");
      if (res.status === 401 || res.status === 403) throw new Error("auth:huggingface");
      throw new Error("error:huggingface");
    }
    const ct = res.headers.get("content-type") ?? "";
    if (!ct.includes("json")) throw new Error("loading");
    const data = await res.json();
    if (data?.error) {
      if (String(data.error).includes("image")) throw new Error("skip");
      throw new Error("error:huggingface");
    }
    const text = Array.isArray(data) ? data[0]?.generated_text ?? "" : "";
    if (!text) throw new Error("error:huggingface");
    return stripThinking(text);
  };

  for (const model of HF_MODELS) {
    for (let attempt = 0; attempt < 3; attempt++) {
      try {
        return await hfCall(model);
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        if (msg === "skip") break;
        if (msg.startsWith("auth")) throw err;
        if ((msg === "loading" || msg.startsWith("rate")) && attempt < 2) {
          await sleep(5000 * (attempt + 1));
          continue;
        }
        break;
      }
    }
  }
  throw new Error("rate:huggingface");
}

async function generateWithFallback(prompt: string): Promise<string> {
  const trials: Array<{ label: string; fn: (p: string) => Promise<string> }> = [
    { label: "gemini", fn: tryGemini },
    { label: "groq", fn: tryGroq },
    { label: "huggingface", fn: tryHuggingFace },
  ];

  let lastError = "";
  let sawAuth = false;
  let sawSafety = false;

  for (const { label, fn } of trials) {
    try {
      return await fn(prompt);
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      lastError = `${label}: ${msg}`;
      if (msg.startsWith("auth:")) sawAuth = true;
      if (msg === "safety") sawSafety = true;
    }
  }

  if (sawSafety) throw Object.assign(new Error("safety"), { status: 422 });
  if (sawAuth) throw Object.assign(new Error(`auth error – check server API keys (${lastError})`), { status: 500 });
  throw Object.assign(new Error(lastError || "all providers failed"), { status: 502 });
}

export default async function handler(req: Request): Promise<Response> {
  const headers = { "Content-Type": "application/json", ...corsHeaders(req) };

  if (req.method === "OPTIONS") return new Response(null, { status: 204, headers });

  if (req.method !== "POST") {
    return Response.json({ error: "Method not allowed" }, { status: 405, headers });
  }

  let prompt = "";
  try {
    const body = await req.json();
    prompt = typeof body?.prompt === "string" ? body.prompt : "";
  } catch {
    return Response.json({ error: "Invalid JSON body" }, { status: 400, headers });
  }

  if (!prompt) return Response.json({ error: "Missing prompt" }, { status: 400, headers });
  if (prompt.length > MAX_PROMPT_CHARS) {
    return Response.json({ error: "Prompt too long" }, { status: 413, headers });
  }

  try {
    const text = await generateWithFallback(prompt);
    return Response.json({ text }, { headers });
  } catch (err) {
    const e = err as Error & { status?: number };
    const message =
      e.message === "safety"
        ? "Analysis blocked by content safety filters."
        : e.message.includes("auth")
          ? "AI provider auth error – check server API keys."
          : "All AI providers are currently unavailable or rate-limited. Try again in a few minutes.";
    return Response.json({ error: message }, { status: e.status ?? 502, headers });
  }
}

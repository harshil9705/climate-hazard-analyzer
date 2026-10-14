import type { AnyAnalysis, AnalysisRequest, GeocodeResult, Meta } from "./types";

const BASE = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/+$/, "");
// In dev the API runs on :8000 (Vite only proxies /api), so link the docs there directly.
export const API_DOCS_URL = `${BASE || "http://localhost:8000"}/docs`;

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
    public details: string[] = [],
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit, timeoutMs = 180_000): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, { ...init, signal: init?.signal ?? controller.signal });
  } catch (err) {
    if ((err as Error).name === "AbortError") throw new ApiError("The request timed out. Please try again.", 0);
    throw new ApiError("Cannot reach the analysis server. Is it running?", 0);
  } finally {
    clearTimeout(timer);
  }

  if (!res.ok) {
    let message = `Request failed (${res.status})`;
    let details: string[] = [];
    try {
      const body = await res.json();
      if (typeof body.detail === "string") message = body.detail;
      if (Array.isArray(body.errors)) {
        details = body.errors.map((e: { field: string; message: string }) =>
          e.field ? `${e.field}: ${e.message}` : e.message,
        );
      }
    } catch {
      /* non-JSON error body */
    }
    if (res.status === 429) {
      const wait = res.headers.get("Retry-After");
      message = `Too many requests. Please wait${wait ? ` ${wait}s` : ""} and try again.`;
    }
    throw new ApiError(message, res.status, details);
  }
  return res.json() as Promise<T>;
}

export const api = {
  meta: () => request<Meta>("/api/meta"),
  geocode: (q: string, signal?: AbortSignal) =>
    request<GeocodeResult[]>(`/api/geocode?q=${encodeURIComponent(q)}`, { signal }),
  createAnalysis: (body: AnalysisRequest) =>
    request<AnyAnalysis>("/api/analyses", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  getAnalysis: (id: string) => request<AnyAnalysis>(`/api/analyses/${encodeURIComponent(id)}`),
  exportUrl: (id: string, kind: "export.csv" | "report.pdf" | "plot.png") =>
    `${BASE}/api/analyses/${encodeURIComponent(id)}/${kind}`,
};

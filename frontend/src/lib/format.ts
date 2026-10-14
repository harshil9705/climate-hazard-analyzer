import type { Region, Significance, Trend } from "../api/types";

export function formatSigned(value: number, digits = 1): string {
  const fixed = value.toFixed(digits);
  return value > 0 ? `+${fixed}` : fixed;
}

export function formatP(p: number | undefined | null): string {
  if (p == null) return "n/a";
  return p < 0.001 ? "p < 0.001" : `p = ${p.toFixed(3)}`;
}

export const SIGNIFICANCE_LABEL: Record<Significance, string> = {
  significant: "Significant",
  weak: "Weak evidence",
  not_significant: "Not significant",
  insufficient_data: "Insufficient data",
};

export function trendSummary(trend: Trend, unit: string): string {
  if (trend.status === "constant") return "No variation";
  if (trend.status !== "ok" || trend.sens_slope_per_decade == null) return "Not enough data";
  return `${formatSigned(trend.sens_slope_per_decade, Math.abs(trend.sens_slope_per_decade) < 0.1 ? 3 : 2)} ${unit}/decade`;
}

export function describeRegion(r: Region): string {
  if (r.kind === "point") return `${r.lat.toFixed(3)}°, ${r.lon.toFixed(3)}°`;
  return `${r.south.toFixed(2)}…${r.north.toFixed(2)}°N, ${r.west.toFixed(2)}…${r.east.toFixed(2)}°E`;
}

/** Client-side mirror of the server's validation, for instant feedback. The server stays the authority. */
export function validateRequest(opts: {
  region: Region | null;
  start: number;
  end: number;
  minYear: number;
  maxYear: number;
  maxSpan?: number;
}): string | null {
  const { region, start, end, minYear, maxYear, maxSpan = 5 } = opts;
  if (!region) return "Choose a region: search a place, pick a preset or click the map.";
  if (!Number.isInteger(start) || !Number.isInteger(end)) return "Years must be whole numbers.";
  if (start < minYear || end > maxYear) return `Years must be between ${minYear} and ${maxYear}.`;
  if (end - start + 1 < 10) return "Choose a range of at least 10 years so a trend can be assessed.";
  if (region.kind === "bbox") {
    if (region.south >= region.north || region.west >= region.east) return "The box corners are invalid.";
    if (region.north - region.south > maxSpan || region.east - region.west > maxSpan)
      return `The box may span at most ${maxSpan}° on each side.`;
  }
  return null;
}

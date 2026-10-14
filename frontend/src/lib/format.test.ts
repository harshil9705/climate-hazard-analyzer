import { describe, expect, it } from "vitest";
import { formatP, formatSigned, trendSummary, validateRequest } from "./format";

describe("format helpers", () => {
  it("formats signed numbers", () => {
    expect(formatSigned(2.345)).toBe("+2.3");
    expect(formatSigned(-1.2, 2)).toBe("-1.20");
    expect(formatSigned(0)).toBe("0.0");
  });

  it("formats p-values", () => {
    expect(formatP(0.0001)).toBe("p < 0.001");
    expect(formatP(0.0412)).toBe("p = 0.041");
    expect(formatP(undefined)).toBe("n/a");
  });

  it("summarises trends with sensible precision", () => {
    expect(trendSummary({ n: 30, status: "ok", sens_slope_per_decade: 2.5, rolling_mean_10y: [] }, "days")).toBe(
      "+2.50 days/decade",
    );
    expect(trendSummary({ n: 30, status: "ok", sens_slope_per_decade: 0.012, rolling_mean_10y: [] }, "°C")).toBe(
      "+0.012 °C/decade",
    );
    expect(trendSummary({ n: 3, status: "insufficient_data", rolling_mean_10y: [] }, "days")).toBe("Not enough data");
  });
});

describe("validateRequest", () => {
  const base = { start: 1990, end: 2020, minYear: 1940, maxYear: 2025 };
  const point = { kind: "point" as const, lat: 1, lon: 2 };

  it("requires a region", () => {
    expect(validateRequest({ ...base, region: null })).toMatch(/Choose a region/);
  });
  it("requires at least 10 years", () => {
    expect(validateRequest({ ...base, region: point, start: 2015 })).toMatch(/at least 10 years/);
  });
  it("rejects out-of-range years", () => {
    expect(validateRequest({ ...base, region: point, start: 1900 })).toMatch(/between/);
  });
  it("rejects oversized boxes", () => {
    const box = { kind: "bbox" as const, south: 0, west: 0, north: 10, east: 1 };
    expect(validateRequest({ ...base, region: box })).toMatch(/at most 5/);
  });
  it("accepts a valid request", () => {
    expect(validateRequest({ ...base, region: point })).toBeNull();
  });
});

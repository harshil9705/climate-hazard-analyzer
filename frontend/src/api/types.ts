export type PointRegion = { kind: "point"; lat: number; lon: number; name?: string | null };
export type BBoxRegion = {
  kind: "bbox";
  south: number;
  west: number;
  north: number;
  east: number;
  name?: string | null;
};
export type Region = PointRegion | BBoxRegion;
export type HazardType = "heatwave" | "drought" | "rainfall";

export type ThresholdMethod = "fixed" | "calendar_day";

export interface HeatwaveParams {
  percentile: number;
  min_duration_days: number;
  threshold_method: ThresholdMethod;
  baseline_start: number;
  baseline_end: number;
}

export interface DroughtParams {
  dry_threshold_mm: number;
  min_duration_days: number;
}

export interface RainfallParams {
  percentile: number;
  wet_threshold_mm: number;
  min_duration_days: number;
  baseline_start: number;
  baseline_end: number;
}

export type AnyParams = HeatwaveParams | DroughtParams | RainfallParams;

export interface AnalysisRequest {
  region: Region;
  hazard: HazardType;
  start_year: number;
  end_year: number;
  params: AnyParams;
}

export type Preset = Region & { id: string; name: string };

export interface Meta {
  hazards: { id: string; label: string; default?: boolean }[];
  min_year: number;
  max_year: number;
  default_range: [number, number];
  default_params: HeatwaveParams;
  presets: Preset[];
}

export interface GeocodeResult {
  name: string;
  lat: number;
  lon: number;
  country?: string | null;
  admin1?: string | null;
  population?: number | null;
}

// Heatwave annual row
export interface AnnualRow {
  year: number;
  excluded: boolean;
  event_count: number | null;
  heatwave_days: number | null;
  longest_event_days: number | null;
  mean_heatwave_tmax_c: number | null;
  peak_tmax_c: number | null;
  cumulative_excess_cdays: number | null;
  exceedance_days: number | null;
  mean_annual_tmax_c: number | null;
  annual_max_tmax_c: number | null;
}

// Drought annual row
export interface DroughtAnnualRow {
  year: number;
  excluded: boolean;
  event_count: number | null;
  drought_days: number | null;
  max_dry_spell: number | null;
  cumulative_deficit_mm: number | null;
  mean_annual_precip_mm: number | null;
  total_annual_precip_mm: number | null;
  dry_days_total: number | null;
}

// Heavy rainfall annual row
export interface RainfallAnnualRow {
  year: number;
  excluded: boolean;
  event_count: number | null;
  heavy_days: number | null;
  max_event_days: number | null;
  total_heavy_precip_mm: number | null;
  rx1day_mm: number | null;
  rx5day_mm: number | null;
  total_annual_precip_mm: number | null;
  mean_annual_precip_mm: number | null;
}

export type Significance = "significant" | "weak" | "not_significant" | "insufficient_data";

export interface Trend {
  n: number;
  status: "ok" | "constant" | "insufficient_data";
  direction?: "increasing" | "decreasing" | "none";
  significance?: Significance;
  mann_kendall?: { s: number; z: number; p_value: number; tau: number };
  sens_slope_per_decade?: number;
  ols?: {
    slope_per_decade: number;
    slope_ci95_per_decade: [number, number];
    r_squared: number;
    p_value: number | null;
  };
  trend_line?: number[];
  rolling_mean_10y: (number | null)[];
}

export type TrendKey =
  | "heatwave_days"
  | "event_count"
  | "longest_event_days"
  | "cumulative_excess_cdays"
  | "mean_heatwave_tmax_c"
  | "mean_annual_tmax_c"
  | "exceedance_days";

export interface HeatwaveEvent {
  start: string;
  end: string;
  year: number;
  duration_days: number;
  peak_tmax_c: number;
  mean_tmax_c: number;
  mean_excess_c: number;
  cumulative_excess_cdays: number;
}

export interface DroughtEvent {
  start: string;
  end: string;
  year: number;
  duration_days: number;
  min_precip_mm: number;
  mean_precip_mm: number;
  cumulative_deficit_mm: number;
}

export interface RainfallEvent {
  start: string;
  end: string;
  year: number;
  duration_days: number;
  peak_precip_mm: number;
  mean_precip_mm: number;
  cumulative_precip_mm: number;
}

export interface PeriodComparison {
  metric: string;
  early: { start: number; end: number; mean: number };
  late: { start: number; end: number; mean: number };
  absolute_change: number;
  percent_change: number | null;
}

interface BaseAnalysis {
  id: string;
  request: AnalysisRequest;
  region_label: string;
  generated_at: string;
  algorithm_version: string;
  source: {
    provider: string;
    dataset: string;
    variable: string;
    units: string;
    grid_points: { lat: number; lon: number }[];
    fetched_years: [number, number];
  };
  climatology: {
    baseline_label: string;
    recent_label: string;
    baseline_mean: (number | null)[];
    recent_mean: (number | null)[];
    threshold?: number[];
  };
  insights: {
    headline: string;
    findings: { metric: string; text: string; significance?: Significance }[];
    period_comparison: PeriodComparison | null;
    caveats: string[];
  };
  data_quality: {
    total_days: number;
    missing_raw: number;
    implausible_removed: number;
    spikes_removed: number;
    interpolated: number;
    missing_after_cleaning: number;
    excluded_years: number[];
  };
  cache: { years_requested: number; years_from_cache: number; years_fetched: number; upstream_calls: number };
}

export interface Analysis extends BaseAnalysis {
  hazard: "heatwave";
  threshold: {
    method: ThresholdMethod;
    percentile: number;
    baseline: [number, number];
    value_c: number | null;
    label: string;
    min_duration_days: number;
  };
  annual: AnnualRow[];
  trends: Record<TrendKey, Trend>;
  events: HeatwaveEvent[];
  event_total: number;
}

export interface DroughtAnalysis extends BaseAnalysis {
  hazard: "drought";
  threshold: {
    dry_threshold_mm: number;
    min_duration_days: number;
    label: string;
  };
  annual: DroughtAnnualRow[];
  trends: Record<string, Trend>;
  events: DroughtEvent[];
  event_total: number;
}

export interface RainfallAnalysis extends BaseAnalysis {
  hazard: "rainfall";
  threshold: {
    percentile: number;
    wet_threshold_mm: number;
    value_mm: number;
    baseline: [number, number];
    min_duration_days: number;
    label: string;
  };
  annual: RainfallAnnualRow[];
  trends: Record<string, Trend>;
  events: RainfallEvent[];
  event_total: number;
}

export type AnyAnalysis = Analysis | DroughtAnalysis | RainfallAnalysis;

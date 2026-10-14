import type { ChartData, ChartOptions } from "chart.js";
import { Chart, Line } from "react-chartjs-2";
import type { Analysis, TrendKey } from "../api/types";
import { baseOptions, useChartColors } from "../lib/chartTheme";
import { SIGNIFICANCE_LABEL, formatP, trendSummary } from "../lib/format";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const MONTH_START_DOY = [1, 32, 60, 91, 121, 152, 182, 213, 244, 274, 305, 335];

/** Hero chart: annual heatwave days, 10-year rolling mean, Sen's slope trend. */
export function AnnualHeatwaveChart({ analysis }: { analysis: Analysis }) {
  const c = useChartColors();
  const years = analysis.annual.map((r) => String(r.year));
  const trend = analysis.trends.heatwave_days;

  const data: ChartData<"bar" | "line", (number | null)[], string> = {
    labels: years,
    datasets: [
      {
        type: "bar",
        label: "Heatwave days",
        data: analysis.annual.map((r) => r.heatwave_days),
        backgroundColor: c.heat,
        borderRadius: { topLeft: 4, topRight: 4 },
        borderSkipped: "bottom",
        maxBarThickness: 24,
        categoryPercentage: 0.85,
        barPercentage: 0.9,
        order: 3,
      },
      {
        type: "line",
        label: "10-year rolling mean",
        data: trend.rolling_mean_10y,
        borderColor: c.trend,
        backgroundColor: c.trend,
        borderWidth: 2,
        pointRadius: 0,
        pointHoverRadius: 5,
        tension: 0.3,
        spanGaps: true,
        order: 1,
      },
      ...(trend.trend_line
        ? [
            {
              type: "line" as const,
              label: "Trend (Sen's slope)",
              data: trend.trend_line,
              borderColor: c.reference,
              backgroundColor: c.reference,
              borderWidth: 2,
              borderDash: [6, 4],
              pointRadius: 0,
              pointHoverRadius: 0,
              order: 2,
            },
          ]
        : []),
    ],
  };

  const opts = baseOptions(c);
  const options: ChartOptions<"bar" | "line"> = {
    ...opts,
    plugins: {
      ...opts.plugins,
      tooltip: {
        ...opts.plugins.tooltip,
        callbacks: {
          label: (ctx) => {
            const v = ctx.parsed.y;
            if (v == null) return `${ctx.dataset.label}: excluded (data gaps)`;
            return `${ctx.dataset.label}: ${v.toFixed(ctx.datasetIndex === 0 ? 0 : 1)} days`;
          },
        },
      },
    },
    scales: { ...opts.scales, y: { ...opts.scales.y, title: { display: true, text: "days per year", color: c.textMuted } } },
  };

  return (
    <div className="chart chart-lg" role="img" aria-label={`Bar chart of annual heatwave days for ${analysis.region_label}`}>
      <Chart type="bar" data={data} options={options} />
    </div>
  );
}

const METRICS: { key: TrendKey; title: string; unit: string; zeroBased: boolean; digits: number }[] = [
  { key: "event_count", title: "Heatwave events per year", unit: "events", zeroBased: true, digits: 0 },
  { key: "longest_event_days", title: "Longest heatwave (days)", unit: "days", zeroBased: true, digits: 0 },
  { key: "cumulative_excess_cdays", title: "Cumulative excess heat (°C·days)", unit: "°C·days", zeroBased: true, digits: 1 },
  { key: "mean_annual_tmax_c", title: "Mean annual max temperature (°C)", unit: "°C", zeroBased: false, digits: 2 },
];

function MetricChart({ analysis, metric }: { analysis: Analysis; metric: (typeof METRICS)[number] }) {
  const c = useChartColors();
  const trend = analysis.trends[metric.key];
  const values = analysis.annual.map((r) => r[metric.key as keyof typeof r] as number | null);
  const opts = baseOptions(c);
  const data: ChartData<"line", (number | null)[], string> = {
    labels: analysis.annual.map((r) => String(r.year)),
    datasets: [
      {
        label: metric.title,
        data: values,
        borderColor: c.heat,
        backgroundColor: c.heatWash,
        fill: metric.zeroBased ? "origin" : false,
        borderWidth: 2,
        pointRadius: 0,
        pointHoverRadius: 5,
        pointHoverBorderColor: c.surface,
        pointHoverBorderWidth: 2,
        tension: 0.2,
        spanGaps: false,
      },
      ...(trend.trend_line
        ? [
            {
              label: "Trend",
              data: trend.trend_line,
              borderColor: c.reference,
              borderDash: [6, 4],
              borderWidth: 1.5,
              pointRadius: 0,
              pointHoverRadius: 0,
              fill: false,
            },
          ]
        : []),
    ],
  };
  const options: ChartOptions<"line"> = {
    ...opts,
    plugins: {
      ...opts.plugins,
      legend: { display: false },
      tooltip: {
        ...opts.plugins.tooltip,
        callbacks: {
          label: (ctx) =>
            ctx.parsed.y == null ? "excluded" : `${ctx.dataset.label}: ${ctx.parsed.y.toFixed(metric.digits)} ${metric.unit}`,
        },
      },
    },
    scales: { ...opts.scales, y: { ...opts.scales.y, beginAtZero: metric.zeroBased } },
  };
  const sig = trend.significance;
  return (
    <figure className="metric-card">
      <figcaption>
        <span className="metric-title">{metric.title}</span>
        <span className="metric-trend">
          {trendSummary(trend, metric.unit)}
          {sig && (
            <span className={`badge badge-${sig}`} title={formatP(trend.mann_kendall?.p_value)}>
              {SIGNIFICANCE_LABEL[sig]}
            </span>
          )}
        </span>
      </figcaption>
      <div className="chart chart-sm">
        <Line data={data} options={options} />
      </div>
    </figure>
  );
}

export function MetricGrid({ analysis }: { analysis: Analysis }) {
  return (
    <div className="metric-grid">
      {METRICS.map((m) => (
        <MetricChart key={m.key} analysis={analysis} metric={m} />
      ))}
    </div>
  );
}

/** Seasonal cycle: baseline vs recent decade mean Tmax, with the heatwave threshold. */
export function ClimatologyChart({ analysis }: { analysis: Analysis }) {
  const c = useChartColors();
  const cl = analysis.climatology;
  const labels = Array.from({ length: 365 }, (_, i) => {
    const m = MONTH_START_DOY.indexOf(i + 1);
    return m >= 0 ? MONTHS[m] : "";
  });
  const opts = baseOptions(c);
  const data: ChartData<"line", (number | null)[], string> = {
    labels,
    datasets: [
      {
        label: `Recent mean (${cl.recent_label})`,
        data: cl.recent_mean,
        borderColor: c.heat,
        borderWidth: 2,
        pointRadius: 0,
        pointHoverRadius: 4,
      },
      {
        label: `Baseline mean (${cl.baseline_label})`,
        data: cl.baseline_mean,
        borderColor: c.trend,
        borderWidth: 2,
        pointRadius: 0,
        pointHoverRadius: 4,
      },
      {
        label: `Heatwave threshold (${analysis.threshold.percentile}th pct)`,
        data: cl.threshold ?? [],
        borderColor: c.reference,
        borderDash: [6, 4],
        borderWidth: 1.5,
        pointRadius: 0,
        pointHoverRadius: 0,
      },
    ],
  };
  const options: ChartOptions<"line"> = {
    ...opts,
    plugins: {
      ...opts.plugins,
      tooltip: {
        ...opts.plugins.tooltip,
        callbacks: {
          title: (items) => {
            const d = new Date(Date.UTC(2001, 0, 1 + items[0].dataIndex));
            return d.toLocaleDateString(undefined, { month: "short", day: "numeric", timeZone: "UTC" });
          },
          label: (ctx) => `${ctx.dataset.label}: ${ctx.parsed.y?.toFixed(1)} °C`,
        },
      },
    },
    scales: {
      x: { ...opts.scales.x, ticks: { ...opts.scales.x.ticks, autoSkip: false, callback: (_v, i) => labels[i] || null } },
      y: { ...opts.scales.y, beginAtZero: false, title: { display: true, text: "daily max temperature (°C)", color: c.textMuted } },
    },
  };
  return (
    <div className="chart chart-md" role="img" aria-label="Seasonal cycle of daily maximum temperature compared with the heatwave threshold">
      <Line data={data} options={options} />
    </div>
  );
}

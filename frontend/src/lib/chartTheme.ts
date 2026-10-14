import {
  BarController,
  BarElement,
  CategoryScale,
  Chart as ChartJS,
  Filler,
  Legend,
  LinearScale,
  LineController,
  LineElement,
  PointElement,
  Tooltip,
} from "chart.js";
import { useState } from "react";

ChartJS.register(
  BarController,
  BarElement,
  LineController,
  LineElement,
  PointElement,
  CategoryScale,
  LinearScale,
  Tooltip,
  Legend,
  Filler,
);

export interface ChartColors {
  heat: string;
  heatWash: string;
  trend: string;
  trendWash: string;
  text: string;
  textMuted: string;
  grid: string;
  surface: string;
  reference: string;
}

function read(): ChartColors {
  const css = getComputedStyle(document.documentElement);
  const v = (name: string) => css.getPropertyValue(name).trim();
  return {
    heat: v("--series-heat"),
    heatWash: v("--series-heat-wash"),
    trend: v("--series-trend"),
    trendWash: v("--series-trend-wash"),
    text: v("--text-secondary"),
    textMuted: v("--text-muted"),
    grid: v("--grid"),
    surface: v("--surface-1"),
    reference: v("--text-muted"),
  };
}

/** Chart colors resolved from the CSS tokens, so charts and UI share one palette. */
export function useChartColors(): ChartColors {
  const [colors] = useState<ChartColors>(read);
  return colors;
}

export function baseOptions(c: ChartColors) {
  return {
    responsive: true,
    maintainAspectRatio: false,
    animation: { duration: 300 },
    interaction: { mode: "index" as const, intersect: false },
    plugins: {
      legend: {
        position: "top" as const,
        align: "start" as const,
        labels: { color: c.text, boxWidth: 14, boxHeight: 3, padding: 14, font: { size: 12 } },
      },
      tooltip: {
        backgroundColor: c.surface,
        titleColor: c.text,
        bodyColor: c.text,
        borderColor: c.grid,
        borderWidth: 1,
        padding: 10,
        boxPadding: 4,
        usePointStyle: true,
      },
    },
    scales: {
      x: {
        grid: { display: false },
        border: { color: c.grid },
        ticks: { color: c.textMuted, maxRotation: 0, autoSkipPadding: 12 },
      },
      y: {
        grid: { color: c.grid, lineWidth: 1 },
        border: { display: false },
        ticks: { color: c.textMuted, padding: 6 },
        beginAtZero: true,
      },
    },
  };
}

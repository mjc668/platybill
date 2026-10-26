"use client";

import { useTranslations, useLocale } from "next-intl";
import type { ForecastPoint, TrendPoint } from "@/lib/stats-api";

interface Props {
  trend: TrendPoint[];
  forecast: ForecastPoint[];
  currency: string;
}

const WIDTH = 600;
const HEIGHT = 240;
const PADDING = { top: 16, right: 12, bottom: 56, left: 52 };

function parseAmount(value: string): number {
  const parsed = parseFloat(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function buildTicks(max: number): number[] {
  if (max <= 0) return [0, 1];
  const rough = max / 3;
  const magnitude = 10 ** Math.floor(Math.log10(rough));
  const residual = rough / magnitude;
  const step =
    (residual <= 1 ? 1 : residual <= 2 ? 2 : residual <= 5 ? 5 : 10) * magnitude;
  const top = Math.ceil(max / step) * step;
  const ticks: number[] = [];
  for (let value = 0; value <= top + step / 2; value += step) {
    ticks.push(value);
  }
  return ticks;
}

export default function BillsVsPaymentsChart({ trend, forecast, currency }: Props) {
  const t = useTranslations("Dashboard");
  const locale = useLocale();

  const values = [
    ...trend.flatMap((point) => [
      parseAmount(point.due_total),
      parseAmount(point.paid_total),
    ]),
    ...forecast.map((point) => parseAmount(point.expected_total)),
  ];
  const hasData = values.some((value) => value > 0);

  const formatMonth = (period: string): string => {
    const label = new Intl.DateTimeFormat(locale, { month: "short" }).format(
      new Date(`${period}-01T00:00:00`),
    );
    return label.charAt(0).toUpperCase() + label.slice(1);
  };

  const amountFormatter = new Intl.NumberFormat(locale, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
  const tickFormatter = new Intl.NumberFormat(locale, { maximumFractionDigits: 0 });

  if (!hasData) {
    return (
      <p className="rounded-xl border border-dashed border-slate-200 px-4 py-8 text-center text-sm text-slate-400 dark:border-slate-700 dark:text-slate-500">
        {t("trendEmpty")}
      </p>
    );
  }

  const slots = [
    ...trend.map((point) => ({
      period: point.period,
      due: parseAmount(point.due_total),
      paid: parseAmount(point.paid_total),
      forecast: null as number | null,
    })),
    ...forecast.map((point) => ({
      period: point.period,
      due: null as number | null,
      paid: null as number | null,
      forecast: parseAmount(point.expected_total),
    })),
  ];

  const ticks = buildTicks(Math.max(...values));
  const top = ticks[ticks.length - 1];
  const plotWidth = WIDTH - PADDING.left - PADDING.right;
  const plotHeight = HEIGHT - PADDING.top - PADDING.bottom;
  const bottom = PADDING.top + plotHeight;
  const slotWidth = plotWidth / Math.max(slots.length, 1);
  const pairWidth = slotWidth * 0.6;
  const barWidth = pairWidth * 0.44;
  const barGap = pairWidth - barWidth * 2;
  const forecastBarWidth = pairWidth * 0.7;

  const slotCenter = (index: number): number => PADDING.left + slotWidth * (index + 0.5);
  const barHeight = (value: number): number => (top > 0 ? plotHeight * (value / top) : 0);
  const barY = (value: number): number => PADDING.top + plotHeight - barHeight(value);

  const tooltip = (period: string, label: string, value: number): string =>
    `${formatMonth(period)} · ${label}: ${amountFormatter.format(value)} ${currency}`;

  const boundaryX =
    trend.length > 0 && forecast.length > 0
      ? PADDING.left + slotWidth * trend.length
      : null;

  return (
    <div>
      <svg
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        className="w-full h-auto overflow-visible"
        role="img"
        aria-label={t("trendAriaLabel")}
      >
        {/* Horizontal gridlines + y-axis labels */}
        {ticks.map((tick) => (
          <g key={tick} className="text-slate-200 dark:text-slate-700">
            <line
              x1={PADDING.left}
              y1={barY(tick)}
              x2={WIDTH - PADDING.right}
              y2={barY(tick)}
              stroke="currentColor"
              strokeWidth={1}
            />
            <text
              x={PADDING.left - 8}
              y={barY(tick) + 4}
              textAnchor="end"
              className="fill-slate-400 text-[11px] dark:fill-slate-500"
            >
              {tickFormatter.format(tick)}
            </text>
          </g>
        ))}

        {/* Present boundary between actuals and forecast */}
        {boundaryX !== null && (
          <line
            x1={boundaryX}
            y1={PADDING.top}
            x2={boundaryX}
            y2={bottom}
            stroke="currentColor"
            strokeWidth={1.5}
            className="text-slate-300 dark:text-slate-600"
          />
        )}

        {/* Actual months: due + paid bars */}
        {trend.map((point, index) => {
          const due = parseAmount(point.due_total);
          const paid = parseAmount(point.paid_total);
          const pairLeft = slotCenter(index) - pairWidth / 2;
          return (
            <g key={`actual-${point.period}`}>
              {due > 0 && (
                <rect
                  x={pairLeft}
                  y={barY(due)}
                  width={barWidth}
                  height={barHeight(due)}
                  rx={2}
                  className="fill-slate-300 dark:fill-slate-600"
                >
                  <title>{tooltip(point.period, t("trendDue"), due)}</title>
                </rect>
              )}
              {paid > 0 && (
                <rect
                  x={pairLeft + barWidth + barGap}
                  y={barY(paid)}
                  width={barWidth}
                  height={barHeight(paid)}
                  rx={2}
                  className="fill-blue-500"
                >
                  <title>{tooltip(point.period, t("trendPaid"), paid)}</title>
                </rect>
              )}
            </g>
          );
        })}

        {/* Forecast months: outlined amber bars */}
        {forecast.map((point, index) => {
          const expected = parseAmount(point.expected_total);
          if (expected <= 0) return null;
          const x = slotCenter(trend.length + index) - forecastBarWidth / 2;
          return (
            <rect
              key={`forecast-${point.period}`}
              x={x}
              y={barY(expected)}
              width={forecastBarWidth}
              height={barHeight(expected)}
              rx={2}
              fill="none"
              stroke="currentColor"
              strokeWidth={2}
              className="text-amber-500"
            >
              <title>{tooltip(point.period, t("trendForecast"), expected)}</title>
            </rect>
          );
        })}

        {/* X-axis month labels — rotated so all 12 fit on mobile widths */}
        {slots.map((slot, index) => {
          const labelY = bottom + 12;
          return (
            <text
              key={`label-${index}-${slot.period}`}
              x={slotCenter(index)}
              y={labelY}
              textAnchor="end"
              transform={`rotate(-45 ${slotCenter(index)} ${labelY})`}
              className="fill-slate-400 text-[11px] dark:fill-slate-500"
            >
              {formatMonth(slot.period)}
            </text>
          );
        })}
      </svg>

      <div className="mt-1 flex flex-wrap items-center gap-x-5 gap-y-1 text-xs text-slate-500 dark:text-slate-400">
        <span className="flex items-center gap-1.5">
          <span className="h-2.5 w-2.5 rounded-sm bg-slate-300 dark:bg-slate-600" />
          {t("trendDue")}
        </span>
        <span className="flex items-center gap-1.5">
          <span className="h-2.5 w-2.5 rounded-sm bg-blue-500" />
          {t("trendPaid")}
        </span>
        <span
          data-testid="trend-legend-forecast"
          className="flex items-center gap-1.5"
        >
          <span className="h-2.5 w-2.5 rounded-sm border-2 border-amber-500" />
          {t("trendForecast")}
        </span>
      </div>
    </div>
  );
}

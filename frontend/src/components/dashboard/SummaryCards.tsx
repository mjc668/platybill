"use client";

import { AlertCircle, CalendarClock, CalendarRange, CheckCircle2 } from "lucide-react";
import { useTranslations, useLocale } from "next-intl";
import type {
  OverdueSummary,
  PaidWindow,
  UpcomingWindow,
} from "@/lib/stats-api";

interface Props {
  upcoming7d: UpcomingWindow;
  upcoming30d: UpcomingWindow;
  paid30d: PaidWindow;
  overdue: OverdueSummary;
  currency: string;
}

interface CardConfig {
  key: "overdue" | "next-7d" | "next-30d";
  label: string;
  amount: string;
  count: number;
  accent: string;
  iconClass: string;
  Icon: typeof AlertCircle;
}

function parseAmount(value: string): number {
  const parsed = parseFloat(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

export default function SummaryCards({
  upcoming7d,
  upcoming30d,
  paid30d,
  overdue,
  currency,
}: Props) {
  const t = useTranslations("Dashboard");
  const locale = useLocale();

  const amountFormatter = new Intl.NumberFormat(locale, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });

  const paid = parseAmount(paid30d.paid_total);
  const due = parseAmount(paid30d.due_total);
  const paidPercent =
    due > 0 ? Math.min(Math.max((paid / due) * 100, 0), 100) : 0;

  // Overdue money is still owed in the near term, so the 7-day swatch shows
  // overdue + the next 7 days combined.
  const combined7dTotal = (
    parseAmount(overdue.total) + parseAmount(upcoming7d.total)
  ).toFixed(2);
  const combined7dCount = overdue.count + upcoming7d.count;

  const cards: CardConfig[] = [
    {
      key: "overdue",
      label: t("cardOverdue"),
      amount: overdue.total,
      count: overdue.count,
      accent: "border-l-red-400 dark:border-l-red-500",
      iconClass: "bg-red-100 text-red-600 dark:bg-red-900/40 dark:text-red-400",
      Icon: AlertCircle,
    },
    {
      key: "next-7d",
      label: t("cardOverdueNext7d"),
      amount: combined7dTotal,
      count: combined7dCount,
      accent: "border-l-amber-400 dark:border-l-amber-500",
      iconClass: "bg-amber-100 text-amber-600 dark:bg-amber-900/40 dark:text-amber-400",
      Icon: CalendarClock,
    },
    {
      key: "next-30d",
      label: t("cardNext30d"),
      amount: upcoming30d.total,
      count: upcoming30d.count,
      accent: "border-l-blue-400 dark:border-l-blue-500",
      iconClass: "bg-blue-100 text-blue-600 dark:bg-blue-900/40 dark:text-blue-400",
      Icon: CalendarRange,
    },
  ];

  return (
    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
      {cards.map(({ key, label, amount, count, accent, iconClass, Icon }) => (
        <div
          key={key}
          data-testid={`summary-${key}`}
          className={`rounded-xl border border-slate-200 border-l-4 ${accent} bg-white p-4 shadow-sm dark:border-slate-700 dark:bg-slate-800`}
        >
          <div className="flex items-center gap-3">
            <div className={`rounded-lg p-2 ${iconClass}`}>
              <Icon size={18} />
            </div>
            <p className="text-sm font-medium text-slate-500 dark:text-slate-400">
              {label}
            </p>
          </div>
          <p className="mt-3 text-xl font-semibold tabular-nums text-slate-800 dark:text-slate-100">
            {amountFormatter.format(parseAmount(amount))}{" "}
            <span className="text-sm font-medium text-slate-400 dark:text-slate-500">
              {currency}
            </span>
          </p>
          <p className="mt-0.5 text-xs text-slate-400 dark:text-slate-500">
            {t("cardCount", { count })}
          </p>
        </div>
      ))}

      <div
        data-testid="summary-paid"
        className="rounded-xl border border-slate-200 border-l-4 border-l-blue-400 bg-white p-4 shadow-sm dark:border-slate-700 dark:border-l-blue-500 dark:bg-slate-800"
      >
        <div className="flex items-center gap-3">
          <div className="rounded-lg bg-blue-100 p-2 text-blue-600 dark:bg-blue-900/40 dark:text-blue-400">
            <CheckCircle2 size={18} />
          </div>
          <p className="text-sm font-medium text-slate-500 dark:text-slate-400">
            {t("cardPaid")}
          </p>
        </div>
        <p className="mt-3 text-xl font-semibold tabular-nums text-slate-800 dark:text-slate-100">
          {amountFormatter.format(paid)}{" "}
          <span className="text-sm font-medium text-slate-400 dark:text-slate-500">
            {currency}
          </span>
        </p>
        <div
          role="progressbar"
          aria-label={t("cardPaid")}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={Math.round(paidPercent)}
          className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-slate-100 dark:bg-slate-700"
        >
          <div
            className="h-full rounded-full bg-blue-500"
            style={{ width: `${paidPercent}%` }}
          />
        </div>
        <p className="mt-1 text-xs text-slate-400 dark:text-slate-500">
          {t("cardPaidProgress", {
            percent: Math.round(paidPercent),
            amount: `${amountFormatter.format(due)} ${currency}`,
          })}
        </p>
      </div>
    </div>
  );
}

"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Plus } from "lucide-react";
import { useTranslations, useLocale } from "next-intl";
import { fetchStatsOverview, type StatsOverview } from "@/lib/stats-api";
import {
  fetchPayments,
  type PaymentInstanceOut,
} from "@/lib/payments-api";
import { SessionExpiredError } from "@/lib/api";
import SummaryCards from "@/components/dashboard/SummaryCards";
import BillsVsPaymentsChart from "@/components/dashboard/BillsVsPaymentsChart";
import CategoryBars from "@/components/dashboard/CategoryBars";
import AttentionList from "@/components/dashboard/AttentionList";
import MiniCalendar from "@/components/dashboard/MiniCalendar";

function parseAmount(value: string): number {
  const parsed = parseFloat(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function getCurrentMonth(): string {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
}

function getTodayKey(): string {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
}

export default function DashboardPage() {
  const t = useTranslations("Dashboard");
  const locale = useLocale();
  const [stats, setStats] = useState<StatsOverview | null>(null);
  const [payments, setPayments] = useState<PaymentInstanceOut[] | null>(null);
  const [paymentsMonth, setPaymentsMonth] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);

  useEffect(() => {
    let cancelled = false;
    const month = getCurrentMonth();
    Promise.all([
      fetchStatsOverview(),
      fetchPayments(month).catch((err: unknown) => {
        if (err instanceof SessionExpiredError) throw err;
        return null;
      }),
    ])
      .then(([statsData, paymentsData]) => {
        if (!cancelled) {
          setStats(statsData);
          setPayments(paymentsData);
          setPaymentsMonth(paymentsData !== null ? month : null);
          setLoadError(null);
          setLoading(false);
        }
      })
      .catch((err: unknown) => {
        if (err instanceof SessionExpiredError) return;
        if (!cancelled) {
          setLoadError(err instanceof Error ? err.message : t("loadError"));
          setLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [refreshKey, t]);

  const isEmpty =
    stats !== null &&
    stats.summary.total_count === 0 &&
    !stats.trend.some(
      (point) => parseAmount(point.paid_total) > 0 || parseAmount(point.due_total) > 0,
    ) &&
    !stats.forecast.some((point) => parseAmount(point.expected_total) > 0);

  const monthLabel =
    stats !== null
      ? (() => {
          const label = new Intl.DateTimeFormat(locale, {
            month: "long",
            year: "numeric",
          }).format(new Date(`${stats.month}-01T00:00:00`));
          return label.charAt(0).toUpperCase() + label.slice(1);
        })()
      : null;

  return (
    <div className="mx-auto max-w-4xl px-3 py-4 sm:px-4 sm:py-8">
      <div className="mb-4 sm:mb-6">
        <h1 className="text-2xl font-semibold text-slate-800 dark:text-slate-100 mb-1">
          {t("title")}
        </h1>
        <p className="text-slate-500 dark:text-slate-400">{t("subtitle")}</p>
      </div>

      {/* Loading skeleton */}
      {loading && (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {[1, 2, 3, 4].map((i) => (
            <div
              key={i}
              className="h-28 rounded-xl bg-slate-200 dark:bg-slate-700 animate-pulse"
            />
          ))}
        </div>
      )}

      {/* Error banner */}
      {!loading && loadError && (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-800 dark:bg-red-900/20 dark:text-red-400">
          <span>{loadError}</span>
          <button
            onClick={() => {
              setLoading(true);
              setLoadError(null);
              setRefreshKey((k) => k + 1);
            }}
            className="rounded-lg border border-red-300 bg-white px-3 py-1.5 text-xs font-medium text-red-700 shadow-sm transition-all hover:bg-red-50 dark:border-red-700 dark:bg-slate-800 dark:text-red-400 dark:hover:bg-red-900/30"
          >
            {t("retry")}
          </button>
        </div>
      )}

      {!loading && !loadError && stats !== null && (
        <div className="flex flex-col gap-8">
          {stats.other_currencies.length > 0 && (
            <p className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-2.5 text-sm text-amber-700 dark:border-amber-800 dark:bg-amber-900/20 dark:text-amber-400">
              {t("currencyNote", {
                currency: stats.currency,
                others: stats.other_currencies.join(", "),
              })}
            </p>
          )}

          {isEmpty && (
            <div className="flex flex-col items-center justify-center rounded-2xl border-2 border-dashed border-slate-200 px-6 py-12 text-center dark:border-slate-700">
              <div className="mb-3 rounded-full bg-blue-100 p-4 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400">
                <Plus size={28} />
              </div>
              <p className="font-medium text-slate-700 dark:text-slate-300">
                {t("emptyTitle")}
              </p>
              <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
                {t("emptyDesc")}
              </p>
              <Link
                href="/dashboard/bills"
                className="mt-4 rounded-xl border border-blue-700 bg-blue-700 px-5 py-2 text-sm font-medium text-white shadow-sm transition-all hover:border-blue-800 hover:bg-blue-800"
              >
                {t("emptyCta")}
              </Link>
            </div>
          )}

          {/* Monthly summary */}
          <section>
            <h2 className="mb-3 text-xs font-bold uppercase tracking-widest text-slate-400 dark:text-slate-500">
              {monthLabel}
            </h2>
            <SummaryCards
              upcoming7d={stats.upcoming_7d}
              upcoming30d={stats.upcoming_30d}
              paid30d={stats.paid_30d}
              overdue={stats.overdue}
              currency={stats.currency}
            />
          </section>

          {/* Bills vs payments */}
          <section>
            <h2 className="mb-3 text-xs font-bold uppercase tracking-widest text-slate-400 dark:text-slate-500">
              {t("trendTitle")}
            </h2>
            <BillsVsPaymentsChart
              trend={stats.trend}
              forecast={stats.forecast}
              currency={stats.currency}
            />
          </section>

          {/* Calendar + attention */}
          <div className="grid gap-6 lg:grid-cols-2">
            <section>
              {payments !== null && paymentsMonth !== null && (
                <>
                  <h2 className="mb-3 text-xs font-bold uppercase tracking-widest text-slate-400 dark:text-slate-500">
                    {t("miniCalendarTitle")}
                  </h2>
                  <MiniCalendar
                    month={paymentsMonth}
                    instances={payments}
                    todayStr={getTodayKey()}
                  />
                </>
              )}
            </section>

            <section>
              <h2 className="mb-3 text-xs font-bold uppercase tracking-widest text-slate-400 dark:text-slate-500">
                {t("attentionTitle")}
              </h2>
              <AttentionList items={stats.attention} currency={stats.currency} />
            </section>
          </div>

          {/* Category breakdown */}
          <section>
            <h2 className="mb-3 text-xs font-bold uppercase tracking-widest text-slate-400 dark:text-slate-500">
              {t("categoryTitle")}
            </h2>
            <CategoryBars categories={stats.by_category} currency={stats.currency} />
          </section>
        </div>
      )}
    </div>
  );
}

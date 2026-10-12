"use client";

import { Fragment, useEffect, useState } from "react";
import Link from "next/link";
import {
  CalendarDays,
  ChevronLeft,
  ChevronRight,
  ChevronsUpDown,
  Download,
  List,
  Loader2,
  X,
} from "lucide-react";
import { useTranslations, useLocale } from "next-intl";
import {
  fetchNeedsConfirmation,
  fetchPayments,
  syncInstances,
  type PaymentInstanceOut,
} from "@/lib/payments-api";
import { fetchImportDrafts } from "@/lib/imports-api";
import { type Category } from "@/lib/categories-api";
import { categoryValue, sortCategories } from "@/lib/categories";
import { downloadXlsx } from "@/lib/export-api";
import { SessionExpiredError } from "@/lib/api";
import {
  createAmountFormatter,
  dueAmount,
  formatCurrencyTotals,
  paidAmount,
  remainingAmount,
  sumByCurrency,
} from "@/lib/payment-totals";
import PaymentRow from "@/components/payments/PaymentRow";
import PaymentCalendar from "@/components/payments/PaymentCalendar";
import PaymentFilters, {
  type PaymentStatusFilter,
} from "@/components/payments/PaymentFilters";
import MarkPaidDialog from "@/components/payments/MarkPaidDialog";
import DeletePaymentDialog from "@/components/payments/DeletePaymentDialog";

import { useCollapsedCategories } from "@/hooks/useCollapsedCategories";
import {
  PaymentActionProvider,
  usePaymentActions,
} from "@/context/payment-context";

function getCurrentMonth(): string {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
}

function getMonthLabel(year: number, monthIndex: number, locale: string): string {
  const label = new Intl.DateTimeFormat(locale, { month: "short" }).format(
    new Date(year, monthIndex),
  );
  return label.charAt(0).toUpperCase() + label.slice(1);
}

function monthKey(year: number, monthIndex: number): string {
  return `${year}-${String(monthIndex + 1).padStart(2, "0")}`;
}

function getTodayStr(): string {
  const d = new Date();
  d.setHours(0, 0, 0, 0);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function formatDayLabel(date: string, locale: string): string {
  const label = new Intl.DateTimeFormat(locale, {
    weekday: "short",
    day: "numeric",
    month: "short",
  }).format(new Date(date + "T00:00:00"));
  return label.charAt(0).toUpperCase() + label.slice(1);
}

function daysPast(dueDate: string, todayStr: string): number {
  const due = new Date(dueDate + "T00:00:00").getTime();
  const today = new Date(todayStr + "T00:00:00").getTime();
  return Math.round((today - due) / 86_400_000);
}

const AGING_BUCKETS = [
  { key: "aging1to7", min: 1, max: 7 },
  { key: "aging8to30", min: 8, max: 30 },
  { key: "aging31plus", min: 31, max: Number.POSITIVE_INFINITY },
] as const;

function uniqueCategories(categories: Category[]): Category[] {
  const byId = new Map<number, Category>();
  for (const category of categories) byId.set(category.id, category);
  return [...byId.values()];
}

const SECTION_KEYS = ["overdue", "upcoming", "paid"] as const;
type SectionKey = (typeof SECTION_KEYS)[number];

const SECTION_LABEL_KEYS = {
  overdue: "sectionOverdue",
  upcoming: "sectionUpcoming",
  paid: "sectionPaid",
} as const satisfies Record<SectionKey, string>;

const SECTION_TITLE_CLASS: Record<SectionKey, string> = {
  overdue: "text-red-500 dark:text-red-400",
  upcoming: "text-slate-400 dark:text-slate-500",
  paid: "text-blue-600 dark:text-blue-400",
};

export default function PaymentsPage() {
  return (
    <PaymentActionProvider>
      <PaymentsPageInner />
    </PaymentActionProvider>
  );
}

function PaymentsPageInner() {
  const t = useTranslations("PaymentsPage");
  const tRow = useTranslations("PaymentRow");
  const tRoot = useTranslations();
  const locale = useLocale();
  const amountFormatter = createAmountFormatter(locale);

  const today = new Date();
  const currentYear = today.getFullYear();
  const currentMonth = getCurrentMonth();

  const [selectedMonth, setSelectedMonth] = useState<string>(getCurrentMonth);
  const { dialogTarget, setDialogTarget, deleteTarget, setDeleteTarget } = usePaymentActions();
  const [instances, setInstances] = useState<PaymentInstanceOut[]>([]);
  const [loadedMonth, setLoadedMonth] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [xlsxLoadingYear, setXlsxLoadingYear] = useState<number | null>(null);
  const [xlsxError, setXlsxError] = useState<string | null>(null);
  const [view, setView] = useState<"list" | "calendar">("list");
  const [statusFilter, setStatusFilter] = useState<PaymentStatusFilter>("all");
  const [categoryFilter, setCategoryFilter] = useState<string>("all");
  const [searchFilter, setSearchFilter] = useState("");
  const [reloadToken, setReloadToken] = useState(0);
  const [reviewCount, setReviewCount] = useState(0);

  // Derived: true whenever selectedMonth hasn't finished loading yet.
  // Becomes true immediately when selectedMonth changes (same render), so no
  // synchronous setState inside useEffect is needed.
  const loading = loadedMonth !== selectedMonth;

  const isReadOnly = selectedMonth < currentMonth;

  useEffect(() => {
    let cancelled = false;
    const isCurrentOrFuture = selectedMonth >= currentMonth;
    (isCurrentOrFuture ? syncInstances(selectedMonth).catch(() => {}) : Promise.resolve())
      .then(() => fetchPayments(selectedMonth, isCurrentOrFuture))
      .then((data) => {
        if (!cancelled) {
          setInstances(data);
          setLoadError(null);
          setLoadedMonth(selectedMonth);
        }
      })
      .catch((err: unknown) => {
        if (err instanceof SessionExpiredError) return;
        if (!cancelled) {
          setLoadError(err instanceof Error ? err.message : t("loadError"));
          setLoadedMonth(selectedMonth);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [selectedMonth, currentMonth, t, reloadToken]);

  function handleInstancePaid(updated: PaymentInstanceOut) {
    setInstances((prev) =>
      prev.map((inst) => (inst.id === updated.id ? updated : inst)),
    );
    setDialogTarget(null);
    setReloadToken((token) => token + 1);
  }

  useEffect(() => {
    let cancelled = false;
    Promise.all([fetchImportDrafts(), fetchNeedsConfirmation()])
      .then(([drafts, estimates]) => {
        if (!cancelled) setReviewCount(drafts.length + estimates.length);
      })
      .catch(() => {
        if (!cancelled) setReviewCount(0);
      });
    return () => {
      cancelled = true;
    };
  }, [reloadToken]);

  function handleInstanceDeleted(id: number) {
    setInstances((prev) => prev.filter((inst) => inst.id !== id));
    setDeleteTarget(null);
  }

  function handleInstanceReverted(updated: PaymentInstanceOut) {
    setInstances((prev) =>
      prev.map((inst) => (inst.id === updated.id ? updated : inst)),
    );
  }

  const [selectedYear, setSelectedYear] = useState(currentYear);

  // Deep link support: /dashboard/payments?month=YYYY-MM preselects that month.
  // Uses window.location (not useSearchParams) to avoid a Suspense boundary.
  useEffect(() => {
    const monthParam = new URLSearchParams(window.location.search).get("month");
    if (!monthParam || !/^\d{4}-\d{2}$/.test(monthParam)) return;
    const [yearStr, monthStr] = monthParam.split("-");
    const monthIndex = parseInt(monthStr, 10);
    if (monthIndex < 1 || monthIndex > 12) return;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- one-shot post-hydration read of the browser-only deep link; a lazy initializer would risk a hydration mismatch
    setSelectedMonth(monthParam);
    setSelectedYear(parseInt(yearStr, 10));
  }, []);

  const todayStr = getTodayStr();

  const activeCategories = sortCategories(
    uniqueCategories(instances.map((inst) => inst.category)),
    locale,
    tRoot,
  );

  const { collapsed, toggle, collapseAll, expandAll, allCollapsed } =
    useCollapsedCategories("payments-collapsed-sections", SECTION_KEYS);

  const searchQuery = searchFilter.trim().toLowerCase();
  const hasActiveFilters =
    statusFilter !== "all" || categoryFilter !== "all" || searchQuery !== "";

  const filteredInstances = instances.filter((inst) => {
    if (statusFilter === "unpaid" && inst.status === "paid") return false;
    if (statusFilter === "overdue" && inst.status !== "overdue") return false;
    if (statusFilter === "paid" && inst.status !== "paid") return false;
    if (categoryFilter !== "all" && categoryValue(inst.category) !== categoryFilter) return false;
    if (searchQuery && !inst.bill_name.toLowerCase().includes(searchQuery)) return false;
    return true;
  });

  const monthDue = sumByCurrency(instances, dueAmount);
  const monthPaid = sumByCurrency(instances, paidAmount);
  const monthRemaining = sumByCurrency(instances, remainingAmount);

  // Urgency-first list: overdue, then upcoming, then paid — each by due date.
  // Totals use the remaining balance (or the paid amount for the Paid section)
  // and are grouped per currency since bills can differ.
  const sections = SECTION_KEYS.map((key) => {
    const items = filteredInstances
      .filter((inst) => inst.status === key)
      .sort(
        (a, b) =>
          a.due_date.localeCompare(b.due_date) ||
          a.bill_name.localeCompare(b.bill_name),
      );
    const valueOf = key === "paid" ? paidAmount : remainingAmount;
    const totals = sumByCurrency(items, valueOf);
    const groups: { dueDate: string; items: PaymentInstanceOut[] }[] = [];
    for (const inst of items) {
      const last = groups[groups.length - 1];
      if (last && last.dueDate === inst.due_date) {
        last.items.push(inst);
      } else {
        groups.push({ dueDate: inst.due_date, items: [inst] });
      }
    }
    const aging =
      key === "overdue"
        ? AGING_BUCKETS.map((bucket) => ({
            key: bucket.key,
            items: items.filter((inst) => {
              const days = daysPast(inst.due_date, todayStr);
              return days >= bucket.min && days <= bucket.max;
            }),
          })).filter((bucket) => bucket.items.length > 0)
        : [];
    return { key, items, totals, groups, aging };
  }).filter((section) => section.items.length > 0);

  // The calendar stays month-scoped even when the list includes overdue items
  // carried over from earlier periods.
  const calendarInstances = filteredInstances.filter(
    (inst) => inst.period === selectedMonth,
  );

  function clearFilters() {
    setStatusFilter("all");
    setCategoryFilter("all");
    setSearchFilter("");
  }

  async function handleExportXlsx(year: number) {
    setXlsxError(null);
    setXlsxLoadingYear(year);
    try {
      await downloadXlsx(year);
    } catch {
      setXlsxError(t("exportXlsxError"));
    } finally {
      setXlsxLoadingYear(null);
    }
  }

  return (
    <div className="mx-auto max-w-4xl px-4 py-8">
      {dialogTarget && (
        <MarkPaidDialog
          instance={dialogTarget}
          isOpen={true}
          onClose={() => setDialogTarget(null)}
          onConfirm={handleInstancePaid}
        />
      )}
      {deleteTarget && (
        <DeletePaymentDialog
          instance={deleteTarget}
          isOpen={true}
          onClose={() => setDeleteTarget(null)}
          onDeleted={handleInstanceDeleted}
        />
      )}
      {reviewCount > 0 && (
        <Link
          href="/dashboard/bills"
          data-testid="bills-to-review-link"
          className="mb-4 flex items-center justify-between gap-3 rounded-xl border border-blue-200 bg-blue-50/60 px-3 py-2 text-sm text-blue-800 transition-colors hover:bg-blue-100 dark:border-blue-900/60 dark:bg-blue-900/10 dark:text-blue-300 dark:hover:bg-blue-900/20"
        >
          <span>{t("reviewLink", { count: reviewCount })}</span>
          <span className="font-medium">{t("reviewLinkAction")} →</span>
        </Link>
      )}

      {/* Page header */}
      <div className="mb-6 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-slate-800 dark:text-slate-100">
            {t("title")}
          </h1>
          <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
            {t("subtitle")}
          </p>
        </div>
        <div className="flex items-center gap-2">
        <div className="flex rounded-xl border border-slate-200 bg-white p-0.5 shadow-sm dark:border-slate-700 dark:bg-slate-800">
          <button
            type="button"
            aria-pressed={view === "list"}
            onClick={() => setView("list")}
            className={`flex items-center gap-1.5 rounded-[10px] px-3 py-1.5 text-sm font-medium transition-colors ${
              view === "list"
                ? "bg-blue-700 text-white shadow-sm"
                : "text-slate-500 hover:text-slate-700 dark:text-slate-400 dark:hover:text-slate-200"
            }`}
          >
            <List size={14} />
            {t("viewList")}
          </button>
          <button
            type="button"
            aria-pressed={view === "calendar"}
            onClick={() => setView("calendar")}
            className={`flex items-center gap-1.5 rounded-[10px] px-3 py-1.5 text-sm font-medium transition-colors ${
              view === "calendar"
                ? "bg-blue-700 text-white shadow-sm"
                : "text-slate-500 hover:text-slate-700 dark:text-slate-400 dark:hover:text-slate-200"
            }`}
          >
            <CalendarDays size={14} />
            {t("viewCalendar")}
          </button>
        </div>
        </div>
      </div>

      {/* Month selector */}
      <div className="mb-6">
        {/* Year navigation */}
        <div className="flex items-center gap-1 mb-3">
          <button
            onClick={() => setSelectedYear((y) => y - 1)}
            disabled={selectedYear <= currentYear - 2}
            className="rounded p-1 text-slate-400 hover:text-slate-600 disabled:opacity-30 dark:text-slate-500 dark:hover:text-slate-300 transition-colors"
          >
            <ChevronLeft size={18} />
          </button>
          <span className="text-lg font-semibold text-slate-700 dark:text-slate-200 w-14 text-center tabular-nums">
            {selectedYear}
          </span>
          <button
            onClick={() => setSelectedYear((y) => y + 1)}
            disabled={selectedYear >= currentYear + 1}
            className="rounded p-1 text-slate-400 hover:text-slate-600 disabled:opacity-30 dark:text-slate-500 dark:hover:text-slate-300 transition-colors"
          >
            <ChevronRight size={18} />
          </button>
        </div>

        {/* Timeline strip */}
        <div className="relative">
          {/* Track */}
          <div className="absolute bottom-0 left-0 right-0 h-px bg-slate-200 dark:bg-slate-700" />
          <div className="flex">
            {Array.from({ length: 12 }, (_, i) => {
              const key = monthKey(selectedYear, i);
              const isSelected = key === selectedMonth;
              const isCurrent = key === currentMonth;
              const isPast = key < currentMonth;
              return (
                <button
                  key={key}
                  onClick={() => setSelectedMonth(key)}
                  className={`relative flex flex-1 flex-col items-center gap-1 pb-2.5 pt-2 text-sm font-medium transition-colors focus:outline-none ${
                    isSelected
                      ? "text-blue-700 dark:text-blue-400"
                      : isPast
                      ? "text-slate-400 dark:text-slate-500 hover:text-slate-600 dark:hover:text-slate-300"
                      : "text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-slate-200"
                  }`}
                >
                  {isCurrent && (
                    <span className="absolute top-0.5 left-1/2 -translate-x-1/2 w-1 h-1 rounded-full bg-blue-500 dark:bg-blue-400" />
                  )}
                  {getMonthLabel(selectedYear, i, locale)}
                  <span
                    className={`absolute bottom-0 left-1 right-1 h-0.5 rounded-full transition-all ${
                      isSelected ? "bg-blue-600 dark:bg-blue-500" : "bg-transparent"
                    }`}
                  />
                </button>
              );
            })}
          </div>
        </div>

        {/* Export */}
        <div className="mt-4 flex items-center justify-end gap-3">
          <button
            onClick={() => handleExportXlsx(selectedYear)}
            disabled={xlsxLoadingYear !== null}
            className="group flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-3.5 py-2 text-sm font-medium text-slate-600 shadow-sm transition-all hover:border-blue-300 hover:bg-blue-50 hover:text-blue-700 disabled:cursor-not-allowed disabled:opacity-50 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-400 dark:hover:border-blue-700 dark:hover:bg-blue-900/20 dark:hover:text-blue-400"
          >
            {xlsxLoadingYear === selectedYear ? (
              <Loader2 size={15} className="animate-spin text-blue-600 dark:text-blue-400" />
            ) : (
              <Download size={15} className="transition-transform group-hover:-translate-y-0.5" />
            )}
            {xlsxLoadingYear === selectedYear ? t("exportXlsxLoading") : t("exportXlsx")}
            <span className="rounded bg-slate-100 px-1.5 py-0.5 text-xs font-semibold text-slate-400 dark:bg-slate-700 dark:text-slate-500">
              {selectedYear}
            </span>
          </button>
          {xlsxError && (
            <p className="text-sm text-red-600 dark:text-red-400">{xlsxError}</p>
          )}
        </div>
      </div>

      {/* Selected month header */}
      <div className="mb-4 pb-3 border-b border-slate-200 dark:border-slate-700">
        <div className="flex items-center gap-2">
          <h2 className="text-lg font-semibold text-slate-800 dark:text-slate-100">
            {(() => {
              const label = new Intl.DateTimeFormat(locale, { month: "long", year: "numeric" }).format(
                new Date(
                  parseInt(selectedMonth.split("-")[0]),
                  parseInt(selectedMonth.split("-")[1]) - 1,
                ),
              );
              return label.charAt(0).toUpperCase() + label.slice(1);
            })()}
          </h2>
          {isReadOnly && (
            <span className="rounded-md px-1.5 py-0.5 text-xs font-medium bg-slate-100 text-slate-500 dark:bg-slate-700 dark:text-slate-400">
              {t("pastMonth")}
            </span>
          )}
        </div>
        {!loading && !loadError && instances.length > 0 && (
          <div className="mt-0.5 flex items-center justify-between gap-3">
            <p className="text-sm text-slate-500 dark:text-slate-400">
              {[
                instances.filter((i) => i.status === "upcoming").length > 0 &&
                  `${instances.filter((i) => i.status === "upcoming").length} ${tRow("status.upcoming").toLowerCase()}`,
                instances.filter((i) => i.status === "overdue").length > 0 &&
                  `${instances.filter((i) => i.status === "overdue").length} ${tRow("status.overdue").toLowerCase()}`,
                instances.filter((i) => i.status === "paid").length > 0 &&
                  `${instances.filter((i) => i.status === "paid").length} ${tRow("status.paid").toLowerCase()}`,
              ]
                .filter(Boolean)
                .join(" · ")}
            </p>
            {sections.length > 1 && (
              <button
                onClick={allCollapsed ? expandAll : collapseAll}
                className="flex shrink-0 items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-500 shadow-sm transition-all hover:border-slate-300 hover:bg-slate-50 hover:text-slate-700 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-400 dark:hover:border-slate-600 dark:hover:text-slate-200"
              >
                <ChevronsUpDown size={13} />
                {allCollapsed ? t("expandAll") : t("collapseAll")}
              </button>
            )}
          </div>
        )}
        {!loading && !loadError && instances.length > 0 && (
          <div className="mt-3 space-y-2.5">
            {[...monthDue].map(([currency, due]) => {
              const paid = monthPaid.get(currency) ?? 0;
              const remaining = monthRemaining.get(currency) ?? 0;
              const paidPercent =
                due > 0 ? Math.min(100, Math.max(0, (paid / due) * 100)) : 0;
              return (
                <div key={currency} className="flex flex-col gap-1">
                  <p className="text-xs font-medium tabular-nums text-slate-500 dark:text-slate-400">
                    {t("monthDue")}: {amountFormatter.format(due)} {currency}
                    <span className="mx-1.5 text-slate-300 dark:text-slate-600">·</span>
                    {t("monthPaid")}: {amountFormatter.format(paid)} {currency}
                    <span className="mx-1.5 text-slate-300 dark:text-slate-600">·</span>
                    {t("monthRemaining")}: {amountFormatter.format(remaining)} {currency}
                  </p>
                  <div
                    role="progressbar"
                    aria-label={`${t("monthPaid")} / ${t("monthDue")}`}
                    aria-valuemin={0}
                    aria-valuemax={100}
                    aria-valuenow={Math.round(paidPercent)}
                    className="h-1.5 w-full overflow-hidden rounded bg-slate-100 dark:bg-slate-700"
                  >
                    <div
                      className="h-full rounded bg-blue-500"
                      style={{ width: `${paidPercent}%` }}
                    />
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Error banner */}
      {loadError && (
        <div className="mb-4 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-800 dark:bg-red-900/20 dark:text-red-400">
          {loadError}
        </div>
      )}

      {/* Loading skeleton */}
      {loading && (
        <div className="space-y-3">
          {[1, 2, 3].map((i) => (
            <div
              key={i}
              className="h-14 rounded-xl bg-slate-200 dark:bg-slate-700 animate-pulse"
            />
          ))}
        </div>
      )}

      {/* Filters */}
      {!loading && !loadError && instances.length > 0 && (
        <PaymentFilters
          status={statusFilter}
          category={categoryFilter}
          search={searchFilter}
          categories={activeCategories}
          onStatusChange={setStatusFilter}
          onCategoryChange={setCategoryFilter}
          onSearchChange={setSearchFilter}
          onClear={clearFilters}
          hasActiveFilters={hasActiveFilters}
        />
      )}

      {/* No matches */}
      {!loading &&
        !loadError &&
        instances.length > 0 &&
        filteredInstances.length === 0 && (
          <div
            data-testid="payment-no-matches"
            className="flex flex-col items-center justify-center rounded-2xl border-2 border-dashed border-slate-200 dark:border-slate-700 px-6 py-12 text-center"
          >
            <p className="font-medium text-slate-700 dark:text-slate-300">
              {t("noMatches")}
            </p>
            <button
              onClick={clearFilters}
              className="mt-3 flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-sm font-medium text-slate-600 shadow-sm transition-all hover:border-slate-300 hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-300 dark:hover:bg-slate-700"
            >
              <X size={14} />
              {t("clearFilters")}
            </button>
          </div>
        )}

      {/* Payment calendar */}
      {!loading &&
        !loadError &&
        view === "calendar" &&
        calendarInstances.length > 0 && (
          <PaymentCalendar
            key={selectedMonth}
            month={selectedMonth}
            instances={calendarInstances}
            todayStr={todayStr}
            onMarkPaid={setDialogTarget}
            onDelete={setDeleteTarget}
            onReverted={handleInstanceReverted}
          />
        )}

      {/* Payment list */}
      {!loading && !loadError && view === "list" && filteredInstances.length > 0 && (
        <div className="flex flex-col gap-4">
          {sections.map(({ key, items, totals, groups, aging }) => (
            <div key={key} data-testid={`payment-section-${key}`}>
              <button
                onClick={() => toggle(key)}
                className="mb-3 flex w-full items-center gap-2.5 text-left"
              >
                <ChevronRight
                  size={12}
                  className={`shrink-0 text-slate-400 dark:text-slate-500 transition-transform duration-150 ${
                    collapsed.has(key) ? "" : "rotate-90"
                  }`}
                />
                <span
                  className={`text-xs font-bold uppercase tracking-widest shrink-0 ${SECTION_TITLE_CLASS[key]}`}
                >
                  {t(SECTION_LABEL_KEYS[key])}
                </span>
                <span className="rounded-full bg-slate-100 dark:bg-slate-700 px-1.5 py-0.5 text-xs font-semibold text-slate-400 dark:text-slate-500 shrink-0 tabular-nums">
                  {items.length}
                </span>
                <span className="shrink-0 text-xs font-medium tabular-nums text-slate-400 dark:text-slate-500">
                  {[...totals]
                    .map(
                      ([cur, value]) =>
                        `${amountFormatter.format(value)} ${cur}`,
                    )
                    .join(" · ")}
                </span>
                <div className="flex-1 h-px bg-slate-100 dark:bg-slate-700/60" />
              </button>
              {!collapsed.has(key) && (
                <div className="flex flex-col gap-2">
                  {key === "overdue" && aging.length > 0 && (
                    <div className="flex flex-wrap items-center gap-1.5">
                      <span className="text-[11px] font-semibold uppercase tracking-wide text-slate-400 dark:text-slate-500">
                        {t("overdueAging")}
                      </span>
                      {aging.map((bucket) => (
                        <span
                          key={bucket.key}
                          className="rounded-full bg-red-50 px-2 py-0.5 text-[11px] font-medium text-red-600 dark:bg-red-900/20 dark:text-red-400"
                        >
                          {t(bucket.key)} · {bucket.items.length} ·{" "}
                          <span className="tabular-nums">
                            {formatCurrencyTotals(
                              sumByCurrency(bucket.items, remainingAmount),
                              amountFormatter,
                            )}
                          </span>
                        </span>
                      ))}
                    </div>
                  )}
                  {groups.map((group) => (
                    <Fragment key={group.dueDate}>
                      <div className="flex items-center gap-2 pt-1">
                        <span className="shrink-0 text-[11px] font-semibold capitalize text-slate-500 dark:text-slate-400">
                          {formatDayLabel(group.dueDate, locale)}
                        </span>
                        <span className="shrink-0 text-[11px] font-medium tabular-nums text-slate-400 dark:text-slate-500">
                          {formatCurrencyTotals(
                            sumByCurrency(
                              group.items,
                              key === "paid" ? paidAmount : remainingAmount,
                            ),
                            amountFormatter,
                          )}
                        </span>
                        <div className="h-px flex-1 bg-slate-100 dark:bg-slate-700/60" />
                      </div>
                      {group.items.map((inst) => (
                        <PaymentRow
                          key={inst.id}
                          instance={inst}
                          readOnly={false}
                          onMarkPaid={setDialogTarget}
                          onDelete={setDeleteTarget}
                          onReverted={handleInstanceReverted}
                        />
                      ))}
                    </Fragment>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Empty state */}
      {!loading &&
        !loadError &&
        (instances.length === 0 ||
          (view === "calendar" && calendarInstances.length === 0)) && (
        <div className="flex flex-col items-center justify-center rounded-2xl border-2 border-dashed border-slate-200 dark:border-slate-700 px-6 py-16 text-center">
          <p className="font-medium text-slate-700 dark:text-slate-300">
            {t("noPayments")}
          </p>
          {!isReadOnly && (
            <Link
              href="/dashboard/bills"
              className="mt-3 text-sm font-medium text-blue-700 hover:underline dark:text-blue-500"
            >
              {t("addBills")}
            </Link>
          )}
        </div>
      )}
    </div>
  );
}

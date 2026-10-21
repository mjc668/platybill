"use client";

import { Search, X } from "lucide-react";
import { useTranslations } from "next-intl";
import { categoryLabel, type Category } from "@/lib/categories-api";
import { categoryValue } from "@/lib/categories";

export type PaymentStatusFilter = "all" | "unpaid" | "overdue" | "paid";

interface Props {
  status: PaymentStatusFilter;
  /** Option value from `categoryValue`, or "all". */
  category: string;
  search: string;
  categories: Category[];
  onStatusChange: (status: PaymentStatusFilter) => void;
  onCategoryChange: (category: string) => void;
  onSearchChange: (search: string) => void;
  onClear: () => void;
  hasActiveFilters: boolean;
}

const labelClass =
  "mb-1 block text-xs font-semibold uppercase tracking-wide text-slate-400 dark:text-slate-500";
const selectClass =
  "w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-base sm:text-sm text-slate-800 outline-none transition-all focus:border-blue-500 focus:ring-2 focus:ring-blue-100 dark:border-slate-600 dark:bg-slate-700 dark:text-slate-100 dark:focus:border-blue-600 dark:focus:ring-blue-900/40";

export default function PaymentFilters({
  status,
  category,
  search,
  categories,
  onStatusChange,
  onCategoryChange,
  onSearchChange,
  onClear,
  hasActiveFilters,
}: Props) {
  const t = useTranslations("PaymentsPage");
  const tRoot = useTranslations();

  return (
    <div
      data-testid="payment-filters"
      className="mb-4 rounded-xl border border-slate-200 bg-white p-3 shadow-sm dark:border-slate-700 dark:bg-slate-800"
    >
      <div className="grid gap-3 sm:grid-cols-3">
        <div>
          <label htmlFor="payment-filter-status" className={labelClass}>
            {t("filtersStatus")}
          </label>
          <select
            id="payment-filter-status"
            value={status}
            onChange={(e) => onStatusChange(e.target.value as PaymentStatusFilter)}
            className={selectClass}
          >
            <option value="all">{t("filterAllStatuses")}</option>
            <option value="unpaid">{t("filterUnpaid")}</option>
            <option value="overdue">{t("filterOverdue")}</option>
            <option value="paid">{t("filterPaid")}</option>
          </select>
        </div>

        <div>
          <label htmlFor="payment-filter-category" className={labelClass}>
            {t("filtersCategory")}
          </label>
          <select
            id="payment-filter-category"
            value={category}
            onChange={(e) => onCategoryChange(e.target.value)}
            className={selectClass}
          >
            <option value="all">{t("filterAllCategories")}</option>
            {categories.map((cat) => (
              <option key={cat.id} value={categoryValue(cat)}>
                {categoryLabel(cat, tRoot)}
              </option>
            ))}
          </select>
        </div>

        <div>
          <label htmlFor="payment-filter-search" className={labelClass}>
            {t("filtersName")}
          </label>
          <div className="relative">
            <Search
              size={14}
              className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400 dark:text-slate-500"
            />
            <input
              id="payment-filter-search"
              type="search"
              value={search}
              onChange={(e) => onSearchChange(e.target.value)}
              placeholder={t("searchPlaceholder")}
              className={selectClass + " pl-8"}
            />
          </div>
        </div>
      </div>

      {hasActiveFilters && (
        <div className="mt-3 flex justify-end">
          <button
            onClick={onClear}
            className="flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-500 shadow-sm transition-all hover:border-slate-300 hover:bg-slate-50 hover:text-slate-700 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-400 dark:hover:border-slate-600 dark:hover:text-slate-200"
          >
            <X size={13} />
            {t("clearFilters")}
          </button>
        </div>
      )}
    </div>
  );
}

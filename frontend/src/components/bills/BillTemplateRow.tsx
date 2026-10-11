"use client";

import { useState } from "react";
import {
  Pencil,
  Archive as ArchiveIcon,
  ChevronUp,
  PauseCircle,
  NotebookPen,
  MoreHorizontal,
} from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import BillTemplateForm from "./BillTemplateForm";
import type { Category } from "@/lib/categories-api";
import {
  normalizeBillFrequency,
  type BillTemplateOut,
  type BillTemplateUpdate,
} from "@/lib/bills-api";

interface Props {
  template: BillTemplateOut;
  isExpanded: boolean;
  /** Actual next unpaid instance, shown in the "next due" view. */
  nextDue?: { date: string; amount: string } | null;
  /** Non-archived categories offered by the edit form's picker. */
  categories: Category[];
  onCategoryCreated: (category: Category) => void;
  /** Positional palette class for this bill's category. */
  colorClass: string;
  onEditToggle: () => void;
  onSave: (data: BillTemplateUpdate) => Promise<void>;
  onArchive: () => void;
}

function formatDueLabel(template: BillTemplateOut, locale: string): string | null {
  const { due_day, due_month, start_period, start_date } = template;
  const frequency = normalizeBillFrequency(template.frequency);

  if (frequency === "one_off") {
    if (!start_period) return null;
    const [year, month] = start_period.split("-").map(Number);
    const monthName = new Intl.DateTimeFormat(locale, { month: "short" }).format(
      new Date(year, month - 1)
    );
    if (due_day != null) return `${monthName} ${due_day}`;
    return new Intl.DateTimeFormat(locale, { month: "short", year: "numeric" }).format(
      new Date(year, month - 1)
    );
  }

  if (frequency === "weekly") {
    if (!start_date) return null;
    return new Intl.DateTimeFormat(locale, { day: "numeric", month: "short" }).format(
      new Date(start_date + "T00:00:00")
    );
  }

  if (frequency === "annual" && due_day != null && due_month != null) {
    const monthName = new Intl.DateTimeFormat(locale, { month: "short" }).format(
      new Date(2000, due_month - 1)
    );
    return `${monthName} ${due_day}`;
  }

  if (due_day != null) return String(due_day);
  return null;
}

function localTodayIso(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

export default function BillTemplateRow({
  template,
  isExpanded,
  nextDue,
  categories,
  onCategoryCreated,
  colorClass,
  onEditToggle,
  onSave,
  onArchive,
}: Props) {
  const t = useTranslations("BillTemplateRow");
  const tFreq = useTranslations("Frequencies");
  const locale = useLocale();
  const [actionsOpen, setActionsOpen] = useState(false);

  const frequency = normalizeBillFrequency(template.frequency);
  const dueLabel = formatDueLabel(template, locale);
  const nextDueOverdue = nextDue != null && nextDue.date < localTodayIso();

  // Paused overrides category color with amber
  const leftBorder = template.is_paused
    ? "border-l-amber-400 dark:border-l-amber-500"
    : colorClass;

  return (
    <div
      className={`group rounded-xl border border-slate-200 bg-white overflow-hidden shadow-sm dark:bg-slate-800 dark:border-slate-700 border-l-4 ${leftBorder}`}
    >
      {/* Collapsed row */}
      <div
        className={`flex items-center gap-3 px-4 py-3 ${template.is_paused ? "opacity-60" : ""}`}
      >
        {/* Two-line content */}
        <div className="flex flex-1 flex-col min-w-0 gap-0.5">
          {/* Line 1: name + paused badge */}
          <div className="flex items-center gap-2 min-w-0">
            <span className="font-semibold text-sm text-slate-800 dark:text-slate-100 truncate">
              {template.name}
            </span>
            {template.is_paused && (
              <span className="flex items-center gap-1 rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-700 dark:bg-amber-900/30 dark:text-amber-400 shrink-0">
                <PauseCircle size={10} />
                {t("paused")}
              </span>
            )}
          </div>

          {/* Line 2: amount · frequency · due */}
          <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
            <span className="text-xs font-medium text-slate-600 dark:text-slate-300">
              {template.amount} {template.currency}
            </span>
            <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-500 dark:bg-slate-700 dark:text-slate-400">
              {t(`frequency.${frequency}`, { count: template.interval_count ?? 1 })}
            </span>
            {frequency !== "one_off" && template.max_occurrences != null && (
              <span className="text-xs text-slate-400 dark:text-slate-500">
                · {tFreq("paymentCount", { count: template.max_occurrences })}
              </span>
            )}
            {dueLabel && (
              <span className="text-xs text-slate-400 dark:text-slate-500">
                {frequency === "weekly" ? (
                  t("startsOn", { date: dueLabel })
                ) : (
                  <>{t("dueOn")}&nbsp;{dueLabel}</>
                )}
              </span>
            )}
            {nextDue && (
              <span
                className={`rounded-full px-2 py-0.5 text-xs font-medium ${
                  nextDueOverdue
                    ? "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400"
                    : "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400"
                }`}
              >
                {nextDueOverdue ? t("nextDueOverdue") : t("nextDueOn")}{" "}
                {new Intl.DateTimeFormat(locale, {
                  day: "numeric",
                  month: "short",
                }).format(new Date(nextDue.date + "T00:00:00"))}
                {" · "}
                {nextDue.amount} {template.currency}
              </span>
            )}
          </div>

          {/* Notes */}
          {template.notes && (
            <div className="flex items-start gap-1 mt-0.5 text-xs text-slate-400 dark:text-slate-500">
              <NotebookPen size={10} className="mt-0.5 shrink-0" />
              <span className="line-clamp-1">{template.notes}</span>
            </div>
          )}
        </div>

        {/* Actions */}
        <div className="flex items-center gap-1 shrink-0">
          {/* Mobile: ⋯ toggle */}
          <button
            onClick={() => setActionsOpen((o) => !o)}
            aria-label="More actions"
            className="sm:hidden rounded-lg p-1.5 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-600 dark:text-slate-500 dark:hover:bg-slate-700 dark:hover:text-slate-300"
          >
            <MoreHorizontal size={16} />
          </button>

          {/* Edit + Archive: hidden on mobile unless actionsOpen; hover-reveal on sm+ */}
          <div
            className={`items-center gap-1 ${
              actionsOpen ? "flex" : "hidden"
            } sm:flex sm:opacity-0 sm:group-hover:opacity-100 sm:focus-within:opacity-100 sm:transition-opacity sm:duration-150`}
          >
            <button
              onClick={onEditToggle}
              aria-label={isExpanded ? t("close") : t("edit")}
              className="flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 text-sm font-medium text-slate-500 shadow-sm transition-all hover:border-blue-300 hover:bg-blue-50 hover:text-blue-700 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-400 dark:hover:border-blue-700 dark:hover:bg-blue-900/20 dark:hover:text-blue-400"
            >
              {isExpanded ? <ChevronUp size={15} /> : <Pencil size={15} />}
              <span className="hidden sm:inline">{isExpanded ? t("close") : t("edit")}</span>
            </button>
            <button
              onClick={onArchive}
              aria-label={t("archive")}
              className="flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 text-sm font-medium text-slate-400 shadow-sm transition-all hover:border-red-300 hover:bg-red-50 hover:text-red-600 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-500 dark:hover:border-red-800 dark:hover:bg-red-900/20 dark:hover:text-red-400"
            >
              <ArchiveIcon size={15} />
              <span className="hidden sm:inline">{t("archive")}</span>
            </button>
          </div>
        </div>
      </div>

      {/* Expanded edit form */}
      {isExpanded && (
        <div className="border-t border-slate-100 dark:border-slate-700 bg-slate-50 dark:bg-slate-900/40 p-5">
          <BillTemplateForm
            initial={{
              name: template.name,
              category_id: template.category.id,
              frequency: template.frequency,
              interval_count: template.interval_count,
              max_occurrences: template.max_occurrences,
              start_date: template.start_date,
              amount: template.amount,
              currency: template.currency,
              due_day: template.due_day,
              due_month: template.due_month,
              notes: template.notes,
              is_paused: template.is_paused,
            }}
            initialCategory={template.category}
            categories={categories}
            onCategoryCreated={onCategoryCreated}
            onSave={onSave}
            onCancel={onEditToggle}
          />
        </div>
      )}
    </div>
  );
}

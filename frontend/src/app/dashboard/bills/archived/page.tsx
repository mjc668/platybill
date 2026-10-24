"use client";

import { useEffect, useState } from "react";
import { Archive, ArchiveRestore, ChevronRight, ChevronsUpDown, Loader2, Trash2 } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import {
  deleteBill,
  fetchBills,
  normalizeBillFrequency,
  unarchiveBill,
  type BillTemplateOut,
} from "@/lib/bills-api";
import { fetchCategories, categoryLabel, type Category } from "@/lib/categories-api";
import { bankAccountLabel } from "@/lib/bank-accounts-api";
import { sortCategories } from "@/lib/categories";
import { SessionExpiredError } from "@/lib/api";
import { useCollapsedCategories } from "@/hooks/useCollapsedCategories";
import DeleteBillDialog from "@/components/bills/DeleteBillDialog";

export default function ArchivedBillsPage() {
  const t = useTranslations("ArchivedBillsPage");
  const tFreq = useTranslations("Frequencies");
  const tRoot = useTranslations();
  const locale = useLocale();
  const [templates, setTemplates] = useState<BillTemplateOut[]>([]);
  const [categories, setCategories] = useState<Category[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [unarchivingId, setUnarchivingId] = useState<number | null>(null);
  const [unarchiveError, setUnarchiveError] = useState<{
    id: number;
    message: string;
  } | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<BillTemplateOut | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<{
    id: number;
    message: string;
  } | null>(null);

  async function handleDeleteConfirm() {
    if (!deleteTarget || deleting) return;
    const id = deleteTarget.id;
    setDeleting(true);
    setDeleteError(null);
    try {
      await deleteBill(id);
      setTemplates((prev) => prev.filter((tmpl) => tmpl.id !== id));
      setDeleteTarget(null);
    } catch (err) {
      if (err instanceof SessionExpiredError) return;
      setDeleteTarget(null);
      setDeleteError({
        id,
        message: err instanceof Error ? err.message : t("deleteFailed"),
      });
    } finally {
      setDeleting(false);
    }
  }

  async function handleUnarchive(id: number) {
    if (unarchivingId !== null) return;
    setUnarchivingId(id);
    setUnarchiveError(null);
    try {
      await unarchiveBill(id);
      setTemplates((prev) => prev.filter((tmpl) => tmpl.id !== id));
    } catch (err) {
      if (err instanceof SessionExpiredError) return;
      setUnarchiveError({
        id,
        message: err instanceof Error ? err.message : t("unarchiveFailed"),
      });
    } finally {
      setUnarchivingId(null);
    }
  }

  const activeCategories = sortCategories(
    categories.filter((category) =>
      templates.some((tmpl) => tmpl.category.id === category.id),
    ),
    locale,
    tRoot,
  );

  const { collapsed, toggle, collapseAll, expandAll, allCollapsed } =
    useCollapsedCategories(
      "archived-bills-collapsed-categories",
      activeCategories.map((category) => String(category.id)),
    );

  useEffect(() => {
    let cancelled = false;
    Promise.all([fetchBills(true), fetchCategories(true)])
      .then(([billData, categoryData]) => {
        if (!cancelled) {
          setTemplates(billData.filter((bill) => bill.is_archived));
          setCategories(categoryData);
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
  }, [t]);

  return (
    <div className="mx-auto max-w-4xl px-3 py-4 sm:px-4 sm:py-8">
      <div className="mb-6">
        <h1 className="text-2xl font-semibold text-slate-800 dark:text-slate-100">
          {t("title")}
        </h1>
        <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
          {t("subtitle")}
        </p>
        {activeCategories.length > 1 && (
          <div className="mt-3 flex justify-end">
            <button
              onClick={allCollapsed ? expandAll : collapseAll}
              className="flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-500 shadow-sm transition-all hover:border-slate-300 hover:bg-slate-50 hover:text-slate-700 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-400 dark:hover:border-slate-600 dark:hover:text-slate-200"
            >
              <ChevronsUpDown size={13} />
              {allCollapsed ? t("expandAll") : t("collapseAll")}
            </button>
          </div>
        )}
      </div>

      {loading && (
        <div className="space-y-3">
          {[1, 2].map((i) => (
            <div
              key={i}
              className="h-16 rounded-xl bg-slate-200 dark:bg-slate-700 animate-pulse"
            />
          ))}
        </div>
      )}

      {loadError && (
        <div className="rounded-xl bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700 dark:bg-red-900/20 dark:border-red-800 dark:text-red-400">
          {loadError}
        </div>
      )}

      {!loading && !loadError && templates.length === 0 && (
        <div className="flex flex-col items-center justify-center rounded-2xl border-2 border-dashed border-slate-200 dark:border-slate-700 px-6 py-16 text-center">
          <div className="mb-3 rounded-full bg-slate-100 dark:bg-slate-700 p-4 text-slate-400">
            <Archive size={28} />
          </div>
          <p className="font-medium text-slate-700 dark:text-slate-300">{t("noArchivedBills")}</p>
          <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
            {t("willAppearHere")}
          </p>
        </div>
      )}

      {!loading && templates.length > 0 && (
        <div className="flex flex-col gap-6">
          {activeCategories.map((cat) => {
            const groupKey = String(cat.id);
            const group = templates
              .filter((tmpl) => tmpl.category.id === cat.id)
              .sort((a, b) => a.name.localeCompare(b.name));
            return (
              <div key={cat.id}>
                <button
                  onClick={() => toggle(groupKey)}
                  className="mb-3 flex w-full items-center gap-2.5 text-left"
                >
                  <ChevronRight
                    size={12}
                    className={`shrink-0 text-slate-400 dark:text-slate-500 transition-transform duration-150 ${
                      collapsed.has(groupKey) ? "" : "rotate-90"
                    }`}
                  />
                  <span className="text-xs font-bold uppercase tracking-widest text-slate-400 dark:text-slate-500 shrink-0">
                    {categoryLabel(cat, tRoot)}
                  </span>
                  <span className="rounded-full bg-slate-100 dark:bg-slate-700 px-1.5 py-0.5 text-xs font-semibold text-slate-400 dark:text-slate-500 shrink-0 tabular-nums">
                    {group.length}
                  </span>
                  <div className="flex-1 h-px bg-slate-100 dark:bg-slate-700/60" />
                </button>
                {!collapsed.has(groupKey) && <div className="flex flex-col gap-2">
                  {group.map((tmpl) => (
                    <div
                      key={tmpl.id}
                      data-testid={`archived-bill-${tmpl.id}`}
                      className="flex items-center gap-3 rounded-xl border border-slate-200 bg-white px-4 py-3 opacity-70 dark:bg-slate-800 dark:border-slate-700"
                    >
                      <div className="flex flex-1 flex-col min-w-0 gap-0.5">
                        <span className="font-semibold text-sm text-slate-800 dark:text-slate-100 truncate">
                          {tmpl.name}
                        </span>
                        <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
                          <span className="text-xs font-medium text-slate-600 dark:text-slate-300">
                            {tmpl.amount} {tmpl.currency}
                          </span>
                          {tmpl.preferred_account && (
                            <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-xs font-medium text-emerald-600 dark:bg-emerald-900/30 dark:text-emerald-400">
                              {bankAccountLabel(tmpl.preferred_account)}
                            </span>
                          )}
                          <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-500 dark:bg-slate-700 dark:text-slate-400">
                            {t(`frequency.${normalizeBillFrequency(tmpl.frequency)}`, {
                              count: tmpl.interval_count ?? 1,
                            })}
                          </span>
                          {normalizeBillFrequency(tmpl.frequency) !== "one_off" &&
                            tmpl.max_occurrences != null && (
                              <span className="text-xs text-slate-400 dark:text-slate-500">
                                · {tFreq("paymentCount", { count: tmpl.max_occurrences })}
                              </span>
                            )}
                        </div>
                        {unarchiveError?.id === tmpl.id && (
                          <p className="text-xs text-red-600 dark:text-red-400">
                            {unarchiveError.message}
                          </p>
                        )}
                        {deleteError?.id === tmpl.id && (
                          <p className="text-xs text-red-600 dark:text-red-400">
                            {deleteError.message}
                          </p>
                        )}
                      </div>
                      <div className="flex shrink-0 items-center gap-2">
                        <span className="rounded-full bg-slate-100 px-2.5 py-0.5 text-xs font-medium text-slate-500 dark:bg-slate-700 dark:text-slate-400">
                          {t("archived")}
                        </span>
                        <button
                          onClick={() => void handleUnarchive(tmpl.id)}
                          disabled={unarchivingId === tmpl.id}
                          aria-label={t("unarchive")}
                          className="flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 text-sm font-medium text-slate-500 shadow-sm transition-all hover:border-blue-300 hover:bg-blue-50 hover:text-blue-700 disabled:opacity-50 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-400 dark:hover:border-blue-700 dark:hover:bg-blue-900/20 dark:hover:text-blue-400"
                        >
                          {unarchivingId === tmpl.id ? (
                            <Loader2 size={15} className="animate-spin" />
                          ) : (
                            <ArchiveRestore size={15} />
                          )}
                          <span className="hidden sm:inline">{t("unarchive")}</span>
                        </button>
                        <button
                          onClick={() => setDeleteTarget(tmpl)}
                          disabled={deleting}
                          aria-label={t("delete")}
                          className="flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 text-sm font-medium text-slate-500 shadow-sm transition-all hover:border-red-300 hover:bg-red-50 hover:text-red-700 disabled:opacity-50 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-400 dark:hover:border-red-700 dark:hover:bg-red-900/20 dark:hover:text-red-400"
                        >
                          <Trash2 size={15} />
                          <span className="hidden sm:inline">{t("delete")}</span>
                        </button>
                      </div>
                    </div>
                  ))}
                </div>}
              </div>
            );
          })}
        </div>
      )}

      {deleteTarget && (
        <DeleteBillDialog
          billName={deleteTarget.name}
          deleting={deleting}
          onConfirm={() => void handleDeleteConfirm()}
          onCancel={() => setDeleteTarget(null)}
        />
      )}
    </div>
  );
}

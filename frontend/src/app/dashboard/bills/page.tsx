"use client";

import { useEffect, useRef, useState } from "react";
import {
  CalendarClock,
  CalendarPlus,
  ChevronRight,
  ChevronsUpDown,
  FolderTree,
  Loader2,
  Plus,
  Search,
  Upload,
  X,
} from "lucide-react";
import { useRouter } from "next/navigation";
import { useLocale, useTranslations } from "next-intl";
import {
  fetchBills,
  createBill,
  updateBill,
  archiveBill,
  hasDeletedFuture,
  type BillTemplateOut,
  type BillTemplateCreate,
  type BillTemplateUpdate,
} from "@/lib/bills-api";
import { fetchCategories, categoryLabel, type Category } from "@/lib/categories-api";
import { fetchBankAccounts, type BankAccount } from "@/lib/bank-accounts-api";
import { categoryColor, categoryValue, sortCategories } from "@/lib/categories";
import { fetchMe, type UserProfile } from "@/lib/user-api";
import { SessionExpiredError } from "@/lib/api";
import BillTemplateForm from "@/components/bills/BillTemplateForm";
import ReviewInbox from "@/components/payments/ReviewInbox";
import { uploadBill } from "@/lib/imports-api";
import BillTemplateRow from "@/components/bills/BillTemplateRow";
import ArchiveConfirmDialog from "@/components/bills/ArchiveConfirmDialog";
import RestoreDeletedDialog from "@/components/bills/RestoreDeletedDialog";
import GenerateInstancesDialog from "@/components/bills/GenerateInstancesDialog";
import { useCollapsedCategories } from "@/hooks/useCollapsedCategories";

type BillStateFilter = "all" | "active" | "paused";

function uniqueCategories(categories: Category[]): Category[] {
  const byId = new Map<number, Category>();
  for (const category of categories) byId.set(category.id, category);
  return [...byId.values()];
}

const filterLabelClass =
  "mb-1 block text-xs font-semibold uppercase tracking-wide text-slate-400 dark:text-slate-500";
const filterSelectClass =
  "w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-800 outline-none transition-all focus:border-blue-500 focus:ring-2 focus:ring-blue-100 dark:border-slate-600 dark:bg-slate-700 dark:text-slate-100 dark:focus:border-blue-600 dark:focus:ring-blue-900/40";

export default function BillsPage() {
  const t = useTranslations("BillsPage");
  const tRoot = useTranslations();
  const locale = useLocale();
  const [templates, setTemplates] = useState<BillTemplateOut[]>([]);
  const [categories, setCategories] = useState<Category[]>([]);
  const [bankAccounts, setBankAccounts] = useState<BankAccount[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [expandedId, setExpandedId] = useState<number | "new" | null>(null);
  const [archiveTarget, setArchiveTarget] = useState<BillTemplateOut | null>(null);
  const [archiving, setArchiving] = useState(false);
  const [deletedFutureMap, setDeletedFutureMap] = useState<Record<number, boolean>>({});
  const [restoreTarget, setRestoreTarget] = useState<{ id: number; name: string; data: BillTemplateUpdate } | null>(null);
  const [restoring, setRestoring] = useState(false);
  const [profile, setProfile] = useState<UserProfile | null>(null);
  const [generateOpen, setGenerateOpen] = useState(false);
  const [categoryFilter, setCategoryFilter] = useState<string>("all");
  const [stateFilter, setStateFilter] = useState<BillStateFilter>("all");
  const [searchFilter, setSearchFilter] = useState("");
  const [view, setView] = useState<"due" | "category">("due");
  const [importRefresh, setImportRefresh] = useState(0);
  const [importBusy, setImportBusy] = useState(false);
  const [importError, setImportError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const router = useRouter();

  const sortedCategories = sortCategories(categories, locale, tRoot);
  const activeCategories = sortCategories(
    uniqueCategories(templates.map((tmpl) => tmpl.category)),
    locale,
    tRoot,
  );
  const pickerCategories = sortedCategories.filter((category) => !category.is_archived);
  const colorIndexById = new Map(sortedCategories.map((category, index) => [category.id, index]));

  const { collapsed, toggle, collapseAll, expandAll, allCollapsed } =
    useCollapsedCategories(
      "bills-collapsed-categories",
      activeCategories.map((category) => String(category.id)),
    );

  useEffect(() => {
    let cancelled = false;
    Promise.all([fetchBills(), fetchCategories(true), fetchBankAccounts()])
      .then(([billData, categoryData, accountData]) => {
        if (!cancelled) {
          setTemplates(billData);
          setCategories(categoryData);
          setBankAccounts(accountData);
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

  useEffect(() => {
    const stored = localStorage.getItem("bills-view");
    if (stored === "category" || stored === "due") {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- one-shot post-hydration read of a browser-only preference
      setView(stored);
    }
  }, []);

  async function handleImportUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    setImportBusy(true);
    setImportError(null);
    try {
      await uploadBill(file);
      setImportRefresh((token) => token + 1);
    } catch (err) {
      setImportError(err instanceof Error ? err.message : t("importFailed"));
    } finally {
      setImportBusy(false);
    }
  }

  function changeView(next: "due" | "category") {
    setView(next);
    localStorage.setItem("bills-view", next);
  }

  useEffect(() => {
    let cancelled = false;
    fetchMe()
      .then((data) => {
        if (!cancelled) setProfile(data);
      })
      .catch(() => {
        // Profile fetch failure is non-fatal — the form falls back to locale defaults.
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const searchQuery = searchFilter.trim().toLowerCase();
  const hasActiveFilters =
    categoryFilter !== "all" || stateFilter !== "all" || searchQuery !== "";

  const filteredTemplates = templates.filter((tmpl) => {
    if (categoryFilter !== "all" && categoryValue(tmpl.category) !== categoryFilter) return false;
    if (stateFilter === "active" && tmpl.is_paused) return false;
    if (stateFilter === "paused" && !tmpl.is_paused) return false;
    if (searchQuery && !tmpl.name.toLowerCase().includes(searchQuery)) return false;
    return true;
  });

  function clearFilters() {
    setCategoryFilter("all");
    setStateFilter("all");
    setSearchFilter("");
  }

  function handleCategoryCreated(category: Category) {
    setCategories((prev) =>
      prev.some((existing) => existing.id === category.id) ? prev : [...prev, category],
    );
  }

  async function handleCreate(data: BillTemplateCreate) {
    await createBill(data);
    setExpandedId(null);
    setRefreshKey((k) => k + 1);
  }

  async function doUpdate(id: number, data: BillTemplateUpdate) {
    await updateBill(id, data);
    setExpandedId(null);
    setRefreshKey((k) => k + 1);
    setDeletedFutureMap((m) => { const copy = { ...m }; delete copy[id]; return copy; });
  }

  async function handleUpdate(id: number, data: BillTemplateUpdate) {
    if (deletedFutureMap[id]) {
      const name = templates.find((t) => t.id === id)?.name ?? "";
      setRestoreTarget({ id, name, data });
      return;
    }
    await doUpdate(id, data);
  }

  async function handleRestoreConfirm() {
    if (!restoreTarget || restoring) return;
    setRestoring(true);
    try {
      await doUpdate(restoreTarget.id, { ...restoreTarget.data, recreate_deleted_future: true });
      setRestoreTarget(null);
    } finally {
      setRestoring(false);
    }
  }

  async function handleRestoreSkip() {
    if (!restoreTarget) return;
    const { id, data } = restoreTarget;
    try {
      await doUpdate(id, data);
      setRestoreTarget(null);
    } catch {
      // leave dialog open so user can retry
    }
  }

  async function handleArchiveConfirm() {
    if (!archiveTarget || archiving) return;
    setArchiving(true);
    try {
      await archiveBill(archiveTarget.id);
      setArchiveTarget(null);
      setRefreshKey((k) => k + 1);
    } finally {
      setArchiving(false);
    }
  }

  function toggleExpand(id: number | "new") {
    setExpandedId((prev) => {
      const opening = prev !== id;
      if (opening && typeof id === "number") {
        hasDeletedFuture(id)
          .then((res) => setDeletedFutureMap((m) => ({ ...m, [id]: res.has_deleted_future })))
          .catch(() => {/* fail silently — no tombstone prompt this session */});
      }
      return opening ? id : null;
    });
  }

  if (loading) {
    return (
      <div className="mx-auto max-w-4xl px-4 py-8">
        <div className="space-y-3">
          {[1, 2, 3].map((i) => (
            <div
              key={i}
              className="h-16 rounded-xl bg-slate-200 dark:bg-slate-700 animate-pulse"
            />
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-4xl px-4 py-8">
      {archiveTarget && (
        <ArchiveConfirmDialog
          billName={archiveTarget.name}
          onConfirm={handleArchiveConfirm}
          onCancel={() => setArchiveTarget(null)}
          archiving={archiving}
        />
      )}

      {restoreTarget && (
        <RestoreDeletedDialog
          billName={restoreTarget.name}
          onRestore={handleRestoreConfirm}
          onSkip={handleRestoreSkip}
          restoring={restoring}
        />
      )}

      {generateOpen && (
        <GenerateInstancesDialog
          templates={templates}
          onClose={() => setGenerateOpen(false)}
          onGenerated={() => setRefreshKey((k) => k + 1)}
        />
      )}

      <ReviewInbox
        refreshToken={importRefresh}
        onApplied={() => setRefreshKey((key) => key + 1)}
        onJumpToMonth={(month) => router.push(`/dashboard/payments?month=${month}`)}
      />

      {importError && (
        <p className="mb-4 rounded-xl bg-red-50 px-3 py-2 text-sm text-red-600 dark:bg-red-900/20 dark:text-red-400">
          {importError}
        </p>
      )}

      {/* Page header */}
      <div className="mb-6">
        <h1 className="text-2xl font-semibold text-slate-800 dark:text-slate-100">
          {t("title")}
        </h1>
        <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
          {t("subtitle")}
        </p>
        <div className="mt-3 flex items-center justify-between gap-2">
          <div className="flex flex-wrap items-center gap-2">
            <button
              onClick={() => toggleExpand("new")}
              className="flex items-center gap-2 rounded-xl border border-blue-700 bg-blue-700 px-4 py-2 text-sm font-medium text-white shadow-sm transition-all hover:border-blue-800 hover:bg-blue-800 active:bg-blue-900"
            >
              <Plus size={16} />
              {expandedId === "new" ? t("cancel") : t("newBill")}
            </button>
            <button
              onClick={() => setGenerateOpen(true)}
              className="flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-4 py-2 text-sm font-medium text-slate-600 shadow-sm transition-all hover:border-blue-300 hover:bg-blue-50 hover:text-blue-700 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-400 dark:hover:border-blue-700 dark:hover:bg-blue-900/20 dark:hover:text-blue-400"
            >
              <CalendarPlus size={16} />
              {t("generatePayments")}
            </button>
            <button
              onClick={() => fileInputRef.current?.click()}
              disabled={importBusy}
              className="flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-4 py-2 text-sm font-medium text-slate-600 shadow-sm transition-all hover:border-blue-300 hover:bg-blue-50 hover:text-blue-700 disabled:cursor-not-allowed disabled:opacity-50 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-400 dark:hover:border-blue-700 dark:hover:bg-blue-900/20 dark:hover:text-blue-400"
            >
              {importBusy ? (
                <Loader2 size={16} className="animate-spin" />
              ) : (
                <Upload size={16} />
              )}
              {t("importBill")}
            </button>
            <input
              ref={fileInputRef}
              type="file"
              accept=".pdf,application/pdf,image/png,image/jpeg"
              className="hidden"
              onChange={handleImportUpload}
            />
          </div>
          <div className="flex items-center gap-2">
            {view === "category" && activeCategories.length > 1 && (
              <button
                onClick={allCollapsed ? expandAll : collapseAll}
                className="flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-500 shadow-sm transition-all hover:border-slate-300 hover:bg-slate-50 hover:text-slate-700 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-400 dark:hover:border-slate-600 dark:hover:text-slate-200"
              >
                <ChevronsUpDown size={13} />
                {allCollapsed ? t("expandAll") : t("collapseAll")}
              </button>
            )}
            <div className="flex rounded-xl border border-slate-200 bg-white p-0.5 shadow-sm dark:border-slate-700 dark:bg-slate-800">
              <button
                type="button"
                aria-pressed={view === "due"}
                onClick={() => changeView("due")}
                className={`flex items-center gap-1.5 rounded-[10px] px-3 py-1.5 text-xs font-medium transition-colors ${
                  view === "due"
                    ? "bg-blue-700 text-white shadow-sm"
                    : "text-slate-500 hover:text-slate-700 dark:text-slate-400 dark:hover:text-slate-200"
                }`}
              >
                <CalendarClock size={13} />
                {t("viewDue")}
              </button>
              <button
                type="button"
                aria-pressed={view === "category"}
                onClick={() => changeView("category")}
                className={`flex items-center gap-1.5 rounded-[10px] px-3 py-1.5 text-xs font-medium transition-colors ${
                  view === "category"
                    ? "bg-blue-700 text-white shadow-sm"
                    : "text-slate-500 hover:text-slate-700 dark:text-slate-400 dark:hover:text-slate-200"
                }`}
              >
                <FolderTree size={13} />
                {t("viewCategory")}
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* Filters */}
      {templates.length > 0 && (
        <div
          data-testid="bill-filters"
          className="mb-4 rounded-xl border border-slate-200 bg-white p-3 shadow-sm dark:border-slate-700 dark:bg-slate-800"
        >
          <div className="grid gap-3 sm:grid-cols-3">
            <div>
              <label htmlFor="bill-filter-category" className={filterLabelClass}>
                {t("filterCategory")}
              </label>
              <select
                id="bill-filter-category"
                value={categoryFilter}
                onChange={(e) => setCategoryFilter(e.target.value)}
                className={filterSelectClass}
              >
                <option value="all">{t("filterAllCategories")}</option>
                {activeCategories.map((cat) => (
                  <option key={cat.id} value={categoryValue(cat)}>
                    {categoryLabel(cat, tRoot)}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label htmlFor="bill-filter-state" className={filterLabelClass}>
                {t("filterState")}
              </label>
              <select
                id="bill-filter-state"
                value={stateFilter}
                onChange={(e) => setStateFilter(e.target.value as BillStateFilter)}
                className={filterSelectClass}
              >
                <option value="all">{t("filterAllStates")}</option>
                <option value="active">{t("filterActive")}</option>
                <option value="paused">{t("filterPaused")}</option>
              </select>
            </div>
            <div>
              <label htmlFor="bill-filter-search" className={filterLabelClass}>
                {t("filterName")}
              </label>
              <div className="relative">
                <Search
                  size={14}
                  className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400 dark:text-slate-500"
                />
                <input
                  id="bill-filter-search"
                  type="search"
                  value={searchFilter}
                  onChange={(e) => setSearchFilter(e.target.value)}
                  placeholder={t("searchPlaceholder")}
                  className={filterSelectClass + " pl-8"}
                />
              </div>
            </div>
          </div>
          {hasActiveFilters && (
            <div className="mt-3 flex justify-end">
              <button
                onClick={clearFilters}
                className="flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-500 shadow-sm transition-all hover:border-slate-300 hover:bg-slate-50 hover:text-slate-700 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-400 dark:hover:border-slate-600 dark:hover:text-slate-200"
              >
                <X size={13} />
                {t("clearFilters")}
              </button>
            </div>
          )}
        </div>
      )}

      {loadError && (
        <div className="mb-4 rounded-xl bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700 dark:bg-red-900/20 dark:border-red-800 dark:text-red-400">
          {loadError}
        </div>
      )}

      {/* Inline create form */}
      {expandedId === "new" && (
        <div className="mb-4 overflow-hidden rounded-xl border border-blue-200 bg-white shadow-sm dark:border-blue-900 dark:bg-slate-800">
          <div className="border-b border-blue-100 bg-blue-50 px-5 py-3 dark:border-blue-900 dark:bg-blue-900/20">
            <h2 className="text-sm font-semibold text-blue-800 dark:text-blue-300">{t("newBill")}</h2>
          </div>
          <div className="p-5">
            <BillTemplateForm
              defaultCurrency={profile?.default_currency ?? undefined}
              categories={pickerCategories}
              onCategoryCreated={handleCategoryCreated}
              bankAccounts={bankAccounts}
              onSave={handleCreate}
              onCancel={() => setExpandedId(null)}
            />
          </div>
        </div>
      )}

      {/* No matches */}
      {templates.length > 0 && filteredTemplates.length === 0 && (
        <div
          data-testid="bill-no-matches"
          className="flex flex-col items-center justify-center rounded-2xl border-2 border-dashed border-slate-200 dark:border-slate-700 px-6 py-12 text-center"
        >
          <p className="font-medium text-slate-700 dark:text-slate-300">{t("noMatches")}</p>
          <button
            onClick={clearFilters}
            className="mt-3 flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-sm font-medium text-slate-600 shadow-sm transition-all hover:border-slate-300 hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-300 dark:hover:bg-slate-700"
          >
            <X size={14} />
            {t("clearFilters")}
          </button>
        </div>
      )}

      {/* Template list */}
      {templates.length === 0 && expandedId !== "new" ? (
        <div className="flex flex-col items-center justify-center rounded-2xl border-2 border-dashed border-slate-200 dark:border-slate-700 px-6 py-16 text-center">
          <div className="mb-3 rounded-full bg-blue-100 dark:bg-blue-900/30 p-4 text-blue-700">
            <Plus size={28} />
          </div>
          <p className="font-medium text-slate-700 dark:text-slate-300">{t("noBillsYet")}</p>
          <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
            {t("addFirstBill")}
          </p>
          <button
            onClick={() => toggleExpand("new")}
            className="mt-4 rounded-xl border border-blue-700 bg-blue-700 px-5 py-2 text-sm font-medium text-white shadow-sm transition-all hover:border-blue-800 hover:bg-blue-800"
          >
            {t("addFirstBill")}
          </button>
        </div>
      ) : filteredTemplates.length > 0 && view === "due" ? (
        <div className="flex flex-col gap-2" data-testid="bills-next-due">
          {[...filteredTemplates]
            .sort((a, b) => {
              if (a.next_due_date && b.next_due_date) {
                return (
                  a.next_due_date.localeCompare(b.next_due_date) ||
                  a.name.localeCompare(b.name)
                );
              }
              if (a.next_due_date) return -1;
              if (b.next_due_date) return 1;
              return a.name.localeCompare(b.name);
            })
            .map((tmpl) => (
              <BillTemplateRow
                key={tmpl.id}
                template={tmpl}
                isExpanded={expandedId === tmpl.id}
                categories={pickerCategories}
                onCategoryCreated={handleCategoryCreated}
                bankAccounts={bankAccounts}
                colorClass={categoryColor(colorIndexById.get(tmpl.category.id) ?? 0)}
                onEditToggle={() => toggleExpand(tmpl.id)}
                onSave={(data) => handleUpdate(tmpl.id, data)}
                onArchive={() => setArchiveTarget(tmpl)}
                nextDue={
                  tmpl.next_due_date
                    ? {
                        date: tmpl.next_due_date,
                        amount: tmpl.next_due_amount ?? tmpl.amount,
                      }
                    : null
                }
              />
            ))}
        </div>
      ) : filteredTemplates.length > 0 ? (
        <div className="flex flex-col gap-6">
          {activeCategories
            .filter((cat) => filteredTemplates.some((tmpl) => tmpl.category.id === cat.id))
            .map((cat) => {
              const groupKey = String(cat.id);
              const group = filteredTemplates
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
                  {!collapsed.has(groupKey) && (
                    <div className="flex flex-col gap-2">
                      {group.map((tmpl) => (
                        <BillTemplateRow
                          key={tmpl.id}
                          template={tmpl}
                          isExpanded={expandedId === tmpl.id}
                          categories={pickerCategories}
                          onCategoryCreated={handleCategoryCreated}
                          bankAccounts={bankAccounts}
                          colorClass={categoryColor(colorIndexById.get(cat.id) ?? 0)}
                          onEditToggle={() => toggleExpand(tmpl.id)}
                          onSave={(data) => handleUpdate(tmpl.id, data)}
                          onArchive={() => setArchiveTarget(tmpl)}
                        />
                      ))}
                    </div>
                  )}
                </div>
              );
            })}
        </div>
      ) : null}
    </div>
  );
}

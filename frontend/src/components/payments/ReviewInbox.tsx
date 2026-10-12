"use client";

import { useEffect, useMemo, useState, type ReactNode } from "react";
import { Check, Inbox, Loader2, Plus, Trash2, X } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import {
  confirmImportDraft,
  discardImportDraft,
  fetchImportDrafts,
  updateImportDraft,
  type ImportDraftOut,
} from "@/lib/imports-api";
import {
  confirmInstanceAmount,
  fetchNeedsConfirmation,
  type PendingConfirmationOut,
} from "@/lib/payments-api";
import { createBill, fetchBills, type BillTemplateOut } from "@/lib/bills-api";
import { fetchCategories, type Category } from "@/lib/categories-api";
import { fetchMe } from "@/lib/user-api";
import { createAmountFormatter } from "@/lib/payment-totals";

interface Props {
  refreshToken: number;
  onApplied: () => void;
  onJumpToMonth: (month: string) => void;
}

function monthLabel(period: string, locale: string): string {
  const [year, month] = period.split("-").map(Number);
  const label = new Intl.DateTimeFormat(locale, {
    month: "long",
    year: "numeric",
  }).format(new Date(year, month - 1));
  return label.charAt(0).toUpperCase() + label.slice(1);
}

export default function ReviewInbox({ refreshToken, onApplied, onJumpToMonth }: Props) {
  const t = useTranslations("ReviewInbox");
  const locale = useLocale();

  const [estimates, setEstimates] = useState<PendingConfirmationOut[]>([]);
  const [imports, setImports] = useState<ImportDraftOut[]>([]);
  const [bills, setBills] = useState<BillTemplateOut[]>([]);
  const [categories, setCategories] = useState<Category[]>([]);
  const [defaultCurrency, setDefaultCurrency] = useState<string | null>(null);
  const [result, setResult] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [reload, setReload] = useState(0);

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      fetchNeedsConfirmation(),
      fetchImportDrafts(),
      fetchBills(),
      fetchCategories(),
      fetchMe().catch(() => null),
    ])
      .then(([estimateData, importData, billData, categoryData, profile]) => {
        if (cancelled) return;
        setEstimates(estimateData);
        setImports(importData);
        setBills(billData);
        setCategories(categoryData.filter((category) => !category.is_archived));
        setDefaultCurrency(profile?.default_currency ?? null);
        setError(null);
      })
      .catch(() => {
        if (!cancelled) setError(t("loadFailed"));
      });
    return () => {
      cancelled = true;
    };
  }, [refreshToken, reload, t]);

  const total = estimates.length + imports.length;
  const defaultCategoryId = useMemo(() => {
    const preferred = categories.find((category) => category.key === "utilities");
    return (preferred ?? categories[0])?.id ?? null;
  }, [categories]);

  function finish(period: string | null, applied: () => void) {
    applied();
    onApplied();
    // An import can resolve an estimate (same period); refetch both lists so
    // the inbox reflects what is actually left to review.
    setReload((token) => token + 1);
    if (period) setResult(period);
  }

  if (total === 0 && !result && !error) return null;

  return (
    <div
      data-testid="review-inbox"
      className="mb-6 rounded-2xl border border-blue-200 bg-blue-50/60 p-4 dark:border-blue-900/60 dark:bg-blue-900/10"
    >
      <div className="mb-3 flex items-center gap-2">
        <Inbox size={16} className="text-blue-600 dark:text-blue-400" />
        <h2 className="text-sm font-semibold text-blue-800 dark:text-blue-300">
          {t("title", { count: total })}
        </h2>
      </div>

      {error && (
        <p className="mb-3 rounded-xl bg-red-50 px-3 py-2 text-xs text-red-600 dark:bg-red-900/20 dark:text-red-400">
          {error}
        </p>
      )}

      {result && (
        <div className="mb-3 flex items-center justify-between gap-3 rounded-xl bg-blue-100 px-3 py-2 text-xs text-blue-800 dark:bg-blue-900/40 dark:text-blue-300">
          <span>{t("addedTo", { period: monthLabel(result, locale) })}</span>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => onJumpToMonth(result)}
              className="font-medium underline underline-offset-2"
            >
              {t("viewMonth")}
            </button>
            <button
              type="button"
              aria-label={t("dismiss")}
              onClick={() => setResult(null)}
              className="text-blue-600/70 hover:text-blue-800 dark:text-blue-400/70 dark:hover:text-blue-300"
            >
              <X size={13} />
            </button>
          </div>
        </div>
      )}

      <ul className="flex flex-col gap-2">
        {imports.map((draft) => (
          <ImportRow
            key={`import-${draft.id}`}
            draft={draft}
            bills={bills}
            categories={categories}
            defaultCategoryId={defaultCategoryId}
            defaultCurrency={defaultCurrency}
            busy={busyId === `import-${draft.id}`}
            onBusy={(busy) => setBusyId(busy ? `import-${draft.id}` : null)}
            onError={setError}
            onDone={(period) =>
              finish(period, () =>
                setImports((prev) => prev.filter((item) => item.id !== draft.id)),
              )
            }
          />
        ))}
        {estimates.map((estimate) => (
          <EstimateRow
            key={`estimate-${estimate.id}`}
            estimate={estimate}
            busy={busyId === `estimate-${estimate.id}`}
            onBusy={(busy) => setBusyId(busy ? `estimate-${estimate.id}` : null)}
            onError={setError}
            onDone={() =>
              finish(estimate.period, () =>
                setEstimates((prev) => prev.filter((item) => item.id !== estimate.id)),
              )
            }
          />
        ))}
      </ul>
    </div>
  );
}

function Badge({ children, tone }: { children: ReactNode; tone: "amber" | "blue" }) {
  const classes =
    tone === "amber"
      ? "bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400"
      : "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400";
  return (
    <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${classes}`}>
      {children}
    </span>
  );
}

function EstimateRow({
  estimate,
  busy,
  onBusy,
  onError,
  onDone,
}: {
  estimate: PendingConfirmationOut;
  busy: boolean;
  onBusy: (busy: boolean) => void;
  onError: (message: string) => void;
  onDone: () => void;
}) {
  const t = useTranslations("ReviewInbox");
  const locale = useLocale();
  const formatAmount = createAmountFormatter(locale);
  const [amount, setAmount] = useState(estimate.amount);
  const amountValid = Number.isFinite(parseFloat(amount)) && parseFloat(amount) > 0;

  async function handleConfirm() {
    if (!amountValid) {
      onError(t("amountInvalid"));
      return;
    }
    onBusy(true);
    try {
      await confirmInstanceAmount(estimate.id, parseFloat(amount).toFixed(2));
      onDone();
    } catch (err) {
      onError(err instanceof Error ? err.message : t("confirmFailed"));
    } finally {
      onBusy(false);
    }
  }

  return (
    <li className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-amber-200/70 bg-white px-3 py-2 dark:border-amber-900/40 dark:bg-slate-800">
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          <p className="truncate text-sm font-medium text-slate-800 dark:text-slate-100">
            {estimate.bill_name}
          </p>
          <Badge tone="amber">{t("estimateBadge")}</Badge>
        </div>
        <p className="text-xs text-slate-500 dark:text-slate-400">
          {monthLabel(estimate.period, locale)}
          {estimate.basis_amounts.length > 0
            ? ` · ${t("basis", {
                amounts: estimate.basis_amounts
                  .map((value) => formatAmount.format(parseFloat(value)))
                  .join(" · "),
              })}`
            : ""}
        </p>
      </div>
      <div className="flex items-center gap-2">
        <div className="flex items-center gap-1.5 rounded-lg border border-slate-200 bg-slate-50 px-2 py-1.5 dark:border-slate-600 dark:bg-slate-900/40">
          <input
            aria-label={t("amountLabel")}
            type="number"
            step="0.01"
            min="0.01"
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
            className="w-24 bg-transparent text-right text-sm text-slate-800 outline-none dark:text-slate-100"
          />
          <span className="text-xs text-slate-400 dark:text-slate-500">
            {estimate.currency}
          </span>
        </div>
        <button
          type="button"
          onClick={handleConfirm}
          disabled={busy || !amountValid}
          className="flex items-center gap-1 rounded-lg border border-blue-700 bg-blue-700 px-2.5 py-1.5 text-xs font-medium text-white shadow-sm transition-all hover:border-blue-800 hover:bg-blue-800 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {busy ? <Loader2 size={12} className="animate-spin" /> : <Check size={12} />}
          {t("confirm")}
        </button>
      </div>
    </li>
  );
}

function ImportRow({
  draft,
  bills,
  categories,
  defaultCategoryId,
  defaultCurrency,
  busy,
  onBusy,
  onError,
  onDone,
}: {
  draft: ImportDraftOut;
  bills: BillTemplateOut[];
  categories: Category[];
  defaultCategoryId: number | null;
  defaultCurrency: string | null;
  busy: boolean;
  onBusy: (busy: boolean) => void;
  onError: (message: string) => void;
  onDone: (period: string | null) => void;
}) {
  const t = useTranslations("ReviewInbox");
  const locale = useLocale();
  const [amount, setAmount] = useState(draft.amount ?? "");
  const [dueDate, setDueDate] = useState(draft.due_date ?? "");
  const [billId, setBillId] = useState<string>(
    draft.matched_bill_id != null ? String(draft.matched_bill_id) : "",
  );
  const [creating, setCreating] = useState(draft.matched_bill_id === null);
  const [frequency, setFrequency] = useState<
    "monthly" | "weekly" | "annual" | "one_off"
  >("monthly");
  const [newName, setNewName] = useState(draft.provider ?? draft.filename ?? "");
  const [newCategoryId, setNewCategoryId] = useState<string>(
    defaultCategoryId != null ? String(defaultCategoryId) : "",
  );
  const [newDueDay, setNewDueDay] = useState<string>(
    draft.due_date ? String(parseInt(draft.due_date.slice(8, 10), 10)) : "",
  );

  const amountValid = Number.isFinite(parseFloat(amount)) && parseFloat(amount) > 0;
  const weeklyAnchorOk = frequency !== "weekly" || dueDate !== "";
  const canConfirm = creating
    ? newName.trim().length > 0 && newCategoryId !== "" && amountValid && weeklyAnchorOk
    : billId !== "" && amountValid;

  async function handleConfirm() {
    if (!canConfirm) return;
    onBusy(true);
    onError("");
    try {
      let targetBillId = billId === "" ? null : Number(billId);
      if (creating) {
        const dueDay = newDueDay === "" ? null : parseInt(newDueDay, 10);
        const dueMonth = dueDate ? parseInt(dueDate.slice(5, 7), 10) : null;
        const created = await createBill({
          name: newName.trim(),
          category_id: Number(newCategoryId),
          frequency,
          amount: parseFloat(amount).toFixed(2),
          currency: draft.currency ?? defaultCurrency ?? undefined,
          due_day: frequency === "weekly" ? null : dueDay,
          due_month:
            frequency === "annual" || frequency === "one_off" ? dueMonth : null,
          start_date: frequency === "weekly" ? dueDate || null : null,
        });
        targetBillId = created.id;
      } else {
        await updateImportDraft(draft.id, {
          amount: parseFloat(amount).toFixed(2),
          due_date: dueDate || null,
          matched_bill_id: targetBillId,
        });
      }
      await confirmImportDraft(draft.id, targetBillId);
      const period = draft.period ?? (dueDate ? dueDate.slice(0, 7) : null);
      onDone(period);
    } catch (err) {
      onError(err instanceof Error ? err.message : t("confirmFailed"));
    } finally {
      onBusy(false);
    }
  }

  async function handleDiscard() {
    onBusy(true);
    try {
      await discardImportDraft(draft.id);
      onDone(null);
    } catch (err) {
      onError(err instanceof Error ? err.message : t("discardFailed"));
    } finally {
      onBusy(false);
    }
  }

  return (
    <li className="rounded-xl border border-blue-200/70 bg-white px-3 py-2 dark:border-blue-900/40 dark:bg-slate-800">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <p className="truncate text-sm font-medium text-slate-800 dark:text-slate-100">
              {draft.provider ?? draft.filename ?? t("unknownSource")}
            </p>
            <Badge tone="blue">{t("importBadge")}</Badge>
            <span className="text-xs text-slate-400 dark:text-slate-500">
              {t(`source.${draft.source}`)}
            </span>
          </div>
          {draft.period && (
            <p className="text-xs text-slate-500 dark:text-slate-400">
              {monthLabel(draft.period, locale)}
            </p>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <div className="flex items-center gap-1.5 rounded-lg border border-slate-200 bg-slate-50 px-2 py-1.5 dark:border-slate-600 dark:bg-slate-900/40">
            <input
              aria-label={t("amountLabel")}
              type="number"
              step="0.01"
              min="0.01"
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              className="w-24 bg-transparent text-right text-sm text-slate-800 outline-none dark:text-slate-100"
            />
            <span className="text-xs text-slate-400 dark:text-slate-500">
              {draft.currency ?? defaultCurrency ?? ""}
            </span>
          </div>
          <input
            aria-label={t("dueLabel")}
            type="date"
            value={dueDate}
            onChange={(e) => setDueDate(e.target.value)}
            className="rounded-lg border border-slate-200 bg-slate-50 px-2 py-1.5 text-xs text-slate-700 outline-none focus:border-blue-500 dark:border-slate-600 dark:bg-slate-900/40 dark:text-slate-200"
          />
          {!creating && (
            <select
              aria-label={t("billLabel")}
              value={billId}
              onChange={(e) => {
                if (e.target.value === "__new__") {
                  setCreating(true);
                  return;
                }
                setBillId(e.target.value);
              }}
              className="max-w-44 rounded-lg border border-slate-200 bg-white px-2 py-1.5 text-xs text-slate-700 outline-none focus:border-blue-500 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-200"
            >
              <option value="">{t("pickBill")}</option>
              {bills.map((bill) => (
                <option key={bill.id} value={bill.id}>
                  {bill.name}
                </option>
              ))}
              <option value="__new__">{t("newBillOption")}</option>
            </select>
          )}
          <button
            type="button"
            onClick={handleConfirm}
            disabled={busy || !canConfirm}
            className="flex items-center gap-1 rounded-lg border border-blue-700 bg-blue-700 px-2.5 py-1.5 text-xs font-medium text-white shadow-sm transition-all hover:border-blue-800 hover:bg-blue-800 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {busy ? <Loader2 size={12} className="animate-spin" /> : <Check size={12} />}
            {t("confirm")}
          </button>
          <button
            type="button"
            onClick={handleDiscard}
            disabled={busy}
            aria-label={t("discard")}
            className="rounded-lg border border-slate-200 bg-white p-1.5 text-slate-400 shadow-sm transition-all hover:border-red-300 hover:bg-red-50 hover:text-red-600 disabled:opacity-50 dark:border-slate-600 dark:bg-slate-800 dark:hover:border-red-800 dark:hover:bg-red-900/20 dark:hover:text-red-400"
          >
            <Trash2 size={13} />
          </button>
        </div>
      </div>

      {creating && (
        <div className="mt-3 flex flex-wrap items-end gap-2 rounded-lg bg-slate-50 p-2.5 dark:bg-slate-900/40">
          <div className="flex flex-col gap-1">
            <label htmlFor={`new-name-${draft.id}`} className="text-xs text-slate-500 dark:text-slate-400">
              {t("newBillName")}
            </label>
            <input
              id={`new-name-${draft.id}`}
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              className="rounded-lg border border-slate-200 bg-white px-2 py-1.5 text-sm text-slate-800 outline-none focus:border-blue-500 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-100"
            />
          </div>
          <div className="flex flex-col gap-1">
            <label htmlFor={`new-cat-${draft.id}`} className="text-xs text-slate-500 dark:text-slate-400">
              {t("newBillCategory")}
            </label>
            <select
              id={`new-cat-${draft.id}`}
              value={newCategoryId}
              onChange={(e) => setNewCategoryId(e.target.value)}
              className="rounded-lg border border-slate-200 bg-white px-2 py-1.5 text-sm text-slate-700 outline-none focus:border-blue-500 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-200"
            >
              {categories.map((category) => (
                <option key={category.id} value={category.id}>
                  {category.name ?? category.key}
                </option>
              ))}
            </select>
          </div>
          <div className="flex flex-col gap-1">
            <label htmlFor={`new-freq-${draft.id}`} className="text-xs text-slate-500 dark:text-slate-400">
              {t("newBillFrequency")}
            </label>
            <select
              id={`new-freq-${draft.id}`}
              value={frequency}
              onChange={(e) =>
                setFrequency(
                  e.target.value as "monthly" | "weekly" | "annual" | "one_off",
                )
              }
              className="rounded-lg border border-slate-200 bg-white px-2 py-1.5 text-sm text-slate-700 outline-none focus:border-blue-500 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-200"
            >
              <option value="monthly">{t("frequency.monthly")}</option>
              <option value="weekly">{t("frequency.weekly")}</option>
              <option value="annual">{t("frequency.annual")}</option>
              <option value="one_off">{t("frequency.one_off")}</option>
            </select>
          </div>
          {frequency !== "weekly" && (
            <div className="flex flex-col gap-1">
              <label htmlFor={`new-day-${draft.id}`} className="text-xs text-slate-500 dark:text-slate-400">
                {t("newBillDueDay")}
              </label>
              <input
                id={`new-day-${draft.id}`}
                type="number"
                min="1"
                max="31"
                value={newDueDay}
                onChange={(e) => setNewDueDay(e.target.value)}
                className="w-20 rounded-lg border border-slate-200 bg-white px-2 py-1.5 text-sm text-slate-800 outline-none focus:border-blue-500 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-100"
              />
            </div>
          )}
          <p className="flex items-center gap-1 text-xs text-slate-400 dark:text-slate-500">
            <Plus size={12} />
            {t("newBillHint")}
          </p>
        </div>
      )}
    </li>
  );
}

"use client";

import { useCallback, useEffect, useState } from "react";
import { FileSearch, Loader2, Trash2, Check } from "lucide-react";
import { useTranslations, useLocale } from "next-intl";
import {
  confirmImportDraft,
  discardImportDraft,
  fetchImportDrafts,
  updateImportDraft,
  type ImportDraftOut,
} from "@/lib/imports-api";
import { fetchBills, type BillTemplateOut } from "@/lib/bills-api";
import { createAmountFormatter } from "@/lib/payment-totals";

interface Props {
  /** Called after a draft was applied so the page can refresh instances. */
  onApplied: () => void;
}

export default function ImportedBillsCard({ onApplied }: Props) {
  const t = useTranslations("ImportedBills");
  const locale = useLocale();
  const formatAmount = createAmountFormatter(locale);

  const [drafts, setDrafts] = useState<ImportDraftOut[]>([]);
  const [bills, setBills] = useState<BillTemplateOut[]>([]);
  const [busyId, setBusyId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(() => {
    fetchImportDrafts()
      .then(setDrafts)
      .catch(() => setDrafts([]));
  }, []);

  useEffect(() => {
    refresh();
    fetchBills()
      .then(setBills)
      .catch(() => setBills([]));
  }, [refresh]);

  async function handleConfirm(draft: ImportDraftOut) {
    setBusyId(draft.id);
    setError(null);
    try {
      await confirmImportDraft(draft.id, draft.matched_bill_id);
      setDrafts((prev) => prev.filter((item) => item.id !== draft.id));
      onApplied();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("confirmFailed"));
    } finally {
      setBusyId(null);
    }
  }

  async function handleDiscard(draft: ImportDraftOut) {
    setBusyId(draft.id);
    setError(null);
    try {
      await discardImportDraft(draft.id);
      setDrafts((prev) => prev.filter((item) => item.id !== draft.id));
    } catch (err) {
      setError(err instanceof Error ? err.message : t("discardFailed"));
    } finally {
      setBusyId(null);
    }
  }

  async function handleBillChange(draft: ImportDraftOut, billId: string) {
    const value = billId === "" ? null : Number(billId);
    try {
      const updated = await updateImportDraft(draft.id, { matched_bill_id: value });
      setDrafts((prev) => prev.map((item) => (item.id === updated.id ? updated : item)));
    } catch (err) {
      setError(err instanceof Error ? err.message : t("updateFailed"));
    }
  }

  if (drafts.length === 0) return null;

  return (
    <div
      data-testid="imported-bills"
      className="mb-6 rounded-2xl border border-blue-200 bg-blue-50/60 p-4 dark:border-blue-900/60 dark:bg-blue-900/10"
    >
      <div className="mb-3 flex items-center gap-2">
        <FileSearch size={16} className="text-blue-600 dark:text-blue-400" />
        <h2 className="text-sm font-semibold text-blue-800 dark:text-blue-300">
          {t("title", { count: drafts.length })}
        </h2>
      </div>

      {error && (
        <p className="mb-3 rounded-xl bg-red-50 px-3 py-2 text-xs text-red-600 dark:bg-red-900/20 dark:text-red-400">
          {error}
        </p>
      )}

      <ul className="flex flex-col gap-2">
        {drafts.map((draft) => {
          const label = draft.provider ?? draft.filename ?? t("unknownSource");
          const amount =
            draft.amount != null
              ? `${formatAmount.format(parseFloat(draft.amount))} ${draft.currency ?? ""}`.trim()
              : t("noAmount");
          const sourceLabel = t(`source.${draft.source}`);
          return (
            <li
              key={draft.id}
              className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-blue-200/70 bg-white px-3 py-2 dark:border-blue-900/40 dark:bg-slate-800"
            >
              <div className="min-w-0">
                <p className="truncate text-sm font-medium text-slate-800 dark:text-slate-100">
                  {label}
                </p>
                <p className="text-xs text-slate-500 dark:text-slate-400">
                  {amount}
                  {draft.due_date ? ` · ${draft.due_date}` : ""}
                  {` · ${sourceLabel}`}
                </p>
              </div>

              <div className="flex flex-wrap items-center gap-2">
                <select
                  aria-label={t("billPickerLabel")}
                  value={draft.matched_bill_id ?? ""}
                  onChange={(e) => handleBillChange(draft, e.target.value)}
                  disabled={busyId === draft.id}
                  className="rounded-lg border border-slate-200 bg-white px-2 py-1.5 text-xs text-slate-700 outline-none focus:border-blue-500 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-200"
                >
                  <option value="">{t("pickBill")}</option>
                  {bills.map((bill) => (
                    <option key={bill.id} value={bill.id}>
                      {bill.name}
                    </option>
                  ))}
                </select>
                <button
                  type="button"
                  onClick={() => handleConfirm(draft)}
                  disabled={busyId === draft.id || draft.matched_bill_id === null}
                  className="flex items-center gap-1 rounded-lg border border-blue-700 bg-blue-700 px-2.5 py-1.5 text-xs font-medium text-white shadow-sm transition-all hover:border-blue-800 hover:bg-blue-800 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {busyId === draft.id ? (
                    <Loader2 size={12} className="animate-spin" />
                  ) : (
                    <Check size={12} />
                  )}
                  {t("confirm")}
                </button>
                <button
                  type="button"
                  onClick={() => handleDiscard(draft)}
                  disabled={busyId === draft.id}
                  aria-label={t("discard")}
                  className="rounded-lg border border-slate-200 bg-white p-1.5 text-slate-400 shadow-sm transition-all hover:border-red-300 hover:bg-red-50 hover:text-red-600 disabled:opacity-50 dark:border-slate-600 dark:bg-slate-800 dark:hover:border-red-800 dark:hover:bg-red-900/20 dark:hover:text-red-400"
                >
                  <Trash2 size={13} />
                </button>
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

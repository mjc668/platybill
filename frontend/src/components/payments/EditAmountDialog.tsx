"use client";

import { useEffect, useRef, useState } from "react";
import { Pencil } from "lucide-react";
import { useTranslations } from "next-intl";
import {
  confirmInstanceAmount,
  type PaymentInstanceOut,
} from "@/lib/payments-api";

interface Props {
  instance: PaymentInstanceOut;
  onClose: () => void;
  onUpdated: (updated: PaymentInstanceOut) => void;
}

export default function EditAmountDialog({
  instance,
  onClose,
  onUpdated,
}: Props) {
  const t = useTranslations("EditAmountDialog");
  const [amount, setAmount] = useState(instance.amount);
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  async function handleSave() {
    const parsed = parseFloat(amount);
    if (!Number.isFinite(parsed) || parsed <= 0) {
      setError(t("invalidAmount"));
      return;
    }
    setIsSaving(true);
    setError(null);
    try {
      const updated = await confirmInstanceAmount(instance.id, amount.trim());
      if (mounted.current) onUpdated(updated);
    } catch (err) {
      if (!mounted.current) return;
      setError(err instanceof Error ? err.message : t("saveFailed"));
      setIsSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 px-4 backdrop-blur-sm">
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="edit-amount-dialog-title"
        onKeyDown={(e) => e.key === "Escape" && onClose()}
        className="w-full max-w-sm rounded-2xl border border-slate-200 bg-white p-6 shadow-xl dark:bg-slate-800 dark:border-slate-700"
      >
        <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-blue-100 text-blue-600 dark:bg-blue-900/30 dark:text-blue-400">
          <Pencil size={20} />
        </div>
        <h2
          id="edit-amount-dialog-title"
          className="mb-1 text-lg font-semibold text-slate-800 dark:text-slate-100"
        >
          {t("title", { billName: instance.bill_name })}
        </h2>
        <p className="mb-4 text-sm text-slate-500 dark:text-slate-400">
          {t("description")}
        </p>

        <label
          htmlFor="edit-amount-input"
          className="mb-1 block text-sm font-medium text-slate-700 dark:text-slate-300"
        >
          {t("amountLabel", { currency: instance.currency })}
        </label>
        <input
          id="edit-amount-input"
          type="text"
          inputMode="decimal"
          value={amount}
          autoFocus
          onChange={(e) => setAmount(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && void handleSave()}
          className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-800 outline-none transition-all focus:border-blue-500 focus:ring-2 focus:ring-blue-100 dark:border-slate-600 dark:bg-slate-700 dark:text-slate-100 dark:focus:border-blue-600 dark:focus:ring-blue-900/40"
        />

        {error && (
          <p className="mt-2 text-sm text-red-600 dark:text-red-400">{error}</p>
        )}

        <div className="mt-6 flex gap-3">
          <button
            onClick={onClose}
            disabled={isSaving}
            className="flex-1 rounded-xl border border-slate-200 bg-white py-2.5 text-sm font-medium text-slate-700 shadow-sm transition-all hover:border-slate-300 hover:bg-slate-50 disabled:opacity-50 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-300 dark:hover:bg-slate-700"
          >
            {t("cancel")}
          </button>
          <button
            onClick={() => void handleSave()}
            disabled={isSaving}
            className="flex-1 rounded-xl border border-blue-700 bg-blue-700 py-2.5 text-sm font-medium text-white shadow-sm transition-all hover:border-blue-800 hover:bg-blue-800 disabled:opacity-50"
          >
            {isSaving ? t("saving") : t("save")}
          </button>
        </div>
      </div>
    </div>
  );
}

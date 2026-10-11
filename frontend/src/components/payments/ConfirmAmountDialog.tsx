"use client";

import { useEffect, useRef, useState } from "react";
import { ReceiptText } from "lucide-react";
import { useTranslations, useLocale } from "next-intl";
import {
  confirmInstanceAmount,
  type PendingConfirmationOut,
  type PaymentInstanceOut,
} from "@/lib/payments-api";
import { createAmountFormatter } from "@/lib/payment-totals";

interface Props {
  instance: PendingConfirmationOut;
  isOpen: boolean;
  onClose: () => void;
  onConfirm: (updated: PaymentInstanceOut) => void;
}

export default function ConfirmAmountDialog({
  instance,
  isOpen,
  onClose,
  onConfirm,
}: Props) {
  const t = useTranslations("ConfirmAmountDialog");
  const locale = useLocale();
  const formatAmount = createAmountFormatter(locale);

  const [amount, setAmount] = useState(instance.amount);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  if (!isOpen) return null;

  const amountValue = parseFloat(amount);
  const amountValid = Number.isFinite(amountValue) && amountValue > 0;

  async function handleConfirm() {
    if (!amountValid) {
      setError(t("amountInvalid"));
      return;
    }
    setIsSubmitting(true);
    setError(null);
    try {
      const updated = await confirmInstanceAmount(instance.id, amountValue.toFixed(2));
      onConfirm(updated);
    } catch (err) {
      if (!mounted.current) return;
      setError(err instanceof Error ? err.message : t("saveFailed"));
      setIsSubmitting(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 px-4 backdrop-blur-sm">
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="confirm-amount-dialog-title"
        onKeyDown={(e) => e.key === "Escape" && !isSubmitting && onClose()}
        className="w-full max-w-sm rounded-2xl border border-slate-200 bg-white p-6 shadow-xl dark:border-slate-700 dark:bg-slate-800"
      >
        <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-amber-100 text-amber-600 dark:bg-amber-900/30 dark:text-amber-400">
          <ReceiptText size={22} />
        </div>

        <h2
          id="confirm-amount-dialog-title"
          className="mb-1 text-lg font-semibold text-slate-800 dark:text-slate-100"
        >
          {t("title", { billName: instance.bill_name })}
        </h2>
        <p className="mb-4 text-sm text-slate-500 dark:text-slate-400">
          {t("subtitle", { period: instance.period })}
        </p>

        {instance.basis_amounts.length > 0 && (
          <p className="mb-3 rounded-xl bg-slate-50 px-3 py-2 text-xs text-slate-500 dark:bg-slate-900/40 dark:text-slate-400">
            {t("basisLabel")}{" "}
            {instance.basis_amounts
              .map((a) => `${formatAmount.format(parseFloat(a))} ${instance.currency}`)
              .join(" · ")}
          </p>
        )}

        <div className="mb-5">
          <label
            htmlFor="confirm-amount"
            className="mb-1.5 block text-sm font-medium text-slate-700 dark:text-slate-300"
          >
            {t("amountLabel")}
          </label>
          <div className="flex items-center gap-2 rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 focus-within:border-blue-500 focus-within:ring-2 focus-within:ring-blue-100 dark:border-slate-600 dark:bg-slate-900/40 dark:focus-within:border-blue-600">
            <input
              id="confirm-amount"
              type="number"
              step="0.01"
              min="0.01"
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              className="flex-1 bg-transparent text-sm text-slate-800 outline-none dark:text-slate-100"
            />
            <span className="text-sm text-slate-400 dark:text-slate-500">
              {instance.currency}
            </span>
          </div>
        </div>

        {error && (
          <p className="mb-4 rounded-xl bg-red-50 px-3 py-2 text-sm text-red-600 dark:bg-red-900/20 dark:text-red-400">
            {error}
          </p>
        )}

        <div className="flex justify-end gap-3">
          <button
            type="button"
            onClick={onClose}
            disabled={isSubmitting}
            className="rounded-xl border border-slate-200 bg-white px-4 py-2 text-sm font-medium text-slate-600 shadow-sm transition-all hover:border-slate-300 hover:bg-slate-50 disabled:opacity-50 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-400 dark:hover:bg-slate-700"
          >
            {t("cancel")}
          </button>
          <button
            type="button"
            onClick={handleConfirm}
            disabled={isSubmitting || !amountValid}
            className="rounded-xl border border-blue-700 bg-blue-700 px-5 py-2 text-sm font-medium text-white shadow-sm transition-all hover:border-blue-800 hover:bg-blue-800 disabled:opacity-50"
          >
            {t("confirm")}
          </button>
        </div>
      </div>
    </div>
  );
}

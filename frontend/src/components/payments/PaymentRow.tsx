"use client";

import { useState, useRef, useEffect } from "react";
import { AlertCircle, AtSign, CheckCircle, Loader2, MessageSquare, Pencil, RotateCcw, Trash2 } from "lucide-react";
import { useTranslations, useLocale } from "next-intl";
import type { PaymentInstanceOut } from "@/lib/payments-api";
import { deletePaymentEvent, revertPay } from "@/lib/payments-api";
import { bankAccountLabel } from "@/lib/bank-accounts-api";
import { categoryLabel } from "@/lib/categories-api";

export const STATUS_STYLES: Record<string, string> = {
  upcoming:
    "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300",
  overdue:
    "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400",
  paid: "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400",
};

interface Props {
  instance: PaymentInstanceOut;
  onMarkPaid: (instance: PaymentInstanceOut) => void;
  onDelete: (instance: PaymentInstanceOut) => void;
  onReverted: (updated: PaymentInstanceOut) => void;
  /** True for past months — hides the Mark as Paid button. */
  readOnly?: boolean;
}

export default function PaymentRow({ instance, onMarkPaid, onDelete, onReverted, readOnly = false }: Props) {
  const t = useTranslations("PaymentRow");
  const tRoot = useTranslations();
  const locale = useLocale();
  const [reverting, setReverting] = useState(false);
  const [deletingEventId, setDeletingEventId] = useState<number | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  const [noteOpen, setNoteOpen] = useState(false);
  const noteRef = useRef<HTMLDivElement>(null);
  const [emailOpen, setEmailOpen] = useState(false);
  const emailRef = useRef<HTMLDivElement>(null);
  const [editOpen, setEditOpen] = useState(false);

  useEffect(() => {
    if (!noteOpen) return;
    function handleClickOutside(e: MouseEvent) {
      if (noteRef.current && !noteRef.current.contains(e.target as Node)) {
        setNoteOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [noteOpen]);

  useEffect(() => {
    if (!emailOpen) return;
    function handleClickOutside(e: MouseEvent) {
      if (emailRef.current && !emailRef.current.contains(e.target as Node)) {
        setEmailOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [emailOpen]);

  async function handleRevert() {
    setReverting(true);
    setActionError(null);
    try {
      const updated = await revertPay(instance.id);
      onReverted(updated);
    } catch (err) {
      if (!mounted.current) return;
      setActionError(err instanceof Error ? err.message : t("revertFailed"));
    } finally {
      if (mounted.current) setReverting(false);
    }
  }

  async function handleDeleteEvent(paymentId: number) {
    setDeletingEventId(paymentId);
    setActionError(null);
    try {
      const updated = await deletePaymentEvent(instance.id, paymentId);
      onReverted(updated);
    } catch (err) {
      if (!mounted.current) return;
      setActionError(err instanceof Error ? err.message : t("deleteEventFailed"));
    } finally {
      if (mounted.current) setDeletingEventId(null);
    }
  }

  // Append T00:00:00 so JS treats due_date as local time, not UTC midnight
  const dueDate = new Date(instance.due_date + "T00:00:00");
  function formatDate(date: Date): string {
    const fmt = new Intl.DateTimeFormat(locale, { day: "numeric", month: "short" });
    return fmt.formatToParts(date).map(({ type, value }) =>
      type === "month" ? value.charAt(0).toUpperCase() + value.slice(1) : value
    ).join("");
  }

  const dueDateFormatted = formatDate(dueDate);

  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const isDueToday = dueDate.getTime() === today.getTime();

  function tileGradientClass(): string {
    const base = "bg-gradient-to-r from-0% to-70%";
    if (instance.status === "overdue") return `${base} from-red-100 to-white dark:from-red-500/10 dark:to-slate-800`;
    if (instance.status === "paid") return `${base} from-blue-100 to-white dark:from-blue-500/10 dark:to-slate-800`;
    if (isDueToday) return `${base} from-orange-100 to-white dark:from-orange-400/10 dark:to-slate-800`;
    return `${base} from-blue-100 to-white dark:from-blue-400/10 dark:to-slate-800`;
  }

  const paidAt = instance.paid_at ? new Date(instance.paid_at) : null;
  const paidAtFormatted = paidAt ? formatDate(paidAt) : null;

  const amountMismatch =
    instance.status === "paid" &&
    instance.paid_amount != null &&
    parseFloat(instance.amount) > 0 &&
    parseFloat(instance.paid_amount) !== parseFloat(instance.amount);

  const payments = instance.payments ?? [];
  const hasLedger = payments.length > 0;
  const ledgerTotal = payments.reduce((sum, p) => sum + (parseFloat(p.amount) || 0), 0);
  const paidTotal = instance.paid_amount != null ? parseFloat(instance.paid_amount) : ledgerTotal;
  const remainingTotal = Math.max(parseFloat(instance.amount) - paidTotal, 0);

  const emailSentAt = instance.email_sent_at ? new Date(instance.email_sent_at) : null;
  const emailSentAtFormatted = emailSentAt
    ? new Intl.DateTimeFormat(locale, {
        day: "numeric",
        month: "short",
        year: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      }).format(emailSentAt)
    : null;

  return (
    <div
      data-testid="payment-row"
      className={`rounded-xl border border-slate-200 px-4 py-3 shadow-sm dark:border-slate-700 transition-colors ${tileGradientClass()}`}
    >
      <div className="flex flex-col gap-0.5">
        {/* Name + category */}
        <div className="flex items-center gap-2 min-w-0">
          <span className="font-semibold text-sm text-slate-800 dark:text-slate-100 truncate">
            {instance.bill_name}
          </span>
          <span className="shrink-0 rounded-full bg-slate-100 px-1.5 py-0.5 text-[11px] font-medium text-slate-500 dark:bg-slate-700 dark:text-slate-400">
            {categoryLabel(instance.category, tRoot)}
          </span>
          {instance.preferred_account && (
            <span className="shrink-0 truncate max-w-32 rounded-full bg-emerald-50 px-1.5 py-0.5 text-[11px] font-medium text-emerald-600 dark:bg-emerald-900/30 dark:text-emerald-400">
              {bankAccountLabel(instance.preferred_account)}
            </span>
          )}
        </div>
        {/* Amount */}
        {parseFloat(instance.amount) > 0 && (
          <span className="text-xs font-medium text-slate-600 dark:text-slate-300">
            {instance.amount} {instance.currency}
          </span>
        )}
        {/* Due date + status (left) — actions (right) */}
        <div className="flex items-center justify-between gap-2 mt-0.5">
          <div className="flex items-center gap-1.5 text-xs min-w-0">
            <span className="text-slate-400 dark:text-slate-500 shrink-0">
              {t("due")} {dueDateFormatted}
            </span>
            <span className="text-slate-300 dark:text-slate-600">•</span>
            {instance.status === "paid" && paidAtFormatted ? (
              <span className="text-blue-600 dark:text-blue-400 truncate">
                {t("paidOn")} {paidAtFormatted}
                {instance.paid_amount != null && parseFloat(instance.paid_amount) > 0 && (
                  <> · {instance.paid_amount} {instance.currency}</>
                )}
              </span>
            ) : isDueToday && instance.status === "upcoming" ? (
              <span className="rounded-full px-2 py-0.5 text-xs font-medium shrink-0 bg-orange-100 text-orange-600 dark:bg-orange-900/30 dark:text-orange-400">
                {t("dueToday")}
              </span>
            ) : (
              <span className={`rounded-full px-2 py-0.5 text-xs font-medium shrink-0 ${STATUS_STYLES[instance.status] ?? ""}`}>
                {t(`status.${instance.status}` as Parameters<typeof t>[0])}
              </span>
            )}
          </div>

          {/* Actions */}
          <div className="flex items-center gap-1 shrink-0">
            {/* Primary action */}
            {!readOnly && instance.status !== "paid" && (
              <button
                onClick={() => onMarkPaid(instance)}
                className="flex items-center gap-1.5 rounded-lg border border-blue-200 bg-white px-2.5 py-1 text-sm font-medium text-blue-600 shadow-sm transition-all hover:border-blue-300 hover:bg-blue-50 hover:text-blue-700 dark:border-blue-800 dark:bg-slate-800 dark:text-blue-400 dark:hover:border-blue-700 dark:hover:bg-blue-900/20 dark:hover:text-blue-300"
              >
                <CheckCircle size={14} />
                <span className="hidden sm:inline">{t("markAsPaid")}</span>
              </button>
            )}
            {/* Edit amount — unpaid rows only */}
            {!readOnly && instance.status !== "paid" && (
              <button
                onClick={() => setEditOpen(true)}
                aria-label={t("editAmount")}
                title={t("editAmount")}
                className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-600 dark:text-slate-500 dark:hover:bg-slate-700 dark:hover:text-slate-300 transition-colors"
              >
                <Pencil size={14} />
              </button>
            )}
            {/* Note — legacy popover, only when there are no ledger entries */}
            {instance.status === "paid" && instance.notes && !hasLedger && (
              <>
                <div className="relative" ref={noteRef}>
                  <button
                    aria-label={t("paymentNote")}
                    aria-expanded={noteOpen}
                    onClick={() => setNoteOpen((o) => !o)}
                    className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-600 dark:text-slate-500 dark:hover:bg-slate-700 dark:hover:text-slate-300 transition-colors"
                  >
                    <MessageSquare size={14} />
                  </button>
                  {noteOpen && (
                    <div className="absolute bottom-full right-0 mb-2 w-56 rounded-lg bg-slate-800 px-3 py-2 text-xs text-white shadow-lg dark:bg-slate-700 z-10">
                      {instance.notes}
                      <div className="absolute top-full right-3 -mt-px border-4 border-transparent border-t-slate-800 dark:border-t-slate-700" />
                    </div>
                  )}
                </div>
                <div className="w-px h-4 bg-slate-200 dark:bg-slate-600 mx-0.5" />
              </>
            )}
            {/* Revert — visible for paid instances */}
            {instance.status === "paid" && (
              <button
                onClick={handleRevert}
                disabled={reverting}
                title={t("revert")}
                aria-label={t("revert")}
                className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-600 disabled:opacity-50 disabled:cursor-not-allowed dark:text-slate-500 dark:hover:bg-slate-700 dark:hover:text-slate-300 transition-colors"
              >
                {reverting ? <Loader2 size={14} className="animate-spin" /> : <RotateCcw size={14} />}
              </button>
            )}
            <div className="w-px h-4 bg-slate-200 dark:bg-slate-600 mx-0.5" />
            {/* Email notification indicator */}
            <div className="relative" ref={emailRef}>
              <button
                aria-label={t("emailNotification")}
                aria-expanded={emailOpen}
                onClick={() => setEmailOpen((o) => !o)}
                className={`rounded-lg p-1.5 transition-colors ${
                  emailSentAt
                    ? "text-amber-400 hover:bg-amber-50 dark:hover:bg-amber-900/20"
                    : "text-slate-300 hover:bg-slate-100 hover:text-slate-400 dark:text-slate-600 dark:hover:bg-slate-700 dark:hover:text-slate-500"
                }`}
              >
                <AtSign size={14} />
              </button>
              {emailOpen && (
                <div className="absolute bottom-full right-0 mb-2 w-48 rounded-lg bg-slate-800 px-3 py-2 text-xs text-white shadow-lg dark:bg-slate-700 z-10 whitespace-normal">
                  {emailSentAtFormatted
                    ? `${t("emailSentOn")} ${emailSentAtFormatted}`
                    : t("emailNotSent")}
                  <div className="absolute top-full right-3 -mt-px border-4 border-transparent border-t-slate-800 dark:border-t-slate-700" />
                </div>
              )}
            </div>
            <div className="w-px h-4 bg-slate-200 dark:bg-slate-600 mx-0.5" />
            <button
              onClick={() => onDelete(instance)}
              aria-label={t("delete")}
              className="rounded-lg p-1.5 text-slate-400 hover:bg-red-50 hover:text-red-500 dark:text-slate-500 dark:hover:bg-red-900/20 dark:hover:text-red-400 transition-colors"
            >
              <Trash2 size={14} />
            </button>
          </div>
        </div>
        {/* Amount mismatch warning */}
        {amountMismatch && (
          <div className="flex items-center gap-1.5 text-xs text-slate-400 dark:text-slate-500 mt-0.5">
            <AlertCircle size={12} className="shrink-0 text-amber-500 dark:text-amber-400" />
            <span>{t("amountMismatch", { expected: `${instance.amount} ${instance.currency}`, paid: `${instance.paid_amount} ${instance.currency}` })}</span>
          </div>
        )}

        {/* Payment ledger */}
        {hasLedger && (
          <div className="mt-2 border-t border-slate-200/70 pt-2 dark:border-slate-600/50">
            <div className="flex flex-wrap items-baseline justify-between gap-x-2 gap-y-0.5 text-xs">
              <span className="font-medium text-slate-600 dark:text-slate-300">
                {t("paidSoFar", { paid: paidTotal.toFixed(2), total: instance.amount })}
              </span>
              {instance.status !== "paid" && (
                <span className="text-slate-500 dark:text-slate-400">
                  {t("remaining", { amount: `${remainingTotal.toFixed(2)} ${instance.currency}` })}
                </span>
              )}
            </div>
            <ul className="mt-1.5 flex flex-col gap-1">
              {payments.map((payment) => (
                <li
                  key={payment.id}
                  className="flex items-center gap-2 text-xs text-slate-500 dark:text-slate-400"
                >
                  <span className="shrink-0">
                    {formatDate(new Date(payment.paid_on + "T00:00:00"))}
                  </span>
                  <span className="font-medium text-slate-600 dark:text-slate-300">
                    {payment.amount} {instance.currency}
                  </span>
                  {payment.note && <span className="truncate italic">{payment.note}</span>}
                  <button
                    onClick={() => handleDeleteEvent(payment.id)}
                    disabled={deletingEventId === payment.id}
                    title={t("deletePaymentRecord")}
                    aria-label={t("deletePaymentRecord")}
                    className="ml-auto shrink-0 rounded-lg p-1 text-slate-400 transition-colors hover:bg-red-50 hover:text-red-500 disabled:opacity-50 disabled:cursor-not-allowed dark:text-slate-500 dark:hover:bg-red-900/20 dark:hover:text-red-400"
                  >
                    {deletingEventId === payment.id ? (
                      <Loader2 size={12} className="animate-spin" />
                    ) : (
                      <Trash2 size={12} />
                    )}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}

        {actionError && (
          <p className="mt-1 text-xs text-red-600 dark:text-red-400">{actionError}</p>
        )}
      </div>

      {editOpen && (
        <EditAmountDialog
          instance={instance}
          onClose={() => setEditOpen(false)}
          onUpdated={(updated) => {
            setEditOpen(false);
            onReverted(updated);
          }}
        />
      )}
    </div>
  );
}

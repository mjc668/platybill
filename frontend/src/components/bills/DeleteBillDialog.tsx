"use client";

import { Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";
import { createPortal } from "react-dom";

interface Props {
  billName: string;
  onConfirm: () => void;
  onCancel: () => void;
  deleting?: boolean;
}

export default function DeleteBillDialog({
  billName,
  onConfirm,
  onCancel,
  deleting = false,
}: Props) {
  const t = useTranslations("DeleteBillDialog");
  return createPortal(
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 px-4 backdrop-blur-sm">
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="delete-bill-dialog-title"
        onKeyDown={(e) => e.key === "Escape" && onCancel()}
        className="w-full max-w-sm rounded-2xl border border-slate-200 bg-white p-6 shadow-xl dark:bg-slate-800 dark:border-slate-700"
      >
        <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-red-100 text-red-600 dark:bg-red-900/30 dark:text-red-400">
          <Trash2 size={22} />
        </div>
        <h2
          id="delete-bill-dialog-title"
          className="mb-1 text-lg font-semibold text-slate-800 dark:text-slate-100"
        >
          {t("title", { billName })}
        </h2>
        <p className="mb-6 text-sm text-slate-500 dark:text-slate-400">
          {t("description")}
        </p>
        <div className="flex gap-3">
          <button
            onClick={onCancel}
            autoFocus
            className="flex-1 rounded-xl border border-slate-200 bg-white py-2.5 text-sm font-medium text-slate-700 shadow-sm transition-all hover:border-slate-300 hover:bg-slate-50 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-300 dark:hover:bg-slate-700 disabled:opacity-50"
          >
            {t("cancel")}
          </button>
          <button
            onClick={onConfirm}
            disabled={deleting}
            className="flex-1 rounded-xl border border-red-600 bg-red-600 py-2.5 text-sm font-medium text-white shadow-sm transition-all hover:border-red-700 hover:bg-red-700 disabled:opacity-50"
          >
            {deleting ? t("deleting") : t("delete")}
          </button>
        </div>
      </div>
    </div>,
    document.body
  );
}

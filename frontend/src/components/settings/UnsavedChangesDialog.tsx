"use client";

import { createPortal } from "react-dom";
import type { TileTranslator } from "./Tile";

export function UnsavedChangesDialog({
  onStay,
  t,
}: {
  onLeave: () => void;
  onStay: () => void;
  t: TileTranslator;
}) {
  return createPortal(
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div
        className="absolute inset-0 bg-black/40"
        onClick={onStay}
        aria-hidden="true"
      />
      <div className="relative z-10 w-full max-w-sm mx-4 rounded-xl bg-white dark:bg-slate-800 shadow-xl p-6">
        <h3 className="font-semibold text-slate-800 dark:text-slate-100 mb-2">
          {t("unsavedTitle")}
        </h3>
        <p className="text-sm text-slate-500 dark:text-slate-400 mb-5">
          {t("unsavedDescription")}
        </p>
        <div className="flex gap-2 justify-end">
          <button
            onClick={onStay}
            className="rounded-lg border border-slate-200 bg-white px-4 py-1.5 text-sm font-medium text-slate-600 shadow-sm transition-all hover:border-slate-300 hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-300 dark:hover:bg-slate-700"
          >
            {t("unsavedStay")}
          </button>
          <button
            onClick={onLeave}
            className="rounded-lg border border-red-600 bg-red-600 px-4 py-1.5 text-sm font-medium text-white shadow-sm transition-all hover:border-red-700 hover:bg-red-700"
          >
            {t("unsavedLeave")}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}

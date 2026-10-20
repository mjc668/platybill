"use client";

import { ChevronRight } from "lucide-react";
import { useTranslations } from "next-intl";

export type TileColor = "blue" | "yellow" | "red";

/** Translator passed into Tile and its callers. */
export type TileTranslator = ReturnType<typeof useTranslations>;

export const TILE_STYLES: Record<
  TileColor,
  { border: string; header: string; icon: string }
> = {
  blue: {
    border: "border-blue-400 dark:border-blue-500",
    header: "bg-blue-50 dark:bg-blue-900/30",
    icon: "text-blue-500 dark:text-blue-400",
  },
  yellow: {
    border: "border-yellow-400 dark:border-yellow-500",
    header: "bg-yellow-50 dark:bg-yellow-900/30",
    icon: "text-yellow-600 dark:text-yellow-400",
  },
  red: {
    border: "border-red-400 dark:border-red-500",
    header: "bg-red-50 dark:bg-red-900/30",
    icon: "text-red-500 dark:text-red-400",
  },
};

export function Tile({
  color,
  icon: Icon,
  title,
  description,
  children,
  isDirty,
  isSaving,
  saveError,
  onSave,
  onCancel,
  isCollapsed,
  onToggle,
  t,
}: {
  color: TileColor;
  icon: React.ElementType;
  title: string;
  description: string;
  children: React.ReactNode;
  isDirty?: boolean;
  isSaving?: boolean;
  saveError?: string | null;
  onSave?: () => void;
  onCancel?: () => void;
  isCollapsed?: boolean;
  onToggle?: () => void;
  t: TileTranslator;
}) {
  const s = TILE_STYLES[color];
  return (
    <div
      className={`rounded-xl border-l-4 border border-slate-200 dark:border-slate-700 overflow-hidden ${s.border}`}
    >
      <button
        onClick={onToggle}
        className={`w-full text-left px-5 py-4 ${s.header} ${onToggle ? "cursor-pointer" : "cursor-default"}`}
      >
        <div className="flex items-center gap-2">
          <Icon size={18} className={s.icon} />
          <h2 className="flex-1 font-semibold text-slate-800 dark:text-slate-100">
            {title}
          </h2>
          {onToggle && (
            <ChevronRight
              size={14}
              className={`shrink-0 text-slate-400 dark:text-slate-500 transition-transform duration-150 ${
                isCollapsed ? "" : "rotate-90"
              }`}
            />
          )}
        </div>
        {!isCollapsed && (
          <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
            {description}
          </p>
        )}
      </button>

      {!isCollapsed && (
        <div className="px-5 py-4 space-y-4 bg-white dark:bg-slate-800">
          {children}

          {saveError && (
            <p className="text-sm text-red-600 dark:text-red-400">{saveError}</p>
          )}

          {isDirty && onSave && onCancel && (
            <div className="flex gap-2 pt-1">
              <button
                onClick={onSave}
                disabled={isSaving}
                className="rounded-lg border border-blue-700 bg-blue-700 px-4 py-1.5 text-sm font-medium text-white shadow-sm transition-all hover:border-blue-800 hover:bg-blue-800 disabled:opacity-50"
              >
                {isSaving ? t("saving") : t("save")}
              </button>
              <button
                onClick={onCancel}
                disabled={isSaving}
                className="rounded-lg border border-slate-200 bg-white px-4 py-1.5 text-sm font-medium text-slate-600 shadow-sm transition-all hover:border-slate-300 hover:bg-slate-50 disabled:opacity-50 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-300 dark:hover:bg-slate-700"
              >
                {t("cancel")}
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

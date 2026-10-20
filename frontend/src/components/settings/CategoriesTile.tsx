"use client";

import { useEffect, useState } from "react";
import {
  Archive,
  ArchiveRestore,
  Check,
  Loader2,
  Pencil,
  Tags,
  Trash2,
  X,
} from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import {
  categoryLabel,
  createCategory,
  deleteCategory,
  fetchCategories,
  updateCategory,
  type Category,
} from "@/lib/categories-api";
import { sortCategories } from "@/lib/categories";
import { Tile, type TileTranslator } from "./Tile";
  "shrink-0 rounded-lg border border-blue-700 bg-blue-700 px-4 py-2 text-sm font-medium text-white shadow-sm transition-all hover:border-blue-800 hover:bg-blue-800 disabled:opacity-50";
const btnNeutral =
  "shrink-0 rounded-lg border border-slate-200 bg-white px-4 py-2 text-sm font-medium text-slate-600 shadow-sm transition-all hover:border-slate-300 hover:bg-slate-50 disabled:opacity-50 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-300 dark:hover:bg-slate-700";
const iconButton =
  "shrink-0 rounded-lg p-1.5 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-600 disabled:opacity-50 dark:text-slate-500 dark:hover:bg-slate-700 dark:hover:text-slate-300";
const iconButtonDanger =
  "shrink-0 rounded-lg p-1.5 text-slate-400 transition-colors hover:bg-red-50 hover:text-red-500 disabled:opacity-50 dark:text-slate-500 dark:hover:bg-red-900/20 dark:hover:text-red-400";

export function CategoriesTile({
  t,
  isCollapsed,
  onToggle,
}: {
  t: TileTranslator;
  isCollapsed?: boolean;
  onToggle?: () => void;
}) {
  const tc = useTranslations("SettingsPage.categories");
  const tRoot = useTranslations();
  const locale = useLocale();

  const [categories, setCategories] = useState<Category[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [newName, setNewName] = useState("");
  const [adding, setAdding] = useState(false);

  const [renamingId, setRenamingId] = useState<number | null>(null);
  const [renameDraft, setRenameDraft] = useState("");
  const [busyId, setBusyId] = useState<number | null>(null);
  const [deleteTargetId, setDeleteTargetId] = useState<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchCategories(true)
      .then((data) => {
        if (!cancelled) {
          setCategories(data);
          setLoading(false);
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : tc("loadError"));
          setLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [tc]);

  const sorted = sortCategories(categories, locale, tRoot);

  function replaceCategory(updated: Category) {
    setCategories((prev) => prev.map((c) => (c.id === updated.id ? updated : c)));
  }

  async function handleAdd() {
    const name = newName.trim();
    if (!name || adding) return;
    setAdding(true);
    setError(null);
    try {
      const created = await createCategory(name);
      setCategories((prev) => [...prev, created]);
      setNewName("");
    } catch (err) {
      setError(err instanceof Error ? err.message : tc("error"));
    } finally {
      setAdding(false);
    }
  }

  function startRename(category: Category) {
    setRenamingId(category.id);
    setRenameDraft(categoryLabel(category, tRoot));
    setError(null);
  }

  async function saveRename(category: Category) {
    const name = renameDraft.trim();
    if (!name || busyId !== null) return;
    setBusyId(category.id);
    setError(null);
    try {
      replaceCategory(await updateCategory(category.id, { name }));
      setRenamingId(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : tc("error"));
    } finally {
      setBusyId(null);
    }
  }

  async function toggleArchive(category: Category) {
    if (busyId !== null) return;
    setBusyId(category.id);
    setError(null);
    try {
      replaceCategory(
        await updateCategory(category.id, { is_archived: !category.is_archived }),
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : tc("error"));
    } finally {
      setBusyId(null);
    }
  }

  async function confirmDelete(category: Category) {
    if (busyId !== null) return;
    setBusyId(category.id);
    setError(null);
    try {
      await deleteCategory(category.id);
      setCategories((prev) => prev.filter((c) => c.id !== category.id));
      setDeleteTargetId(null);
    } catch (err) {
      setError(
        err instanceof Error && err.message.trim() !== ""
          ? err.message
          : tc("deleteBlocked"),
      );
      setDeleteTargetId(null);
    } finally {
      setBusyId(null);
    }
  }

  return (
    <Tile
      color="blue"
      icon={Tags}
      title={tc("title")}
      description={tc("description")}
      t={t}
      isCollapsed={isCollapsed}
      onToggle={onToggle}
    >
      <div data-testid="categories-tile" className="space-y-4">
        {error && (
          <p
            data-testid="category-error"
            className="text-sm text-red-600 dark:text-red-400"
          >
            {error}
          </p>
        )}

        <div className="flex gap-2">
          <input
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                void handleAdd();
              }
            }}
            placeholder={tc("addPlaceholder")}
            aria-label={tc("addLabel")}
            maxLength={50}
            disabled={adding}
            className={inputClass}
          />
          <button
            type="button"
            onClick={() => void handleAdd()}
            disabled={adding || newName.trim() === ""}
            className={btnSave}
          >
            {adding ? tc("adding") : tc("add")}
          </button>
        </div>

        {loading ? (
          <div className="h-10 animate-pulse rounded-lg bg-slate-100 dark:bg-slate-700" />
        ) : (
          <ul className="flex flex-col gap-1.5">
            {sorted.map((category) => {
              const label = categoryLabel(category, tRoot);
              const isRenaming = renamingId === category.id;
              const isDeleting = deleteTargetId === category.id;
              return (
                <li
                  key={category.id}
                  className="flex items-center gap-2 rounded-lg border border-slate-200 px-3 py-2 dark:border-slate-700"
                >
                  {isRenaming ? (
                    <>
                      <input
                        value={renameDraft}
                        onChange={(e) => setRenameDraft(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter") {
                            e.preventDefault();
                            void saveRename(category);
                          } else if (e.key === "Escape") {
                            setRenamingId(null);
                          }
                        }}
                        aria-label={tc("rename")}
                        maxLength={50}
                        autoFocus
                        className={inputClass}
                      />
                      <button
                        type="button"
                        onClick={() => void saveRename(category)}
                        disabled={busyId === category.id || renameDraft.trim() === ""}
                        aria-label={tc("save")}
                        className={iconButton}
                      >
                        {busyId === category.id ? (
                          <Loader2 size={15} className="animate-spin" />
                        ) : (
                          <Check size={15} />
                        )}
                      </button>
                      <button
                        type="button"
                        onClick={() => setRenamingId(null)}
                        disabled={busyId === category.id}
                        aria-label={tc("cancel")}
                        className={iconButton}
                      >
                        <X size={15} />
                      </button>
                    </>
                  ) : isDeleting ? (
                    <>
                      <span className="flex-1 text-sm text-slate-700 dark:text-slate-200">
                        {tc("deleteConfirm", { name: label })}
                      </span>
                      <button
                        type="button"
                        onClick={() => void confirmDelete(category)}
                        disabled={busyId === category.id}
                        className="shrink-0 rounded-lg border border-red-600 bg-red-600 px-3 py-1.5 text-sm font-medium text-white shadow-sm transition-all hover:border-red-700 hover:bg-red-700 disabled:opacity-50"
                      >
                        {busyId === category.id ? (
                          <Loader2 size={14} className="animate-spin" />
                        ) : (
                          tc("delete")
                        )}
                      </button>
                      <button
                        type="button"
                        onClick={() => setDeleteTargetId(null)}
                        disabled={busyId === category.id}
                        className={btnNeutral}
                      >
                        {tc("cancel")}
                      </button>
                    </>
                  ) : (
                    <>
                      <span className="flex-1 truncate text-sm text-slate-700 dark:text-slate-200">
                        {label}
                      </span>
                      {category.is_archived && (
                        <span className="shrink-0 rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-500 dark:bg-slate-700 dark:text-slate-400">
                          {tc("archived")}
                        </span>
                      )}
                      <button
                        type="button"
                        onClick={() => startRename(category)}
                        aria-label={tc("rename")}
                        className={iconButton}
                      >
                        <Pencil size={14} />
                      </button>
                      <button
                        type="button"
                        onClick={() => void toggleArchive(category)}
                        disabled={busyId === category.id}
                        aria-label={category.is_archived ? tc("unarchive") : tc("archive")}
                        className={iconButton}
                      >
                        {busyId === category.id ? (
                          <Loader2 size={14} className="animate-spin" />
                        ) : category.is_archived ? (
                          <ArchiveRestore size={14} />
                        ) : (
                          <Archive size={14} />
                        )}
                      </button>
                      <button
                        type="button"
                        onClick={() => setDeleteTargetId(category.id)}
                        disabled={busyId === category.id}
                        aria-label={tc("delete")}
                        className={iconButtonDanger}
                      >
                        <Trash2 size={14} />
                      </button>
                    </>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </Tile>
  );
}

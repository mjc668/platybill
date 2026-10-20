"use client";

import { useEffect, useState } from "react";
import {
  Archive,
  ArchiveRestore,
  Check,
  Landmark,
  Loader2,
  Pencil,
  Trash2,
  X,
} from "lucide-react";
import { useTranslations } from "next-intl";
import {
  bankAccountLabel,
  createBankAccount,
  deleteBankAccount,
  fetchBankAccounts,
  updateBankAccount,
  type BankAccount,
} from "@/lib/bank-accounts-api";
import { Tile, type TileTranslator } from "./Tile";

export function BankAccountsTile({
  t,
  isCollapsed,
  onToggle,
}: {
  t: TileTranslator;
  isCollapsed?: boolean;
  onToggle?: () => void;
}) {
  const tc = useTranslations("SettingsPage.bankAccounts");
  const [accounts, setAccounts] = useState<BankAccount[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [newName, setNewName] = useState("");
  const [newIban, setNewIban] = useState("");
  const [adding, setAdding] = useState(false);

  const [editingId, setEditingId] = useState<number | null>(null);
  const [editName, setEditName] = useState("");
  const [editIban, setEditIban] = useState("");
  const [editNote, setEditNote] = useState("");
  const [busyId, setBusyId] = useState<number | null>(null);
  const [deleteTargetId, setDeleteTargetId] = useState<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchBankAccounts(true)
      .then((data) => {
        if (!cancelled) {
          setAccounts(data);
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

  const sorted = [...accounts].sort((a, b) =>
    a.name.localeCompare(b.name, undefined, { sensitivity: "base" }) || a.id - b.id,
  );

  function replaceAccount(updated: BankAccount) {
    setAccounts((prev) => prev.map((a) => (a.id === updated.id ? updated : a)));
  }

  async function handleAdd() {
    const name = newName.trim();
    if (!name || adding) return;
    setAdding(true);
    setError(null);
    try {
      const created = await createBankAccount({
        name,
        iban: newIban.trim() || null,
      });
      setAccounts((prev) => [...prev, created]);
      setNewName("");
      setNewIban("");
    } catch (err) {
      setError(err instanceof Error ? err.message : tc("error"));
    } finally {
      setAdding(false);
    }
  }

  function startEdit(account: BankAccount) {
    setEditingId(account.id);
    setEditName(account.name);
    setEditIban(account.iban ?? "");
    setEditNote(account.note ?? "");
    setError(null);
  }

  async function saveEdit(account: BankAccount) {
    const name = editName.trim();
    if (!name || busyId !== null) return;
    setBusyId(account.id);
    setError(null);
    try {
      replaceAccount(
        await updateBankAccount(account.id, {
          name,
          iban: editIban.trim() || null,
          note: editNote.trim() || null,
        }),
      );
      setEditingId(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : tc("error"));
    } finally {
      setBusyId(null);
    }
  }

  async function toggleArchive(account: BankAccount) {
    if (busyId !== null) return;
    setBusyId(account.id);
    setError(null);
    try {
      replaceAccount(
        await updateBankAccount(account.id, { is_archived: !account.is_archived }),
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : tc("error"));
    } finally {
      setBusyId(null);
    }
  }

  async function confirmDelete(account: BankAccount) {
    if (busyId !== null) return;
    setBusyId(account.id);
    setError(null);
    try {
      await deleteBankAccount(account.id);
      setAccounts((prev) => prev.filter((a) => a.id !== account.id));
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
      icon={Landmark}
      title={tc("title")}
      description={tc("description")}
      t={t}
      isCollapsed={isCollapsed}
      onToggle={onToggle}
    >
      <div data-testid="bank-accounts-tile" className="space-y-4">
        {error && (
          <p
            data-testid="bank-account-error"
            className="text-sm text-red-600 dark:text-red-400"
          >
            {error}
          </p>
        )}

        <div className="flex flex-col gap-2 sm:flex-row">
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
            maxLength={100}
            disabled={adding}
            className={inputClass}
          />
          <input
            value={newIban}
            onChange={(e) => setNewIban(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                void handleAdd();
              }
            }}
            placeholder={tc("ibanPlaceholder")}
            aria-label={tc("ibanLabel")}
            maxLength={34}
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
            {sorted.map((account) => {
              const isEditing = editingId === account.id;
              const isDeleting = deleteTargetId === account.id;
              return (
                <li
                  key={account.id}
                  className="flex items-center gap-2 rounded-lg border border-slate-200 px-3 py-2 dark:border-slate-700"
                >
                  {isEditing ? (
                    <div className="flex flex-1 flex-col gap-2">
                      <input
                        value={editName}
                        onChange={(e) => setEditName(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter") {
                            e.preventDefault();
                            void saveEdit(account);
                          } else if (e.key === "Escape") {
                            setEditingId(null);
                          }
                        }}
                        aria-label={tc("rename")}
                        maxLength={100}
                        autoFocus
                        className={inputClass}
                      />
                      <div className="flex gap-2">
                        <input
                          value={editIban}
                          onChange={(e) => setEditIban(e.target.value)}
                          placeholder={tc("ibanPlaceholder")}
                          aria-label={tc("ibanLabel")}
                          maxLength={34}
                          className={inputClass}
                        />
                        <input
                          value={editNote}
                          onChange={(e) => setEditNote(e.target.value)}
                          placeholder={tc("notePlaceholder")}
                          aria-label={tc("noteLabel")}
                          maxLength={255}
                          className={inputClass}
                        />
                      </div>
                      <div className="flex gap-2">
                        <button
                          type="button"
                          onClick={() => void saveEdit(account)}
                          disabled={busyId === account.id || editName.trim() === ""}
                          aria-label={tc("save")}
                          className={iconButton}
                        >
                          {busyId === account.id ? (
                            <Loader2 size={15} className="animate-spin" />
                          ) : (
                            <Check size={15} />
                          )}
                        </button>
                        <button
                          type="button"
                          onClick={() => setEditingId(null)}
                          disabled={busyId === account.id}
                          aria-label={tc("cancel")}
                          className={iconButton}
                        >
                          <X size={15} />
                        </button>
                      </div>
                    </div>
                  ) : isDeleting ? (
                    <>
                      <span className="flex-1 text-sm text-slate-700 dark:text-slate-200">
                        {tc("deleteConfirm", { name: account.name })}
                      </span>
                      <button
                        type="button"
                        onClick={() => void confirmDelete(account)}
                        disabled={busyId === account.id}
                        className="shrink-0 rounded-lg border border-red-600 bg-red-600 px-3 py-1.5 text-sm font-medium text-white shadow-sm transition-all hover:border-red-700 hover:bg-red-700 disabled:opacity-50"
                      >
                        {busyId === account.id ? (
                          <Loader2 size={14} className="animate-spin" />
                        ) : (
                          tc("delete")
                        )}
                      </button>
                      <button
                        type="button"
                        onClick={() => setDeleteTargetId(null)}
                        disabled={busyId === account.id}
                        className={btnNeutral}
                      >
                        {tc("cancel")}
                      </button>
                    </>
                  ) : (
                    <>
                      <span className="flex-1 truncate text-sm text-slate-700 dark:text-slate-200">
                        {bankAccountLabel(account)}
                      </span>
                      {account.is_archived && (
                        <span className="shrink-0 rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-500 dark:bg-slate-700 dark:text-slate-400">
                          {tc("archived")}
                        </span>
                      )}
                      <button
                        type="button"
                        onClick={() => startEdit(account)}
                        aria-label={tc("rename")}
                        className={iconButton}
                      >
                        <Pencil size={14} />
                      </button>
                      <button
                        type="button"
                        onClick={() => void toggleArchive(account)}
                        disabled={busyId === account.id}
                        aria-label={account.is_archived ? tc("unarchive") : tc("archive")}
                        className={iconButton}
                      >
                        {busyId === account.id ? (
                          <Loader2 size={14} className="animate-spin" />
                        ) : account.is_archived ? (
                          <ArchiveRestore size={14} />
                        ) : (
                          <Archive size={14} />
                        )}
                      </button>
                      <button
                        type="button"
                        onClick={() => setDeleteTargetId(account.id)}
                        disabled={busyId === account.id}
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

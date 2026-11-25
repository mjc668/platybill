"use client";

import { useId, useState } from "react";
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
  updateBankAccount,
  type BankAccount,
} from "@/lib/bank-accounts-api";

interface Props {
  accounts: BankAccount[];
  loading: boolean;
  loadError: string | null;
  onAccountsChange: (next: BankAccount[]) => void;
}

const inputClass =
  "w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-base sm:text-sm text-slate-800 placeholder:text-slate-400 transition-colors focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-blue-600 focus:border-blue-500 dark:border-slate-600 dark:bg-slate-700 dark:text-slate-100 dark:focus:border-blue-400";
const btnSave =
  "shrink-0 rounded-lg border border-blue-700 bg-blue-700 px-4 py-2 text-sm font-medium text-white shadow-sm transition-colors hover:border-blue-800 hover:bg-blue-800 focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-blue-600 disabled:opacity-50";
const btnNeutral =
  "shrink-0 rounded-lg border border-slate-200 bg-white px-4 py-2 text-sm font-medium text-slate-600 shadow-sm transition-colors hover:border-slate-300 hover:bg-slate-50 disabled:opacity-50 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-300 dark:hover:bg-slate-700";
const iconButton =
  "shrink-0 rounded-lg p-1.5 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-600 focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-blue-600 disabled:opacity-50 dark:text-slate-500 dark:hover:bg-slate-700 dark:hover:text-slate-300";
const iconButtonDanger =
  "shrink-0 rounded-lg p-1.5 text-slate-400 transition-colors hover:bg-red-50 hover:text-red-500 focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-red-500 disabled:opacity-50 dark:text-slate-500 dark:hover:bg-red-900/20 dark:hover:text-red-400";

export default function AccountListPanel({
  accounts,
  loading,
  loadError,
  onAccountsChange,
}: Props) {
  const t = useTranslations("AccountsPage.list");
  const baseId = useId();

  const [newName, setNewName] = useState("");
  const [newIban, setNewIban] = useState("");
  const [adding, setAdding] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [editingId, setEditingId] = useState<number | null>(null);
  const [editName, setEditName] = useState("");
  const [editIban, setEditIban] = useState("");
  const [editNote, setEditNote] = useState("");
  const [busyId, setBusyId] = useState<number | null>(null);
  const [deleteTargetId, setDeleteTargetId] = useState<number | null>(null);

  const sorted = [...accounts].sort(
    (a, b) =>
      Number(a.is_archived) - Number(b.is_archived) ||
      a.name.localeCompare(b.name, undefined, { sensitivity: "base" }) ||
      a.id - b.id,
  );

  function replaceAccount(updated: BankAccount) {
    onAccountsChange(accounts.map((a) => (a.id === updated.id ? updated : a)));
  }

  async function handleAdd(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const name = newName.trim();
    if (!name || adding) return;
    setAdding(true);
    setError(null);
    try {
      const created = await createBankAccount({
        name,
        iban: newIban.trim() || null,
      });
      onAccountsChange([...accounts, created]);
      setNewName("");
      setNewIban("");
    } catch (err) {
      setError(err instanceof Error ? err.message : t("error"));
    } finally {
      setAdding(false);
    }
  }

  function startEdit(account: BankAccount) {
    setEditingId(account.id);
    setEditName(account.name);
    setEditIban(account.iban ?? "");
    setEditNote(account.note ?? "");
    setDeleteTargetId(null);
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
      setError(err instanceof Error ? err.message : t("error"));
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
      setError(err instanceof Error ? err.message : t("error"));
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
      onAccountsChange(accounts.filter((a) => a.id !== account.id));
      setDeleteTargetId(null);
    } catch (err) {
      setError(
        err instanceof Error && err.message.trim() !== ""
          ? err.message
          : t("deleteBlocked"),
      );
      setDeleteTargetId(null);
    } finally {
      setBusyId(null);
    }
  }

  const displayedError = error ?? loadError;

  return (
    <section
      aria-labelledby={`${baseId}-heading`}
      data-testid="accounts-list-panel"
      className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-700 dark:bg-slate-800"
    >
      <div className="mb-4 flex items-start gap-3">
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-emerald-50 text-emerald-600 dark:bg-emerald-900/30 dark:text-emerald-400">
          <Landmark size={20} aria-hidden="true" />
        </div>
        <div>
          <h2
            id={`${baseId}-heading`}
            className="text-base font-semibold text-slate-800 dark:text-slate-100"
          >
            {t("heading")}
          </h2>
          <p className="text-sm text-slate-500 dark:text-slate-400">
            {t("description")}
          </p>
        </div>
      </div>

      {displayedError && (
        <p
          role="status"
          aria-live="polite"
          data-testid="accounts-list-error"
          className="mb-4 rounded-xl bg-red-50 px-3 py-2 text-sm text-red-600 dark:bg-red-900/20 dark:text-red-400"
        >
          {displayedError}
        </p>
      )}

      <form
        onSubmit={(e) => void handleAdd(e)}
        aria-labelledby={`${baseId}-heading`}
        className="mb-4 grid grid-cols-1 gap-3 sm:grid-cols-[1fr_1fr_auto] sm:items-end"
      >
        <div className="flex flex-col gap-1">
          <label
            htmlFor={`${baseId}-name`}
            className="text-xs font-medium text-slate-600 dark:text-slate-300"
          >
            {t("nameLabel")}
          </label>
          <input
            id={`${baseId}-name`}
            name="name"
            type="text"
            required
            maxLength={100}
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            placeholder={t("namePlaceholder")}
            disabled={adding}
            className={inputClass}
          />
        </div>

        <div className="flex flex-col gap-1">
          <label
            htmlFor={`${baseId}-iban`}
            className="text-xs font-medium text-slate-600 dark:text-slate-300"
          >
            {t("ibanLabel")}
          </label>
          <input
            id={`${baseId}-iban`}
            name="iban"
            type="text"
            maxLength={34}
            value={newIban}
            onChange={(e) => setNewIban(e.target.value)}
            placeholder={t("ibanPlaceholder")}
            disabled={adding}
            className={inputClass}
          />
        </div>

        <button type="submit" disabled={adding} className={btnSave}>
          {adding ? t("adding") : t("add")}
        </button>
      </form>

      {loading ? (
        <div className="h-14 animate-pulse rounded-xl bg-slate-100 dark:bg-slate-700/60" />
      ) : sorted.length === 0 ? (
        <p className="rounded-xl border border-dashed border-slate-200 px-4 py-6 text-center text-sm text-slate-500 dark:border-slate-700 dark:text-slate-400">
          {t("empty")}
        </p>
      ) : (
        <ul className="flex flex-col gap-2">
          {sorted.map((account) => {
            const isEditing = editingId === account.id;
            const isDeleting = deleteTargetId === account.id;
            return (
              <li
                key={account.id}
                className="flex items-center gap-2 rounded-xl border border-slate-200 px-3.5 py-2.5 dark:border-slate-700"
              >
                {isEditing ? (
                  <div className="flex flex-1 flex-col gap-2">
                    <div className="flex flex-col gap-1">
                      <label
                        htmlFor={`${baseId}-edit-name-${account.id}`}
                        className="text-xs font-medium text-slate-600 dark:text-slate-300"
                      >
                        {t("nameLabel")}
                      </label>
                      <input
                        id={`${baseId}-edit-name-${account.id}`}
                        value={editName}
                        onChange={(e) => setEditName(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.nativeEvent.isComposing) return;
                          if (e.key === "Enter") {
                            e.preventDefault();
                            void saveEdit(account);
                          } else if (e.key === "Escape") {
                            setEditingId(null);
                          }
                        }}
                        maxLength={100}
                        autoFocus
                        className={inputClass}
                      />
                    </div>
                    <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                      <input
                        value={editIban}
                        onChange={(e) => setEditIban(e.target.value)}
                        placeholder={t("ibanPlaceholder")}
                        aria-label={t("ibanLabel")}
                        maxLength={34}
                        className={inputClass}
                      />
                      <input
                        value={editNote}
                        onChange={(e) => setEditNote(e.target.value)}
                        placeholder={t("notePlaceholder")}
                        aria-label={t("noteLabel")}
                        maxLength={255}
                        className={inputClass}
                      />
                    </div>
                    <div className="flex gap-2">
                      <button
                        type="button"
                        onClick={() => void saveEdit(account)}
                        disabled={busyId === account.id || editName.trim() === ""}
                        aria-label={t("save")}
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
                        aria-label={t("cancel")}
                        className={iconButton}
                      >
                        <X size={15} />
                      </button>
                    </div>
                  </div>
                ) : isDeleting ? (
                  <>
                    <span className="flex-1 text-sm text-slate-700 dark:text-slate-200">
                      {t("deleteConfirm", { name: account.name })}
                    </span>
                    <button
                      type="button"
                      onClick={() => void confirmDelete(account)}
                      disabled={busyId === account.id}
                      className="shrink-0 rounded-lg border border-red-600 bg-red-600 px-3 py-1.5 text-sm font-medium text-white shadow-sm transition-colors hover:border-red-700 hover:bg-red-700 disabled:opacity-50"
                    >
                      {busyId === account.id ? (
                        <Loader2 size={14} className="animate-spin" />
                      ) : (
                        t("delete")
                      )}
                    </button>
                    <button
                      type="button"
                      onClick={() => setDeleteTargetId(null)}
                      disabled={busyId === account.id}
                      className={btnNeutral}
                    >
                      {t("cancel")}
                    </button>
                  </>
                ) : (
                  <>
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-sm font-medium text-slate-800 dark:text-slate-100">
                        {bankAccountLabel(account)}
                      </div>
                      {account.note && (
                        <div className="truncate text-xs text-slate-500 dark:text-slate-400">
                          {account.note}
                        </div>
                      )}
                    </div>
                    {account.is_archived && (
                      <span className="shrink-0 rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-500 dark:bg-slate-700 dark:text-slate-400">
                        {t("archived")}
                      </span>
                    )}
                    <button
                      type="button"
                      onClick={() => startEdit(account)}
                      aria-label={t("rename")}
                      title={t("rename")}
                      className={iconButton}
                    >
                      <Pencil size={14} />
                    </button>
                    <button
                      type="button"
                      onClick={() => void toggleArchive(account)}
                      disabled={busyId === account.id}
                      aria-label={account.is_archived ? t("unarchive") : t("archive")}
                      title={account.is_archived ? t("unarchive") : t("archive")}
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
                      aria-label={t("delete")}
                      title={t("delete")}
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
    </section>
  );
}

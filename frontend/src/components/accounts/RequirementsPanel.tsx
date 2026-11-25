"use client";

import { useEffect, useId, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  CalendarRange,
  Landmark,
  Loader2,
  Pencil,
  Wallet,
} from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import {
  fetchAccountRequirements,
  type AccountRequirementBucket,
  type AccountRequirementItem,
  type AccountRequirementsOut,
  type BankAccount,
} from "@/lib/bank-accounts-api";
import { confirmInstanceAmount, updatePaymentInstance } from "@/lib/payments-api";

interface Props {
  accounts: BankAccount[];
  refreshToken: number;
}

function toIsoDate(d: Date): string {
  const year = d.getFullYear();
  const month = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function addDays(base: Date, days: number): Date {
  const copy = new Date(base.getFullYear(), base.getMonth(), base.getDate());
  copy.setDate(copy.getDate() + days);
  return copy;
}

function formatDueDate(iso: string, locale: string): string {
  const date = new Date(iso + "T00:00:00");
  const fmt = new Intl.DateTimeFormat(locale, {
    day: "numeric",
    month: "short",
  });
  return fmt
    .formatToParts(date)
    .map(({ type, value }) =>
      type === "month" ? value.charAt(0).toUpperCase() + value.slice(1) : value,
    )
    .join("");
}

function bucketCurrency(bucket: AccountRequirementBucket): string {
  const currencies = new Set(bucket.items.map((item) => item.currency));
  if (currencies.size === 1) {
    return bucket.items[0]?.currency ?? "";
  }
  return "";
}

const controlClass =
  "w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-base sm:text-sm text-slate-800 transition-colors focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-blue-600 focus:border-blue-500 dark:border-slate-600 dark:bg-slate-700 dark:text-slate-100 dark:focus:border-blue-400";

export default function RequirementsPanel({ accounts, refreshToken }: Props) {
  const t = useTranslations("AccountsPage.requirements");
  const locale = useLocale();
  const baseId = useId();

  const [fromDate, setFromDate] = useState<string>(() => toIsoDate(new Date()));
  const [toDate, setToDate] = useState<string>(() => toIsoDate(addDays(new Date(), 7)));
  const [selectedAccount, setSelectedAccount] = useState<string>("all");

  const [data, setData] = useState<AccountRequirementsOut | null>(null);
  const [loadedKey, setLoadedKey] = useState<string>("");
  const [error, setError] = useState<string | null>(null);
  const [reloadCount, setReloadCount] = useState<number>(0);

  const [confirmTarget, setConfirmTarget] = useState<AccountRequirementItem | null>(null);
  const [confirmAmount, setConfirmAmount] = useState<string>("");
  const [confirmError, setConfirmError] = useState<string | null>(null);
  const [confirmSaving, setConfirmSaving] = useState<boolean>(false);

  const [assigningId, setAssigningId] = useState<number | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const rangeInvalid = fromDate !== "" && toDate !== "" && toDate < fromDate;
  const requestKey = `${fromDate}|${toDate}|${refreshToken}|${reloadCount}`;
  const loading = !rangeInvalid && loadedKey !== requestKey;

  useEffect(() => {
    if (rangeInvalid) return;
    let cancelled = false;
    fetchAccountRequirements(fromDate, toDate)
      .then((res) => {
        if (cancelled || !mounted.current) return;
        setData(res);
        setError(null);
        setLoadedKey(requestKey);
      })
      .catch((err: unknown) => {
        if (cancelled || !mounted.current) return;
        setError(err instanceof Error ? err.message : t("loadError"));
        setLoadedKey(requestKey);
      });
    return () => {
      cancelled = true;
    };
  }, [fromDate, toDate, rangeInvalid, requestKey, t]);

  function applyQuickDays(days: number) {
    const today = new Date();
    setFromDate(toIsoDate(today));
    setToDate(toIsoDate(addDays(today, days)));
  }

  const activeAccounts = useMemo(
    () =>
      [...accounts]
        .filter((acc) => !acc.is_archived)
        .sort(
          (a, b) =>
            a.name.localeCompare(b.name, undefined, { sensitivity: "base" }) ||
            a.id - b.id,
        ),
    [accounts],
  );

  const accountOptions = useMemo(() => {
    const seen = new Map<number, string>();
    for (const acc of activeAccounts) {
      seen.set(acc.id, acc.name);
    }
    for (const bucket of data?.buckets ?? []) {
      if (bucket.account_id !== null && !seen.has(bucket.account_id)) {
        seen.set(bucket.account_id, bucket.account_name);
      }
    }
    return [...seen.entries()].sort((a, b) =>
      a[1].localeCompare(b[1], undefined, { sensitivity: "base" }),
    );
  }, [activeAccounts, data]);

  const visibleBuckets = useMemo(() => {
    const buckets = data?.buckets ?? [];
    if (selectedAccount === "all") return buckets;
    if (selectedAccount === "unspecified") {
      return buckets.filter((b) => b.account_id === null);
    }
    const targetId = Number(selectedAccount);
    return buckets.filter((b) => b.account_id === targetId);
  }, [data, selectedAccount]);

  function openConfirmDialog(item: AccountRequirementItem) {
    setConfirmTarget(item);
    setConfirmAmount(item.amount);
    setConfirmError(null);
  }

  async function handleConfirmSave(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!confirmTarget || confirmSaving) return;
    const parsed = parseFloat(confirmAmount);
    if (!Number.isFinite(parsed) || parsed <= 0) {
      setConfirmError(t("invalidAmount"));
      return;
    }
    setConfirmSaving(true);
    setConfirmError(null);
    try {
      await confirmInstanceAmount(confirmTarget.instance_id, confirmAmount.trim());
      if (!mounted.current) return;
      setConfirmTarget(null);
      setReloadCount((n) => n + 1);
    } catch (err) {
      if (!mounted.current) return;
      setConfirmError(err instanceof Error ? err.message : t("saveFailed"));
    } finally {
      if (mounted.current) setConfirmSaving(false);
    }
  }

  async function handleAssignAccount(instanceId: number, rawValue: string) {
    if (assigningId !== null) return;
    const nextAccountId = rawValue === "" ? null : Number(rawValue);
    setAssigningId(instanceId);
    setActionError(null);
    try {
      await updatePaymentInstance(instanceId, { account_id: nextAccountId });
      if (!mounted.current) return;
      setReloadCount((n) => n + 1);
    } catch (err) {
      if (!mounted.current) return;
      setActionError(err instanceof Error ? err.message : t("saveFailed"));
    } finally {
      if (mounted.current) setAssigningId(null);
    }
  }

  const accountSelectId = `${baseId}-account`;
  const fromInputId = `${baseId}-from`;
  const toInputId = `${baseId}-to`;
  const rangeErrorId = `${baseId}-range-error`;

  return (
    <section
      aria-labelledby={`${baseId}-heading`}
      data-testid="requirements-panel"
      className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-700 dark:bg-slate-800"
    >
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-blue-50 text-blue-600 dark:bg-blue-900/30 dark:text-blue-400">
            <CalendarRange size={20} aria-hidden="true" />
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

        <div className="flex flex-wrap items-center gap-1.5">
          {[
            { days: 7, label: t("next7Days") },
            { days: 14, label: t("next14Days") },
            { days: 30, label: t("next30Days") },
          ].map((preset) => (
            <button
              key={preset.days}
              type="button"
              onClick={() => applyQuickDays(preset.days)}
              className="rounded-lg border border-slate-200 bg-slate-50 px-2.5 py-1.5 text-xs font-medium text-slate-600 transition-colors hover:border-blue-300 hover:bg-blue-50 hover:text-blue-700 focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-blue-600 dark:border-slate-600 dark:bg-slate-700/60 dark:text-slate-300 dark:hover:border-blue-700 dark:hover:bg-blue-900/30 dark:hover:text-blue-300"
            >
              {preset.label}
            </button>
          ))}
        </div>
      </div>

      <search className="mb-5">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <div className="flex flex-col gap-1">
            <label
              htmlFor={accountSelectId}
              className="text-xs font-medium text-slate-600 dark:text-slate-300"
            >
              {t("accountFilter")}
            </label>
            <select
              id={accountSelectId}
              name="account"
              value={selectedAccount}
              onChange={(e) => setSelectedAccount(e.target.value)}
              className={controlClass}
            >
              <option value="all">{t("allAccounts")}</option>
              {accountOptions.map(([id, name]) => (
                <option key={id} value={String(id)}>
                  {name}
                </option>
              ))}
              <option value="unspecified">{t("unspecifiedOption")}</option>
            </select>
          </div>

          <div className="flex flex-col gap-1">
            <label
              htmlFor={fromInputId}
              className="text-xs font-medium text-slate-600 dark:text-slate-300"
            >
              {t("fromDate")}
            </label>
            <input
              id={fromInputId}
              name="from"
              type="date"
              value={fromDate}
              aria-invalid={rangeInvalid || undefined}
              aria-describedby={rangeInvalid ? rangeErrorId : undefined}
              onChange={(e) => setFromDate(e.target.value)}
              className={controlClass}
            />
          </div>

          <div className="flex flex-col gap-1">
            <label
              htmlFor={toInputId}
              className="text-xs font-medium text-slate-600 dark:text-slate-300"
            >
              {t("toDate")}
            </label>
            <input
              id={toInputId}
              name="to"
              type="date"
              value={toDate}
              min={fromDate || undefined}
              aria-invalid={rangeInvalid || undefined}
              aria-describedby={rangeInvalid ? rangeErrorId : undefined}
              onChange={(e) => setToDate(e.target.value)}
              className={controlClass}
            />
          </div>
        </div>

        {rangeInvalid && (
          <p
            id={rangeErrorId}
            role="status"
            aria-live="polite"
            className="mt-2 text-sm text-red-600 dark:text-red-400"
          >
            {t("invalidRange")}
          </p>
        )}
      </search>

      {actionError && (
        <p
          role="status"
          aria-live="polite"
          className="mb-3 rounded-xl bg-red-50 px-3 py-2 text-sm text-red-600 dark:bg-red-900/20 dark:text-red-400"
        >
          {actionError}
        </p>
      )}

      {error ? (
        <div
          role="status"
          aria-live="polite"
          className="flex items-center justify-between gap-3 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-900/50 dark:bg-red-900/20 dark:text-red-300"
        >
          <span>{error}</span>
          <button
            type="button"
            onClick={() => setReloadCount((n) => n + 1)}
            className="shrink-0 rounded-lg border border-red-300 bg-white px-3 py-1 text-xs font-medium text-red-700 hover:bg-red-50 dark:border-red-800 dark:bg-slate-800 dark:text-red-300"
          >
            {t("retry")}
          </button>
        </div>
      ) : loading ? (
        <div className="flex flex-col gap-3">
          <div className="h-28 animate-pulse rounded-xl bg-slate-100 dark:bg-slate-700/60" />
          <div className="h-24 animate-pulse rounded-xl bg-slate-100 dark:bg-slate-700/60" />
        </div>
      ) : visibleBuckets.length === 0 ? (
        <div
          data-testid="requirements-empty"
          className="rounded-xl border border-dashed border-slate-200 px-4 py-8 text-center text-sm text-slate-500 dark:border-slate-700 dark:text-slate-400"
        >
          {selectedAccount === "all" ? t("empty") : t("emptyForAccount")}
        </div>
      ) : (
        <div className="flex flex-col gap-4">
          {visibleBuckets.map((bucket) => {
            const isUnspecified = bucket.account_id === null;
            const hasEstimated = parseFloat(bucket.total_estimated) > 0;
            const currency = bucketCurrency(bucket);
            const bucketKey = isUnspecified ? "unspecified" : String(bucket.account_id);

            return (
              <div
                key={bucketKey}
                data-testid={
                  isUnspecified ? "requirements-bucket-unspecified" : "requirements-bucket"
                }
                className={`overflow-hidden rounded-xl border ${
                  isUnspecified
                    ? "border-amber-200 bg-amber-50/40 dark:border-amber-800/60 dark:bg-amber-900/10"
                    : "border-slate-200 bg-slate-50/50 dark:border-slate-700 dark:bg-slate-900/30"
                }`}
              >
                {/* Bucket card header */}
                <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-200/80 px-4 py-3 dark:border-slate-700/80">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      {isUnspecified ? (
                        <AlertTriangle
                          size={16}
                          aria-hidden="true"
                          className="shrink-0 text-amber-600 dark:text-amber-400"
                        />
                      ) : (
                        <Landmark
                          size={16}
                          aria-hidden="true"
                          className="shrink-0 text-emerald-600 dark:text-emerald-400"
                        />
                      )}
                      <h3 className="truncate text-sm font-semibold text-slate-800 dark:text-slate-100">
                        {isUnspecified ? t("unspecifiedTitle") : bucket.account_name}
                      </h3>
                      {isUnspecified && (
                        <span className="rounded-full bg-amber-100 px-2 py-0.5 text-[11px] font-medium text-amber-800 dark:bg-amber-900/40 dark:text-amber-300">
                          {t("unspecifiedBadge")}
                        </span>
                      )}
                      <span className="text-xs text-slate-400 dark:text-slate-500">
                        {t("itemCount", { count: bucket.items.length })}
                      </span>
                    </div>
                    {isUnspecified && (
                      <p className="mt-0.5 text-xs text-amber-700/90 dark:text-amber-300/80">
                        {t("unspecifiedHint")}
                      </p>
                    )}
                  </div>

                  <div className="text-right">
                    <div className="text-xs text-slate-500 dark:text-slate-400">
                      {t("totalDue")}
                    </div>
                    <div className="text-lg font-bold tabular-nums text-slate-900 dark:text-slate-50">
                      {bucket.total_due}
                      {currency ? ` ${currency}` : ""}
                    </div>
                    {hasEstimated && (
                      <div className="text-xs font-medium text-amber-700 dark:text-amber-300">
                        {t("includesEstimated", {
                          amount: `${bucket.total_estimated}${currency ? ` ${currency}` : ""}`,
                        })}
                      </div>
                    )}
                  </div>
                </div>

                {/* Itemised rows */}
                <ul className="divide-y divide-slate-200/70 dark:divide-slate-700/70">
                  {bucket.items.map((item) => {
                    const isEst = item.amount_estimated;
                    return (
                      <li
                        key={item.instance_id}
                        data-testid="requirement-item"
                        data-estimated={isEst ? "true" : "false"}
                        className={`flex flex-wrap items-center justify-between gap-2 px-4 py-2.5 ${
                          isEst
                            ? "bg-amber-50/70 dark:bg-amber-900/15"
                            : "bg-white dark:bg-slate-800/70"
                        }`}
                      >
                        <div className="min-w-0 flex-1">
                          <div className="flex flex-wrap items-center gap-1.5">
                            <span className="truncate text-sm font-medium text-slate-800 dark:text-slate-100">
                              {item.label}
                            </span>
                            {isEst && (
                              <span
                                data-testid="estimate-badge"
                                className="shrink-0 rounded-full border border-dashed border-amber-300 bg-amber-100 px-2 py-0.5 text-[11px] font-medium text-amber-800 dark:border-amber-700 dark:bg-amber-900/40 dark:text-amber-300"
                              >
                                {t("estimatedBadge")}
                              </span>
                            )}
                          </div>
                          <div className="text-xs text-slate-500 dark:text-slate-400">
                            {t("due", { date: formatDueDate(item.due_date, locale) })}
                          </div>
                        </div>

                        <div className="flex flex-wrap items-center gap-2">
                          <span
                            className={`text-sm tabular-nums ${
                              isEst
                                ? "font-medium italic text-amber-800 dark:text-amber-300"
                                : "font-semibold text-slate-800 dark:text-slate-100"
                            }`}
                          >
                            {isEst ? `~${item.amount}` : item.amount} {item.currency}
                          </span>

                          {isEst && (
                            <button
                              type="button"
                              onClick={() => openConfirmDialog(item)}
                              className="flex items-center gap-1 rounded-lg border border-amber-300 bg-amber-50 px-2.5 py-1 text-xs font-semibold text-amber-800 shadow-xs transition-colors hover:border-amber-400 hover:bg-amber-100 focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-amber-600 dark:border-amber-700 dark:bg-amber-900/30 dark:text-amber-300 dark:hover:bg-amber-900/50"
                            >
                              <Pencil size={12} aria-hidden="true" />
                              <span>{t("confirmAmount")}</span>
                            </button>
                          )}

                          {activeAccounts.length > 0 && (
                            <div className="flex items-center gap-1">
                              <Wallet
                                size={13}
                                aria-hidden="true"
                                className="text-slate-400 dark:text-slate-500"
                              />
                              <select
                                aria-label={t("assignAccountLabel", {
                                  label: item.label,
                                })}
                                value={
                                  bucket.account_id !== null
                                    ? String(bucket.account_id)
                                    : ""
                                }
                                disabled={assigningId === item.instance_id}
                                onChange={(e) =>
                                  void handleAssignAccount(
                                    item.instance_id,
                                    e.target.value,
                                  )
                                }
                                className="max-w-36 rounded-lg border border-slate-200 bg-white px-2 py-1 text-xs text-slate-700 focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-blue-600 disabled:opacity-50 dark:border-slate-600 dark:bg-slate-700 dark:text-slate-200"
                              >
                                <option value="">{t("unassigned")}</option>
                                {activeAccounts.map((acc) => (
                                  <option key={acc.id} value={String(acc.id)}>
                                    {acc.name}
                                  </option>
                                ))}
                              </select>
                              {assigningId === item.instance_id && (
                                <Loader2
                                  size={13}
                                  aria-hidden="true"
                                  className="animate-spin text-blue-600"
                                />
                              )}
                            </div>
                          )}
                        </div>
                      </li>
                    );
                  })}
                </ul>
              </div>
            );
          })}
        </div>
      )}

      {/* Confirm estimate dialog */}
      {confirmTarget && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 px-4 backdrop-blur-sm">
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby={`${baseId}-confirm-title`}
            onKeyDown={(e) => e.key === "Escape" && setConfirmTarget(null)}
            className="w-full max-w-sm rounded-2xl border border-slate-200 bg-white p-6 shadow-xl dark:border-slate-700 dark:bg-slate-800"
          >
            <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300">
              <Pencil size={20} aria-hidden="true" />
            </div>
            <h3
              id={`${baseId}-confirm-title`}
              className="mb-1 text-lg font-semibold text-slate-800 dark:text-slate-100"
            >
              {t("confirmDialogTitle", { label: confirmTarget.label })}
            </h3>
            <p className="mb-4 text-sm text-slate-500 dark:text-slate-400">
              {t("confirmDialogDescription")}
            </p>

            <form
              onSubmit={(e) => void handleConfirmSave(e)}
              aria-labelledby={`${baseId}-confirm-title`}
            >
              <label
                htmlFor={`${baseId}-confirm-amount`}
                className="mb-1 block text-sm font-medium text-slate-700 dark:text-slate-300"
              >
                {t("amountLabel", { currency: confirmTarget.currency })}
              </label>
              <input
                id={`${baseId}-confirm-amount`}
                name="amount"
                type="text"
                inputMode="decimal"
                required
                autoFocus
                value={confirmAmount}
                onChange={(e) => {
                  setConfirmAmount(e.target.value);
                  if (confirmError) setConfirmError(null);
                }}
                className={controlClass}
              />

              {confirmError && (
                <p
                  role="status"
                  aria-live="polite"
                  className="mt-2 text-sm text-red-600 dark:text-red-400"
                >
                  {confirmError}
                </p>
              )}

              <div className="mt-6 flex gap-3">
                <button
                  type="button"
                  onClick={() => setConfirmTarget(null)}
                  disabled={confirmSaving}
                  className="flex-1 rounded-xl border border-slate-200 bg-white py-2.5 text-sm font-medium text-slate-700 shadow-sm transition-colors hover:border-slate-300 hover:bg-slate-50 disabled:opacity-50 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-300 dark:hover:bg-slate-700"
                >
                  {t("cancel")}
                </button>
                <button
                  type="submit"
                  disabled={confirmSaving}
                  className="flex-1 rounded-xl border border-blue-700 bg-blue-700 py-2.5 text-sm font-medium text-white shadow-sm transition-colors hover:border-blue-800 hover:bg-blue-800 disabled:opacity-50"
                >
                  {confirmSaving ? t("saving") : t("save")}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </section>
  );
}

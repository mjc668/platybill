"use client";

import { FormEvent, useState } from "react";
import { useTranslations, useLocale } from "next-intl";
import CategoryCombobox from "./CategoryCombobox";
import MonthDayCalendar from "./MonthDayCalendar";
import type { Category } from "@/lib/categories-api";
import type { BankAccount } from "@/lib/bank-accounts-api";
import {
  normalizeBillFrequency,
  type BillFrequency,
  type BillTemplateCreate,
} from "@/lib/bills-api";

const PRESET_CURRENCIES = ["EUR", "PLN", "USD", "AUD"] as const;

const FREQUENCY_VALUES: BillFrequency[] = ["weekly", "monthly", "annual", "one_off"];

const INTERVAL_MAX: Record<Exclude<BillFrequency, "one_off">, number> = {
  weekly: 4,
  monthly: 12,
  annual: 5,
};

const LEGACY_INTERVALS: Record<string, number> = {
  every_2_months: 2,
  quarterly: 3,
};

const DEFAULT_MAX_OCCURRENCES = 12;
const MAX_OCCURRENCES_LIMIT = 999;

function parseMaxOccurrences(value: string): number | null {
  const trimmed = value.trim();
  if (!trimmed) return null;
  const parsed = Number(trimmed);
  if (!Number.isInteger(parsed) || parsed < 1 || parsed > MAX_OCCURRENCES_LIMIT) return null;
  return parsed;
}

function clampInterval(frequency: BillFrequency, value: number): number {
  if (frequency === "one_off") return 1;
  if (!Number.isFinite(value) || value < 1) return 1;
  return Math.min(Math.trunc(value), INTERVAL_MAX[frequency]);
}

function todayIso(): string {
  const now = new Date();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${now.getFullYear()}-${month}-${day}`;
}

const LOCALE_DEFAULT_CURRENCY: Record<string, string> = {
  pl: "PLN",
  de: "EUR",
  en: "USD",
};

type CurrencyOption = (typeof PRESET_CURRENCIES)[number] | "custom";

interface Props {
  initial?: Partial<BillTemplateCreate>;
  /** Category of the edited bill — may be archived and absent from `categories`. */
  initialCategory?: Category;
  /** Account of the edited bill — may be archived and absent from `bankAccounts`. */
  initialAccount?: BankAccount | null;
  /** Non-archived categories offered by the picker. */
  categories: Category[];
  onCategoryCreated: (category: Category) => void;
  /** Non-archived bank accounts offered by the picker. */
  bankAccounts: BankAccount[];
}

interface Errors {
  name?: string;
  amount?: string;
  start_date?: string;
  category?: string;
  max_occurrences?: string;
}

const inputClass =
  "w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm text-slate-800 outline-none transition-all focus:border-blue-500 focus:ring-2 focus:ring-blue-100 dark:bg-slate-800 dark:border-slate-600 dark:text-slate-100 dark:focus:border-blue-600 dark:focus:ring-blue-900/40";

const labelClass = "block text-xs font-semibold uppercase tracking-wide text-slate-400 dark:text-slate-500 mb-1.5";

export default function BillTemplateForm({
  initial,
  initialCategory,
  initialAccount,
  categories,
  onCategoryCreated,
  bankAccounts,
  defaultCurrency,
  onSave,
  onCancel,
}: Props) {
  const t = useTranslations("BillTemplateForm");
  const locale = useLocale();
  const [name, setName] = useState(initial?.name ?? "");
  const [category, setCategory] = useState<Category | null>(
    initialCategory ??
      categories.find((c) => c.id === initial?.category_id) ??
      null,
  );
  const [account, setAccount] = useState<BankAccount | null>(
    initialAccount ??
      bankAccounts.find((a) => a.id === initial?.preferred_account_id) ??
      null,
  );
  const [frequency, setFrequency] = useState<BillFrequency>(
    normalizeBillFrequency(initial?.frequency),
  );
  const [intervalCount, setIntervalCount] = useState<number>(() => {
    const legacyInterval = LEGACY_INTERVALS[initial?.frequency ?? ""];
    return clampInterval(
      normalizeBillFrequency(initial?.frequency),
      initial?.interval_count ?? legacyInterval ?? 1,
    );
  });
  const [limitedPayments, setLimitedPayments] = useState(initial?.max_occurrences != null);
  const [maxOccurrences, setMaxOccurrences] = useState(
    initial?.max_occurrences != null
      ? String(initial.max_occurrences)
      : String(DEFAULT_MAX_OCCURRENCES),
  );
  const [startDate, setStartDate] = useState(initial?.start_date ?? todayIso());
  const [amount, setAmount] = useState(initial?.amount ?? "");
  const initialCurrency =
    initial?.currency ?? defaultCurrency ?? LOCALE_DEFAULT_CURRENCY[locale] ?? "EUR";
  const isPreset = (PRESET_CURRENCIES as readonly string[]).includes(initialCurrency);
  const [currencyOption, setCurrencyOption] = useState<CurrencyOption>(
    isPreset ? (initialCurrency as CurrencyOption) : "custom",
  );
  const [customCurrency, setCustomCurrency] = useState(isPreset ? "" : initialCurrency);
  const [dueDay, setDueDay] = useState(
    initial?.due_day != null ? String(initial.due_day) : String(new Date().getDate()),
  );
  const [dueMonth, setDueMonth] = useState(
    initial?.due_month != null ? String(initial.due_month) : String(new Date().getMonth() + 1),
  );
  const [notes, setNotes] = useState(initial?.notes ?? "");
  const [isPaused, setIsPaused] = useState(initial?.is_paused ?? false);
  const [amountVaries, setAmountVaries] = useState(initial?.amount_varies ?? false);
  const [errors, setErrors] = useState<Errors>({});
  const [submitAttempted, setSubmitAttempted] = useState(false);
  const [saving, setSaving] = useState(false);
  const [apiError, setApiError] = useState<string | null>(null);

  function validate(fields: {
    name: string;
    amount: string;
    category: Category | null;
    frequency: BillFrequency;
    startDate: string;
    limitedPayments: boolean;
    maxOccurrences: string;
  }): Errors {
    const e: Errors = {};
    if (!fields.name.trim()) e.name = t("nameRequired");
    if (fields.amount.trim() && isNaN(Number(fields.amount.trim().replace(",", "."))))
      e.amount = t("amountInvalid");
    if (!fields.category) e.category = t("categoryRequired");
    if (fields.frequency === "weekly" && !fields.startDate)
      e.start_date = t("startDateRequired");
    if (
      fields.frequency !== "one_off" &&
      fields.limitedPayments &&
      parseMaxOccurrences(fields.maxOccurrences) === null
    )
      e.max_occurrences = t("maxOccurrencesInvalid");
    return e;
  }

  function revalidate(
    overrides: Partial<{
      name: string;
      amount: string;
      category: Category | null;
      frequency: BillFrequency;
      startDate: string;
      limitedPayments: boolean;
      maxOccurrences: string;
    }>,
  ) {
    if (submitAttempted) {
      setErrors(
        validate({
          name,
          amount,
          category,
          frequency,
          startDate,
          limitedPayments,
          maxOccurrences,
          ...overrides,
        }),
      );
    }
  }

  function handleNameChange(v: string) { setName(v); revalidate({ name: v }); }
  function handleAmountChange(v: string) { setAmount(v); revalidate({ amount: v }); }
  function handleCategoryChange(v: Category | null) { setCategory(v); revalidate({ category: v }); }
  function handleFrequencyChange(v: BillFrequency) {
    setFrequency(v);
    setIntervalCount((count) => clampInterval(v, count));
    revalidate({ frequency: v });
  }
  function handleIntervalChange(v: string) {
    setIntervalCount(clampInterval(frequency, Number(v)));
  }
  function handleStartDateChange(v: string) {
    setStartDate(v);
    revalidate({ startDate: v });
  }
  function handleLimitedPaymentsChange(checked: boolean) {
    setLimitedPayments(checked);
    revalidate({ limitedPayments: checked });
  }
  function handleMaxOccurrencesChange(v: string) {
    setMaxOccurrences(v);
    revalidate({ maxOccurrences: v });
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setSubmitAttempted(true);
    const errs = validate({
      name,
      amount,
      category,
      frequency,
      startDate,
      limitedPayments,
      maxOccurrences,
    });
    setErrors(errs);
    if (Object.keys(errs).length > 0 || category === null) return;

    setSaving(true);
    setApiError(null);
    try {
      const resolvedCurrency =
        currencyOption === "custom" ? customCurrency.trim().toUpperCase() : currencyOption;
      const isWeekly = frequency === "weekly";
      const payload: BillTemplateCreate = {
        name: name.trim(),
        category_id: category.id,
        preferred_account_id: account?.id ?? null,
        frequency,
        interval_count: frequency === "one_off" ? 1 : intervalCount,
        max_occurrences:
          frequency === "one_off" || !limitedPayments
            ? null
            : parseMaxOccurrences(maxOccurrences),
        start_date: isWeekly ? startDate : null,
        amount: amount.trim() || "0",
        amount_varies: frequency === "one_off" ? false : amountVaries,
        currency: resolvedCurrency || "EUR",
        due_day: isWeekly || !dueDay ? null : parseInt(dueDay, 10),
        due_month: isWeekly || !dueMonth ? null : parseInt(dueMonth, 10),
        notes: notes.trim() || null,
        is_paused: isPaused,
      };
      await onSave(payload);
    } catch (err) {
      setApiError(err instanceof Error ? err.message : t("saveFailed"));
    } finally {
      setSaving(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-5">
      {apiError && (
        <div className="rounded-xl bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700 dark:bg-red-900/20 dark:border-red-800 dark:text-red-400">
          {apiError}
        </div>
      )}

      {/* Row 1: Name + Amount */}
      <div className="grid gap-4 sm:grid-cols-2">
        <div>
          <label htmlFor="bill-name" className={labelClass}>
            {t("nameLabel")} <span className="text-red-400">*</span>
          </label>
          <input
            id="bill-name"
            value={name}
            onChange={(e) => handleNameChange(e.target.value)}
            placeholder={t("namePlaceholder")}
            className={inputClass}
          />
          {errors.name && <p className="mt-1 text-xs text-red-500">{errors.name}</p>}
        </div>

        <div>
          <label htmlFor="bill-amount" className={labelClass}>{t("amountLabel")}</label>
          <div className="flex gap-2">
            <input
              id="bill-amount"
              value={amount}
              onChange={(e) => handleAmountChange(e.target.value)}
              placeholder="0.00"
              inputMode="decimal"
              className={inputClass}
            />
            <select
              aria-label={t("currencyAriaLabel")}
              value={currencyOption}
              onChange={(e) => setCurrencyOption(e.target.value as CurrencyOption)}
              className="w-28 shrink-0 rounded-xl border border-slate-200 bg-white px-2 py-2.5 text-sm text-slate-800 outline-none transition-all focus:border-blue-500 focus:ring-2 focus:ring-blue-100 dark:bg-slate-800 dark:border-slate-600 dark:text-slate-100 dark:focus:border-blue-600 dark:focus:ring-blue-900/40"
            >
              {PRESET_CURRENCIES.map((c) => (
                <option key={c} value={c}>{c}</option>
              ))}
              <option value="custom">{t("customOption")}</option>
            </select>
          </div>
          {currencyOption === "custom" && (
            <input
              aria-label={t("customCurrencyAriaLabel")}
              value={customCurrency}
              onChange={(e) => setCustomCurrency(e.target.value)}
              placeholder={t("customCurrencyPlaceholder")}
              maxLength={10}
              className={inputClass + " mt-2"}
            />
          )}
          {errors.amount && <p className="mt-1 text-xs text-red-500">{errors.amount}</p>}
        </div>
      </div>

      {/* Row 2: Frequency unit pills + interval dropdown */}
      <div>
        <label className={labelClass}>
          {t("frequencyLabel")} <span className="text-red-400">*</span>
        </label>
        <div className="flex flex-wrap items-center gap-2">
          {FREQUENCY_VALUES.map((v) => (
            <button
              key={v}
              type="button"
              onClick={() => handleFrequencyChange(v)}
              className={`rounded-lg border px-3 py-1.5 text-sm font-medium transition-all ${
                frequency === v
                  ? "border-blue-600 bg-blue-50 text-blue-700 shadow-sm dark:border-blue-600 dark:bg-blue-900/30 dark:text-blue-400"
                  : "border-slate-200 bg-white text-slate-600 hover:border-blue-300 hover:bg-blue-50 hover:text-blue-700 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-400 dark:hover:border-blue-700 dark:hover:text-blue-400"
              }`}
            >
              {t(`frequency.${v}` as never)}
            </button>
          ))}
          {frequency !== "one_off" && (
            <>
              <span className="ml-1 text-sm text-slate-500 dark:text-slate-400">
                {t("everyLabel")}
              </span>
              <select
                aria-label={t("intervalAriaLabel")}
                value={intervalCount}
                onChange={(e) => handleIntervalChange(e.target.value)}
                className="shrink-0 rounded-lg border border-slate-200 bg-white px-2 py-1.5 text-sm text-slate-800 outline-none transition-all focus:border-blue-500 focus:ring-2 focus:ring-blue-100 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-100 dark:focus:border-blue-600 dark:focus:ring-blue-900/40"
              >
                {Array.from({ length: INTERVAL_MAX[frequency] }, (_, i) => i + 1).map((n) => (
                  <option key={n} value={n}>{n}</option>
                ))}
              </select>
              <span className="text-sm text-slate-500 dark:text-slate-400">
                {t(`intervalUnit.${frequency}`, { count: intervalCount })}
              </span>
            </>
          )}
        </div>

        {frequency !== "one_off" && (
          <div className="mt-3">
            <label className="flex cursor-pointer items-center gap-2.5 text-sm text-slate-600 dark:text-slate-400">
              <input
                type="checkbox"
                checked={limitedPayments}
                onChange={(e) => handleLimitedPaymentsChange(e.target.checked)}
                className="h-4 w-4 rounded accent-blue-700"
              />
              {t("setNumberOfPayments")}
            </label>
            {limitedPayments && (
              <div className="mt-2 max-w-[12rem]">
                <label htmlFor="bill-max-occurrences" className={labelClass}>
                  {t("numberOfPaymentsLabel")}
                </label>
                <input
                  id="bill-max-occurrences"
                  type="number"
                  min={1}
                  max={MAX_OCCURRENCES_LIMIT}
                  value={maxOccurrences}
                  onChange={(e) => handleMaxOccurrencesChange(e.target.value)}
                  className={inputClass}
                />
                {errors.max_occurrences && (
                  <p className="mt-1 text-xs text-red-500">{errors.max_occurrences}</p>
                )}
              </div>
            )}
          </div>
        )}
      </div>

      {/* Row 3: Date picker — weekly uses a native date input, others the calendar */}
      <div>
        <label
          className={labelClass}
          htmlFor={frequency === "weekly" ? "bill-start-date" : undefined}
        >
          {frequency === "weekly"
            ? t("firstPaymentDateLabel")
            : frequency === "one_off"
              ? t("dueDateLabel")
              : t("startDateLabel")}
        </label>
        {frequency === "weekly" ? (
          <>
            <input
              id="bill-start-date"
              type="date"
              value={startDate}
              onChange={(e) => handleStartDateChange(e.target.value)}
              required
              className={inputClass}
            />
            {errors.start_date && (
              <p className="mt-1 text-xs text-red-500">{errors.start_date}</p>
            )}
          </>
        ) : (
          <MonthDayCalendar
            month={parseInt(dueMonth, 10) || new Date().getMonth() + 1}
            day={parseInt(dueDay, 10) || new Date().getDate()}
            onChange={(m, d) => { setDueMonth(String(m)); setDueDay(String(d)); }}
          />
        )}
      </div>

      {/* Row 4: Category + Notes */}
      <div className="grid gap-4 sm:grid-cols-2">
        <div>
          <label htmlFor="bill-category" className={labelClass}>{t("categoryLabel")}</label>
          <CategoryCombobox
            id="bill-category"
            value={category}
            categories={categories}
            onChange={handleCategoryChange}
            onCreated={onCategoryCreated}
          />
          {errors.category && <p className="mt-1 text-xs text-red-500">{errors.category}</p>}
        </div>
        <div>
          <label htmlFor="bill-account" className={labelClass}>{t("accountLabel")}</label>
          <select
            id="bill-account"
            value={account?.id ?? ""}
            onChange={(e) => {
              const id = e.target.value === "" ? null : Number(e.target.value);
              setAccount(bankAccounts.find((a) => a.id === id) ?? null);
            }}
            className={inputClass}
          >
            <option value="">{t("accountNone")}</option>
            {initialAccount && !bankAccounts.some((a) => a.id === initialAccount.id) && (
              <option value={initialAccount.id}>{initialAccount.name}</option>
            )}
            {bankAccounts.map((a) => (
              <option key={a.id} value={a.id}>{a.name}</option>
            ))}
          </select>
        </div>
      </div>

      {/* Row 5: Notes */}
      <div>
        <label htmlFor="bill-notes" className={labelClass}>{t("notesLabel")}</label>
        <textarea
          id="bill-notes"
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          rows={2}
          placeholder={t("notesPlaceholder")}
          className={inputClass + " resize-none"}
        />
      </div>

      {/* Amount-varies toggle. One-off bills are single known charges, so
          the toggle is hidden for them (and the payload forces it off).
          The hint sits outside the label so the checkbox's accessible name
          stays short ("Usage-based bill") and doesn't collide with the
          Amount field's label. */}
      {frequency !== "one_off" && (
        <div>
          <label className="flex cursor-pointer items-center gap-2.5 text-sm text-slate-600 dark:text-slate-400">
            <input
              type="checkbox"
              checked={amountVaries}
              onChange={(e) => setAmountVaries(e.target.checked)}
              className="h-4 w-4 rounded accent-blue-700"
            />
            {t("amountVariesLabel")}
          </label>
          <p className="ml-6.5 mt-1 text-xs text-slate-400 dark:text-slate-500">
            {t("amountVariesHint")}
          </p>
        </div>
      )}

      {/* Paused toggle */}
      <label className="flex cursor-pointer items-center gap-2.5 text-sm text-slate-600 dark:text-slate-400">
        <input
          type="checkbox"
          checked={isPaused}
          onChange={(e) => setIsPaused(e.target.checked)}
          className="h-4 w-4 rounded accent-blue-700"
        />
        {t("pauseRecurrence")}
      </label>

      <div className="flex justify-end gap-3 border-t border-slate-100 pt-4 dark:border-slate-700">
        <button
          type="button"
          onClick={onCancel}
          className="rounded-xl border border-slate-200 bg-white px-4 py-2 text-sm font-medium text-slate-600 shadow-sm transition-all hover:border-slate-300 hover:bg-slate-50 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-400 dark:hover:bg-slate-700"
        >
          {t("cancel")}
        </button>
        <button
          type="submit"
          disabled={saving}
          className="rounded-xl border border-blue-700 bg-blue-700 px-5 py-2 text-sm font-medium text-white shadow-sm transition-all hover:border-blue-800 hover:bg-blue-800 disabled:opacity-50"
        >
          {saving ? t("saving") : t("save")}
        </button>
      </div>
    </form>
  );
}

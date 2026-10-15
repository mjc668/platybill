"use client";

import { User } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import {
  changeEmail,
  changePassword,
  updateMe,
  type UserProfile,
} from "@/lib/user-api";
import { Tile } from "./Tile";

const CURRENCY_PRESETS = ["PLN", "EUR", "USD", "AUD"] as const;

function timezoneOptions(): string[] {
  const intl = Intl as unknown as {
    supportedValuesOf?: (key: "timeZone") => string[];
  };
  try {
    const values = intl.supportedValuesOf?.("timeZone");
    if (values && values.length > 0) return values;
  } catch {
    // Older browsers: fall through to a short curated list.
  }
  return [
    "UTC",
    "Australia/Sydney",
    "Europe/London",
    "Europe/Warsaw",
    "Europe/Berlin",
    "America/New_York",
    "America/Los_Angeles",
  ];
}

type CurrencyChoice = (typeof CURRENCY_PRESETS)[number] | "custom" | "none";

function deriveCurrencyState(value: string | null | undefined): {
  choice: CurrencyChoice;
  custom: string;
} {
  const currency = value ?? "";
  if (!currency) return { choice: "none", custom: "" };
  if ((CURRENCY_PRESETS as readonly string[]).includes(currency)) {
    return { choice: currency as CurrencyChoice, custom: "" };
  }
  return { choice: "custom", custom: currency };
}

const inputClass =
  "w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-800 placeholder:text-slate-400 outline-none transition-all focus:border-blue-500 focus:ring-2 focus:ring-blue-100 dark:border-slate-600 dark:bg-slate-700 dark:text-slate-100 dark:focus:border-blue-600 dark:focus:ring-blue-900/40";

const btnSave =
  "rounded-lg border border-blue-700 bg-blue-700 px-4 py-1.5 text-sm font-medium text-white shadow-sm transition-all hover:border-blue-800 hover:bg-blue-800 disabled:opacity-50";
const btnCancel =
  "rounded-lg border border-slate-200 bg-white px-4 py-1.5 text-sm font-medium text-slate-600 shadow-sm transition-all hover:border-slate-300 hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-300 dark:hover:bg-slate-700";

export function ProfileTile({
  profile,
  onProfileUpdate,
  onDirtyChange,
  t,
  isCollapsed,
  onToggle,
}: {
  profile: UserProfile;
  onProfileUpdate: (p: UserProfile) => void;
  onDirtyChange: (dirty: boolean) => void;
  t: ReturnType<typeof useTranslations>;
  isCollapsed?: boolean;
  onToggle?: () => void;
}) {
  const tp = useTranslations("SettingsPage");

  const [emailInput, setEmailInput] = useState("");
  const [emailPassword, setEmailPassword] = useState("");
  const [emailError, setEmailError] = useState<string | null>(null);
  const [isEmailSaving, setIsEmailSaving] = useState(false);

  const [curPassword, setCurPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [passwordError, setPasswordError] = useState<string | null>(null);
  const [isPasswordSaving, setIsPasswordSaving] = useState(false);

  const initialCurrency = deriveCurrencyState(profile.default_currency);
  const [currencyChoice, setCurrencyChoice] = useState<CurrencyChoice>(initialCurrency.choice);
  const [customCurrency, setCustomCurrency] = useState(initialCurrency.custom);
  const [currencyError, setCurrencyError] = useState<string | null>(null);
  const [isCurrencySaving, setIsCurrencySaving] = useState(false);

  const [timezone, setTimezone] = useState(profile.timezone ?? "");
  const [timezoneError, setTimezoneError] = useState<string | null>(null);
  const [isTimezoneSaving, setIsTimezoneSaving] = useState(false);
  const tzOptions = useMemo(() => {
    const base = timezoneOptions();
    if (profile.timezone && !base.includes(profile.timezone)) {
      return [profile.timezone, ...base];
    }
    return base;
  }, [profile.timezone]);

  const resolvedCurrency =
    currencyChoice === "none"
      ? ""
      : currencyChoice === "custom"
        ? customCurrency.trim().toUpperCase()
        : currencyChoice;
  const isCurrencyDirty = resolvedCurrency !== (profile.default_currency ?? "");

  const isEmailDirty = emailInput.length > 0 || emailPassword.length > 0;
  const isPasswordDirty = curPassword.length > 0 || newPassword.length > 0;
  const isTimezoneDirty = timezone !== (profile.timezone ?? "");
  const isDirty = isEmailDirty || isPasswordDirty || isCurrencyDirty || isTimezoneDirty;

  useEffect(() => {
    onDirtyChange(isDirty);
  }, [isDirty, onDirtyChange]);

  async function saveEmail() {
    if (!emailInput || !emailPassword) {
      setEmailError(tp("profile.emailAndPasswordRequired"));
      return;
    }
    setEmailError(null);
    setIsEmailSaving(true);
    try {
      const updated = await changeEmail(emailInput, emailPassword);
      onProfileUpdate(updated);
      setEmailInput("");
      setEmailPassword("");
    } catch (err) {
      const msg = err instanceof Error ? err.message : "";
      setEmailError(
        msg.includes("already registered")
          ? tp("profile.emailTaken")
          : tp("profile.wrongPassword"),
      );
    } finally {
      setIsEmailSaving(false);
    }
  }

  async function savePassword() {
    if (newPassword.length < 8) {
      setPasswordError(tp("profile.passwordTooShort"));
      return;
    }
    setPasswordError(null);
    setIsPasswordSaving(true);
    try {
      await changePassword(curPassword, newPassword);
      setCurPassword("");
      setNewPassword("");
    } catch {
      setPasswordError(tp("profile.wrongPassword"));
    } finally {
      setIsPasswordSaving(false);
    }
  }

  function cancelCurrency() {
    const derived = deriveCurrencyState(profile.default_currency);
    setCurrencyChoice(derived.choice);
    setCustomCurrency(derived.custom);
    setCurrencyError(null);
  }

  async function saveCurrency() {
    if (currencyChoice === "custom" && !/^[A-Z0-9]{2,10}$/.test(resolvedCurrency)) {
      setCurrencyError(tp("profile.defaultCurrencyInvalid"));
      return;
    }
    setCurrencyError(null);
    setIsCurrencySaving(true);
    try {
      const updated = await updateMe({
        default_currency: resolvedCurrency || null,
      });
      onProfileUpdate(updated);
      const derived = deriveCurrencyState(updated.default_currency);
      setCurrencyChoice(derived.choice);
      setCustomCurrency(derived.custom);
    } catch {
      setCurrencyError(tp("profile.defaultCurrencySaveFailed"));
    } finally {
      setIsCurrencySaving(false);
    }
  }

  async function saveTimezone() {
    setTimezoneError(null);
    setIsTimezoneSaving(true);
    try {
      const updated = await updateMe({ timezone: timezone || null });
      onProfileUpdate(updated);
      setTimezone(updated.timezone ?? "");
    } catch {
      setTimezoneError(tp("profile.timezoneSaveFailed"));
    } finally {
      setIsTimezoneSaving(false);
    }
  }

  return (
    <Tile
      color="blue"
      icon={User}
      title={tp("profile.title")}
      description={tp("profile.description")}
      t={t}
      isCollapsed={isCollapsed}
      onToggle={onToggle}
    >
      <p className="text-sm text-slate-500 dark:text-slate-400">
        <span className="text-slate-400 dark:text-slate-500">{tp("profile.currentEmailLabel")} </span>
        {profile.email}
      </p>

      <div className="space-y-2">
        <label className="block text-sm font-medium text-slate-700 dark:text-slate-300">
          {tp("profile.emailLabel")}
        </label>
        <p className="text-xs text-slate-400 dark:text-slate-500">{tp("profile.emailHint")}</p>
        <input
          type="email"
          value={emailInput}
          onChange={(e) => setEmailInput(e.target.value)}
          placeholder={tp("profile.emailPlaceholder")}
          className={inputClass}
        />
        <input
          type="password"
          value={emailPassword}
          onChange={(e) => setEmailPassword(e.target.value)}
          placeholder={tp("profile.currentPasswordPlaceholder")}
          className={inputClass}
        />
        {emailError && (
          <p className="text-sm text-red-600 dark:text-red-400">{emailError}</p>
        )}
        {isEmailDirty && (
          <div className="flex gap-2 pt-1">
            <button onClick={saveEmail} disabled={isEmailSaving} className={btnSave}>
              {isEmailSaving ? tp("saving") : tp("save")}
            </button>
            <button
              onClick={() => { setEmailInput(""); setEmailPassword(""); setEmailError(null); }}
              disabled={isEmailSaving}
              className={btnCancel}
            >
              {tp("cancel")}
            </button>
          </div>
        )}
      </div>

      <hr className="border-slate-200 dark:border-slate-700" />

      <div className="space-y-2">
        <label className="block text-sm font-medium text-slate-700 dark:text-slate-300">
          {tp("profile.newPasswordLabel")}
        </label>
        <p className="text-xs text-slate-400 dark:text-slate-500">{tp("profile.passwordHint")}</p>
        <input
          type="password"
          value={curPassword}
          onChange={(e) => setCurPassword(e.target.value)}
          placeholder={tp("profile.currentPasswordPlaceholder")}
          className={inputClass}
        />
        <input
          type="password"
          value={newPassword}
          onChange={(e) => setNewPassword(e.target.value)}
          placeholder={tp("profile.newPasswordPlaceholder")}
          className={inputClass}
        />
        {passwordError && (
          <p className="text-sm text-red-600 dark:text-red-400">{passwordError}</p>
        )}
        {isPasswordDirty && (
          <div className="flex gap-2 pt-1">
            <button onClick={savePassword} disabled={isPasswordSaving} className={btnSave}>
              {isPasswordSaving ? tp("saving") : tp("save")}
            </button>
            <button
              onClick={() => { setCurPassword(""); setNewPassword(""); setPasswordError(null); }}
              disabled={isPasswordSaving}
              className={btnCancel}
            >
              {tp("cancel")}
            </button>
          </div>
        )}
      </div>

      <hr className="border-slate-200 dark:border-slate-700" />

      <div className="space-y-2">
        <label
          htmlFor="default-currency"
          className="block text-sm font-medium text-slate-700 dark:text-slate-300"
        >
          {tp("profile.defaultCurrencyLabel")}
        </label>
        <p className="text-xs text-slate-400 dark:text-slate-500">
          {tp("profile.defaultCurrencyHint")}
        </p>
        <div className="flex gap-2">
          <select
            id="default-currency"
            value={currencyChoice}
            onChange={(e) => setCurrencyChoice(e.target.value as CurrencyChoice)}
            disabled={isCurrencySaving}
            className={inputClass}
          >
            <option value="none">{tp("profile.defaultCurrencyNone")}</option>
            {CURRENCY_PRESETS.map((c) => (
              <option key={c} value={c}>{c}</option>
            ))}
            <option value="custom">{tp("profile.defaultCurrencyCustom")}</option>
          </select>
          {currencyChoice === "custom" && (
            <div className="w-28 shrink-0">
              <input
                aria-label={tp("profile.defaultCurrencyCustomAriaLabel")}
                value={customCurrency}
                onChange={(e) => setCustomCurrency(e.target.value.toUpperCase())}
                placeholder={tp("profile.defaultCurrencyPlaceholder")}
                maxLength={10}
                disabled={isCurrencySaving}
                className={inputClass}
              />
            </div>
          )}
        </div>
        {currencyError && (
          <p className="text-sm text-red-600 dark:text-red-400">{currencyError}</p>
        )}
        {isCurrencyDirty && (
          <div className="flex gap-2 pt-1">
            <button onClick={saveCurrency} disabled={isCurrencySaving} className={btnSave}>
              {isCurrencySaving ? tp("saving") : tp("save")}
            </button>
            <button onClick={cancelCurrency} disabled={isCurrencySaving} className={btnCancel}>
              {tp("cancel")}
            </button>
          </div>
        )}
      </div>

      <hr className="border-slate-200 dark:border-slate-700" />

      <div className="space-y-2">
        <label
          htmlFor="timezone"
          className="block text-sm font-medium text-slate-700 dark:text-slate-300"
        >
          {tp("profile.timezoneLabel")}
        </label>
        <p className="text-xs text-slate-400 dark:text-slate-500">
          {tp("profile.timezoneHint")}
        </p>
        <select
          id="timezone"
          value={timezone}
          onChange={(e) => setTimezone(e.target.value)}
          disabled={isTimezoneSaving}
          className={inputClass}
        >
          <option value="">{tp("profile.timezoneDefault")}</option>
          {tzOptions.map((tz) => (
            <option key={tz} value={tz}>
              {tz}
            </option>
          ))}
        </select>
        {timezoneError && (
          <p className="text-sm text-red-600 dark:text-red-400">{timezoneError}</p>
        )}
        {isTimezoneDirty && (
          <div className="flex gap-2 pt-1">
            <button onClick={saveTimezone} disabled={isTimezoneSaving} className={btnSave}>
              {isTimezoneSaving ? tp("saving") : tp("save")}
            </button>
            <button
              onClick={() => {
                setTimezone(profile.timezone ?? "");
                setTimezoneError(null);
              }}
              disabled={isTimezoneSaving}
              className={btnCancel}
            >
              {tp("cancel")}
            </button>
          </div>
        )}
      </div>
    </Tile>
  );
}

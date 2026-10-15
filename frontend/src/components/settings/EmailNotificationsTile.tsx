"use client";

import { AlertTriangle, BarChart2, ChevronRight, HelpCircle, Loader2, Mail, Send } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import {
  fetchNotificationStatus,
  fetchServerTime,
  sendMonthlySummaryNow,
  sendNotificationNow,
  sendTestNotification,
  updateMe,
  type NotificationStatus,
  type TestNotificationResult,
  type UserProfile,
} from "@/lib/user-api";
import { Switch } from "@/components/ui/Switch";
import { Tile } from "./Tile";

const SLOTS = Array.from({ length: 48 }, (_, i) => i * 30);
function fmtSlot(minutes: number) {
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}`;
}

export function EmailNotificationsTile({
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
  const locale = useLocale();

  const [emailEnabled, setEmailEnabled] = useState(profile.email_reminders_enabled);
  const [notify2, setNotify2] = useState(profile.notify_2_days_before);
  const [notify1, setNotify1] = useState(profile.notify_1_day_before);
  const [notifyOn, setNotifyOn] = useState(profile.notify_on_day);
  const [notify1After, setNotify1After] = useState(profile.notify_1_day_after);
  const [sendMinute, setSendMinute] = useState(profile.reminder_send_minute);
  const [monthlySummary, setMonthlySummary] = useState(profile.monthly_summary_enabled);
  const [digestEnabled, setDigestEnabled] = useState(profile.upcoming_digest_enabled);
  const [digestWeekday, setDigestWeekday] = useState(profile.upcoming_digest_weekday);
  const [digestMinute, setDigestMinute] = useState(profile.upcoming_digest_minute);
  const [digestDays, setDigestDays] = useState(profile.upcoming_digest_days);
  const [isTogglingDigest, setIsTogglingDigest] = useState(false);

  // 2024-01-01 was a Monday; index 0 = Monday matches the backend convention.
  const weekdayLabels = useMemo(() => {
    const fmt = new Intl.DateTimeFormat(locale, {
      weekday: "long",
      timeZone: "UTC",
    });
    return Array.from({ length: 7 }, (_, i) =>
      fmt.format(new Date(Date.UTC(2024, 0, 1 + i))),
    );
  }, [locale]);
  const [isSaving, setIsSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [isTogglingEnabled, setIsTogglingEnabled] = useState(false);
  const [isTogglingMonthlySummary, setIsTogglingMonthlySummary] = useState(false);
  const [isSendingNow, setIsSendingNow] = useState(false);
  const [sendNowResult, setSendNowResult] = useState<
    { sent: number } | { error: string } | null
  >(null);
  const [isSendingSummary, setIsSendingSummary] = useState(false);
  const [sendSummaryResult, setSendSummaryResult] = useState<
    { sent: boolean } | { error: string } | null
  >(null);
  const [notificationStatus, setNotificationStatus] =
    useState<NotificationStatus | null>(null);
  const [isSendingTest, setIsSendingTest] = useState(false);
  const [testResult, setTestResult] =
    useState<TestNotificationResult | { error: string } | null>(null);
  const [serverTime, setServerTime] = useState<string | null>(null);

  useEffect(() => {
    fetchNotificationStatus()
      .then(setNotificationStatus)
      .catch(() => {});
  }, []);

  useEffect(() => {
    fetchServerTime()
      .then(({ server_time }) => {
        const formatted = new Intl.DateTimeFormat("en-GB", {
          year: "numeric",
          month: "short",
          day: "numeric",
          hour: "2-digit",
          minute: "2-digit",
          timeZone: "UTC",
          timeZoneName: "short",
        }).format(new Date(server_time));
        setServerTime(formatted);
      })
      .catch(() => {});
  }, []);

  const isDirty =
    notify2 !== profile.notify_2_days_before ||
    notify1 !== profile.notify_1_day_before ||
    notifyOn !== profile.notify_on_day ||
    notify1After !== profile.notify_1_day_after ||
    sendMinute !== profile.reminder_send_minute ||
    digestWeekday !== profile.upcoming_digest_weekday ||
    digestMinute !== profile.upcoming_digest_minute ||
    digestDays !== profile.upcoming_digest_days;

  const noneSelected = !notify2 && !notify1 && !notifyOn && !notify1After;
  const smtpConfigured = notificationStatus?.smtp_configured ?? false;
  const appriseConfigured = notificationStatus?.apprise_configured ?? false;
  const noChannelConfigured =
    notificationStatus !== null && !smtpConfigured && !appriseConfigured;

  useEffect(() => {
    onDirtyChange(isDirty);
  }, [isDirty, onDirtyChange]);

  async function handleEmailEnabledChange(value: boolean) {
    setEmailEnabled(value);
    setIsTogglingEnabled(true);
    try {
      const updated = await updateMe({ email_reminders_enabled: value });
      onProfileUpdate(updated);
    } catch {
      // Revert on failure
      setEmailEnabled(!value);
    } finally {
      setIsTogglingEnabled(false);
    }
  }

  function cancel() {
    setNotify2(profile.notify_2_days_before);
    setNotify1(profile.notify_1_day_before);
    setNotifyOn(profile.notify_on_day);
    setNotify1After(profile.notify_1_day_after);
    setSendMinute(profile.reminder_send_minute);
    setDigestWeekday(profile.upcoming_digest_weekday);
    setDigestMinute(profile.upcoming_digest_minute);
    setDigestDays(profile.upcoming_digest_days);
    setSaveError(null);
  }

  async function handleMonthlySummaryChange(value: boolean) {
    setMonthlySummary(value);
    setIsTogglingMonthlySummary(true);
    try {
      const updated = await updateMe({ monthly_summary_enabled: value });
      onProfileUpdate(updated);
    } catch {
      setMonthlySummary(!value);
    } finally {
      setIsTogglingMonthlySummary(false);
    }
  }

  async function handleDigestEnabledChange(value: boolean) {
    setDigestEnabled(value);
    setIsTogglingDigest(true);
    try {
      const updated = await updateMe({ upcoming_digest_enabled: value });
      onProfileUpdate(updated);
    } catch {
      setDigestEnabled(!value);
    } finally {
      setIsTogglingDigest(false);
    }
  }

  async function save() {
    setIsSaving(true);
    setSaveError(null);
    try {
      const updated = await updateMe({
        notify_2_days_before: notify2,
        notify_1_day_before: notify1,
        notify_on_day: notifyOn,
        notify_1_day_after: notify1After,
        reminder_send_minute: sendMinute,
        upcoming_digest_weekday: digestWeekday,
        upcoming_digest_minute: digestMinute,
        upcoming_digest_days: digestDays,
      });
      onProfileUpdate(updated);
    } catch {
      setSaveError(tp("saveFailed"));
    } finally {
      setIsSaving(false);
    }
  }

  async function handleSendNow() {
    setIsSendingNow(true);
    setSendNowResult(null);
    try {
      const result = await sendNotificationNow();
      setSendNowResult(result);
    } catch (err) {
      setSendNowResult({ error: err instanceof Error ? err.message : tp("saveFailed") });
    } finally {
      setIsSendingNow(false);
    }
  }

  async function handleSendSummary() {
    setIsSendingSummary(true);
    setSendSummaryResult(null);
    try {
      const result = await sendMonthlySummaryNow();
      setSendSummaryResult(result);
    } catch (err) {
      setSendSummaryResult({ error: err instanceof Error ? err.message : tp("saveFailed") });
    } finally {
      setIsSendingSummary(false);
    }
  }

  async function handleSendTest() {
    setIsSendingTest(true);
    setTestResult(null);
    try {
      const result = await sendTestNotification();
      setTestResult(result);
    } catch (err) {
      setTestResult({ error: err instanceof Error ? err.message : tp("saveFailed") });
    } finally {
      setIsSendingTest(false);
    }
  }

  const checkboxClass =
    "h-4 w-4 rounded border-slate-200 accent-blue-700 focus:ring-blue-500 dark:border-slate-600";
  const labelClass = "ml-2 text-sm text-slate-700 dark:text-slate-300 cursor-pointer";

  const checkboxes: [string, boolean, (v: boolean) => void, string][] = [
    ["2-before", notify2, setNotify2, tp("emailNotifications.twoDaysBefore")],
    ["1-before", notify1, setNotify1, tp("emailNotifications.oneDayBefore")],
    ["on-day", notifyOn, setNotifyOn, tp("emailNotifications.onDay")],
    ["1-after", notify1After, setNotify1After, tp("emailNotifications.oneDayAfter")],
  ];

  return (
    <Tile
      color="yellow"
      icon={Mail}
      title={tp("emailNotifications.title")}
      description={tp("emailNotifications.description")}
      t={t}
      isCollapsed={isCollapsed}
      onToggle={onToggle}
    >
      <Switch
        checked={emailEnabled}
        onChange={handleEmailEnabledChange}
        label={tp("emailNotifications.masterToggle")}
        disabled={isTogglingEnabled}
      />

      <div className={!emailEnabled ? "opacity-50 pointer-events-none" : ""}>
        <div className="space-y-2">
          {checkboxes.map(([key, checked, setter, label]) => (
            <label key={key} className="flex items-center">
              <input
                type="checkbox"
                checked={checked}
                onChange={(e) => setter(e.target.checked)}
                className={checkboxClass}
              />
              <span className={labelClass}>{label}</span>
            </label>
          ))}
        </div>

        {noneSelected && (
          <div className="flex items-start gap-2 rounded-lg bg-yellow-50 dark:bg-yellow-900/30 border border-yellow-200 dark:border-yellow-700 px-3 py-2 mt-2">
            <AlertTriangle size={15} className="text-yellow-600 dark:text-yellow-400 mt-0.5 shrink-0" />
            <p className="text-sm text-yellow-700 dark:text-yellow-300">
              {tp("emailNotifications.noneWarning")}
            </p>
          </div>
        )}

        <div className="flex items-center gap-3 pt-1">
          <label className="text-sm font-medium text-slate-700 dark:text-slate-300 whitespace-nowrap">
            {tp("emailNotifications.sendTimeLabel")}
          </label>
          <select
            value={sendMinute}
            onChange={(e) => setSendMinute(Number(e.target.value))}
            className="rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-sm font-medium text-slate-700 shadow-sm outline-none transition-all hover:border-slate-300 focus:border-blue-500 focus:ring-2 focus:ring-blue-100 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-200 dark:hover:border-slate-500 dark:focus:border-blue-600 dark:focus:ring-blue-900/40"
          >
            {SLOTS.map((h) => (
              <option key={h} value={h}>{fmtSlot(h)}</option>
            ))}
          </select>
        </div>

        {isDirty && (
          <div className="flex flex-col gap-1 pt-1">
            <div className="flex gap-2">
              <button
                onClick={save}
                disabled={isSaving}
                className="rounded-lg border border-blue-700 bg-blue-700 px-4 py-1.5 text-sm font-medium text-white shadow-sm transition-all hover:border-blue-800 hover:bg-blue-800 disabled:opacity-50"
              >
                {isSaving ? t("saving") : t("save")}
              </button>
              <button
                onClick={cancel}
                disabled={isSaving}
                className="rounded-lg border border-slate-200 bg-white px-4 py-1.5 text-sm font-medium text-slate-600 shadow-sm transition-all hover:border-slate-300 hover:bg-slate-50 disabled:opacity-50 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-300 dark:hover:bg-slate-700"
              >
                {t("cancel")}
              </button>
            </div>
            {saveError && (
              <p className="text-sm text-red-600 dark:text-red-400">{saveError}</p>
            )}
          </div>
        )}

        <div className="flex flex-col gap-2 pt-1 border-t border-slate-100 dark:border-slate-700">
          <button
            onClick={handleSendNow}
            disabled={isSendingNow || !emailEnabled || isDirty || noChannelConfigured}
            className="flex items-center gap-2 self-start rounded-lg border border-slate-200 bg-white px-4 py-1.5 text-sm font-medium text-slate-600 shadow-sm transition-all hover:border-blue-300 hover:bg-blue-50 hover:text-blue-700 disabled:opacity-50 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-400 dark:hover:border-blue-700 dark:hover:bg-blue-900/20 dark:hover:text-blue-400"
          >
            {isSendingNow ? <Loader2 size={14} className="animate-spin" /> : <Send size={14} />}
            {isSendingNow ? tp("emailNotifications.sendNowSending") : tp("emailNotifications.sendNowButton")}
          </button>

          {sendNowResult && "error" in sendNowResult && (
            <p className="text-sm text-red-600 dark:text-red-400">{sendNowResult.error}</p>
          )}
          {sendNowResult && "sent" in sendNowResult && (
            <p className="text-sm text-blue-600 dark:text-blue-500">
              {sendNowResult.sent === 0
                ? tp("emailNotifications.sendNowNoReminders")
                : tp("emailNotifications.sendNowSent", { count: sendNowResult.sent })}
            </p>
          )}

          <div className="pt-1 border-t border-slate-100 dark:border-slate-700">
            <Switch
              checked={monthlySummary}
              onChange={handleMonthlySummaryChange}
              label={tp("emailNotifications.monthlySummaryToggle")}
              disabled={isTogglingMonthlySummary}
            />
          </div>

          <button
            onClick={handleSendSummary}
            disabled={isSendingSummary || !emailEnabled || !monthlySummary || isDirty || noChannelConfigured}
            className="flex items-center gap-2 self-start rounded-lg border border-slate-200 bg-white px-4 py-1.5 text-sm font-medium text-slate-600 shadow-sm transition-all hover:border-blue-300 hover:bg-blue-50 hover:text-blue-700 disabled:opacity-50 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-400 dark:hover:border-blue-700 dark:hover:bg-blue-900/20 dark:hover:text-blue-400"
          >
            {isSendingSummary ? <Loader2 size={14} className="animate-spin" /> : <BarChart2 size={14} />}
            {isSendingSummary
              ? tp("emailNotifications.sendMonthlySummarySending")
              : tp("emailNotifications.sendMonthlySummaryButton")}
          </button>

          {sendSummaryResult && "error" in sendSummaryResult && (
            <p className="text-sm text-red-600 dark:text-red-400">{sendSummaryResult.error}</p>
          )}
          {sendSummaryResult && "sent" in sendSummaryResult && (
            <p className="text-sm text-blue-600 dark:text-blue-500">
              {sendSummaryResult.sent
                ? tp("emailNotifications.sendMonthlySummarySent")
                : tp("emailNotifications.sendMonthlySummaryNoData")}
            </p>
          )}

          <div className="pt-1 border-t border-slate-100 dark:border-slate-700">
            <Switch
              checked={digestEnabled}
              onChange={handleDigestEnabledChange}
              label={tp("emailNotifications.digestToggle")}
              disabled={isTogglingDigest}
            />
            <p className="mt-1 text-xs text-slate-400 dark:text-slate-500">
              {tp("emailNotifications.digestHint")}
            </p>
            <div
              className={`mt-2 flex flex-wrap items-center gap-2 ${
                digestEnabled ? "" : "opacity-50 pointer-events-none"
              }`}
            >
              <select
                aria-label={tp("emailNotifications.digestWeekdayLabel")}
                value={digestWeekday}
                onChange={(e) => setDigestWeekday(Number(e.target.value))}
                className="rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-sm font-medium text-slate-700 shadow-sm outline-none transition-all hover:border-slate-300 focus:border-blue-500 focus:ring-2 focus:ring-blue-100 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-200 dark:hover:border-slate-500 dark:focus:border-blue-600 dark:focus:ring-blue-900/40"
              >
                {weekdayLabels.map((label, i) => (
                  <option key={label} value={i}>
                    {label}
                  </option>
                ))}
              </select>
              <select
                aria-label={tp("emailNotifications.digestTimeLabel")}
                value={digestMinute}
                onChange={(e) => setDigestMinute(Number(e.target.value))}
                className="rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-sm font-medium text-slate-700 shadow-sm outline-none transition-all hover:border-slate-300 focus:border-blue-500 focus:ring-2 focus:ring-blue-100 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-200 dark:hover:border-slate-500 dark:focus:border-blue-600 dark:focus:ring-blue-900/40"
              >
                {SLOTS.map((h) => (
                  <option key={h} value={h}>{fmtSlot(h)}</option>
                ))}
              </select>
              <label className="flex items-center gap-1.5 text-sm text-slate-600 dark:text-slate-400">
                {tp("emailNotifications.digestDaysLabel")}
                <input
                  type="number"
                  min={1}
                  max={30}
                  value={digestDays}
                  onChange={(e) =>
                    setDigestDays(
                      Math.min(30, Math.max(1, Number(e.target.value) || 1)),
                    )
                  }
                  className="w-16 rounded-lg border border-slate-200 bg-white px-2 py-1.5 text-sm font-medium text-slate-700 shadow-sm outline-none transition-all hover:border-slate-300 focus:border-blue-500 focus:ring-2 focus:ring-blue-100 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-200 dark:hover:border-slate-500 dark:focus:border-blue-600 dark:focus:ring-blue-900/40"
                />
              </label>
            </div>
          </div>
        </div>
      </div>

      <div className="flex flex-col gap-2 pt-1 border-t border-slate-100 dark:border-slate-700">
        <p className="text-sm font-medium text-slate-700 dark:text-slate-300">
          {tp("emailNotifications.channelsLabel")}
        </p>

        <div className="flex items-center justify-between gap-2">
          <span className="text-sm text-slate-600 dark:text-slate-400">
            {tp("emailNotifications.smtpChannel")}
          </span>
          <span
            className={
              smtpConfigured
                ? "text-sm text-blue-600 dark:text-blue-500"
                : "text-sm text-slate-400 dark:text-slate-500"
            }
          >
            {smtpConfigured
              ? tp("emailNotifications.channelConfigured")
              : tp("emailNotifications.channelNotConfigured")}
          </span>
        </div>

        <div className="flex items-center justify-between gap-2">
          <span className="text-sm text-slate-600 dark:text-slate-400">
            {tp("emailNotifications.appriseChannel")}
          </span>
          <span
            className={
              appriseConfigured
                ? "text-sm text-blue-600 dark:text-blue-500"
                : "text-sm text-slate-400 dark:text-slate-500"
            }
          >
            {appriseConfigured
              ? tp("emailNotifications.channelConfigured")
              : tp("emailNotifications.channelNotConfigured")}
          </span>
        </div>

        {noChannelConfigured && (
          <div className="flex items-start gap-2 rounded-lg bg-yellow-50 dark:bg-yellow-900/30 border border-yellow-200 dark:border-yellow-700 px-3 py-2">
            <AlertTriangle size={15} className="text-yellow-600 dark:text-yellow-400 mt-0.5 shrink-0" />
            <p className="text-sm text-yellow-700 dark:text-yellow-300">
              {tp("emailNotifications.noChannelWarning")}
            </p>
          </div>
        )}

        <button
          onClick={handleSendTest}
          disabled={isSendingTest}
          className="flex items-center gap-2 self-start rounded-lg border border-slate-200 bg-white px-4 py-1.5 text-sm font-medium text-slate-600 shadow-sm transition-all hover:border-blue-300 hover:bg-blue-50 hover:text-blue-700 disabled:opacity-50 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-400 dark:hover:border-blue-700 dark:hover:bg-blue-900/20 dark:hover:text-blue-400"
        >
          {isSendingTest ? <Loader2 size={14} className="animate-spin" /> : <Send size={14} />}
          {isSendingTest
            ? tp("emailNotifications.sendTestSending")
            : tp("emailNotifications.sendTestButton")}
        </button>

        {testResult && "error" in testResult && (
          <p className="text-sm text-red-600 dark:text-red-400">{testResult.error}</p>
        )}
        {testResult && "ok" in testResult && (
          <p
            className={
              testResult.ok
                ? "text-sm text-blue-600 dark:text-blue-500"
                : "text-sm text-red-600 dark:text-red-400"
            }
          >
            {testResult.ok
              ? testResult.channel === "apprise"
                ? tp("emailNotifications.testSentViaApprise")
                : tp("emailNotifications.testSentViaEmail")
              : (testResult.detail ?? tp("emailNotifications.testFailed"))}
          </p>
        )}
      </div>

      <details className="group pt-1 border-t border-slate-100 dark:border-slate-700">
        <summary className="flex cursor-pointer list-none items-center gap-2 text-sm font-medium text-slate-700 dark:text-slate-300">
          <HelpCircle size={15} className="shrink-0 text-slate-400 dark:text-slate-500" />
          {tp("emailNotifications.setupTitle")}
          <ChevronRight
            size={14}
            className="ml-auto shrink-0 text-slate-400 transition-transform group-open:rotate-90 dark:text-slate-500"
          />
        </summary>
        <div className="mt-2 flex flex-col gap-2 text-sm text-slate-500 dark:text-slate-400">
          <p>{tp("emailNotifications.setupAppriseIntro")}</p>
          <p>{tp("emailNotifications.setupGatewayNote")}</p>
          <p className="font-medium text-slate-600 dark:text-slate-300">
            {tp("emailNotifications.setupMinimalLabel")}
          </p>
          <pre className="overflow-x-auto rounded-lg bg-slate-50 px-3 py-2 text-xs text-slate-600 dark:bg-slate-900/40 dark:text-slate-300">
{`services:
  apprise:
    image: caronc/apprise:latest
    restart: unless-stopped
    ports: ["8000:8000"]
    volumes: ["./apprise/config:/config"]`}
          </pre>
          <pre className="overflow-x-auto rounded-lg bg-slate-50 px-3 py-2 text-xs text-slate-600 dark:bg-slate-900/40 dark:text-slate-300">
{`APPRISE_BASE_URL=http://apprise:8000`}
          </pre>
          <p className="font-medium text-slate-600 dark:text-slate-300">
            {tp("emailNotifications.setupOptionalLabel")}
          </p>
          <pre className="overflow-x-auto rounded-lg bg-slate-50 px-3 py-2 text-xs text-slate-600 dark:bg-slate-900/40 dark:text-slate-300">
{`# saved configuration inside the gateway
APPRISE_KEY=platybill
# or pass targets per request (space/comma separated)
APPRISE_URLS="ntfy://topic discord://webhook_id/webhook_token"`}
          </pre>
          <p>{tp("emailNotifications.setupReachability")}</p>
          <p>{tp("emailNotifications.setupSmtpLegacy")}</p>
        </div>
      </details>

      {serverTime && (
        <p className="mt-3 text-xs text-slate-400 dark:text-slate-500">
          {tp("emailNotifications.serverTimeHint", { time: serverTime })}
        </p>
      )}
    </Tile>
  );
}

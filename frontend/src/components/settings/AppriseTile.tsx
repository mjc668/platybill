"use client";

import { useEffect, useState } from "react";
import { BellRing, Check, Loader2, Save } from "lucide-react";
import { useTranslations } from "next-intl";
import {
  fetchNotificationSettings,
  updateNotificationSettings,
  type NotificationSettings,
} from "@/lib/notifications-api";
import { Tile, type TileTranslator } from "./Tile";

export function AppriseTile({
  t,
  isCollapsed,
  onToggle,
}: {
  t: TileTranslator;
  isCollapsed?: boolean;
  onToggle?: () => void;
}) {
  const tc = useTranslations("SettingsPage.apprise");
  const [settings, setSettings] = useState<NotificationSettings | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<{ tone: "ok" | "error"; text: string } | null>(
    null,
  );
  const [baseUrl, setBaseUrl] = useState("");
  const [urls, setUrls] = useState("");
  const [key, setKey] = useState("");
  const [timeout, setTimeout] = useState("10");

  useEffect(() => {
    let cancelled = false;
    fetchNotificationSettings()
      .then((data) => {
        if (cancelled) return;
        setSettings(data);
        setBaseUrl(data.apprise_base_url ?? "");
        setTimeout(String(data.apprise_timeout_seconds));
        setLoading(false);
      })
      .catch(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const timeoutValue = parseFloat(timeout);
  const timeoutValid =
    Number.isFinite(timeoutValue) && timeoutValue >= 1 && timeoutValue <= 300;
  const urlValid = baseUrl === "" || /^https?:\/\//.test(baseUrl);
  const dirty =
    settings !== null &&
    (baseUrl !== (settings.apprise_base_url ?? "") ||
      urls.trim() !== "" ||
      key.trim() !== "" ||
      (timeoutValid && timeoutValue !== settings.apprise_timeout_seconds));

  async function handleSave() {
    if (!urlValid || !timeoutValid) return;
    setSaving(true);
    setMessage(null);
    try {
      const updated = await updateNotificationSettings({
        apprise: {
          base_url: baseUrl.trim() === "" ? null : baseUrl.trim(),
          ...(urls.trim() !== "" ? { urls: urls.trim() } : {}),
          ...(key.trim() !== "" ? { key: key.trim() } : {}),
          timeout_seconds: timeoutValue,
        },
      });
      setSettings(updated);
      setBaseUrl(updated.apprise_base_url ?? "");
      setUrls("");
      setKey("");
      setTimeout(String(updated.apprise_timeout_seconds));
      setMessage({ tone: "ok", text: tc("saved") });
    } catch (err) {
      setMessage({
        tone: "error",
        text: err instanceof Error ? err.message : tc("saveFailed"),
      });
    } finally {
      setSaving(false);
    }
  }

  const inputClass =
    "w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-800 placeholder:text-slate-400 outline-none transition-all focus:border-blue-500 focus:ring-2 focus:ring-blue-100 dark:border-slate-600 dark:bg-slate-700 dark:text-slate-100 dark:focus:border-blue-600 dark:focus:ring-blue-900/40";

  return (
    <Tile
      color="blue"
      icon={BellRing}
      title={tc("title")}
      description={tc("description")}
      t={t}
      isCollapsed={isCollapsed}
      onToggle={onToggle}
    >
      <div data-testid="apprise-tile" className="space-y-4">
        {message && (
          <p
            className={`flex items-center gap-1.5 rounded-xl px-3 py-2 text-xs ${
              message.tone === "ok"
                ? "bg-blue-50 text-blue-700 dark:bg-blue-900/20 dark:text-blue-400"
                : "bg-red-50 text-red-600 dark:bg-red-900/20 dark:text-red-400"
            }`}
          >
            {message.tone === "ok" && <Check size={12} />}
            {message.text}
          </p>
        )}
        {loading ? (
          <div className="h-10 animate-pulse rounded-lg bg-slate-100 dark:bg-slate-700" />
        ) : (
          <>
            <div className="grid gap-3 sm:grid-cols-2">
              <div>
                <label htmlFor="apprise-url" className="mb-1 block text-xs text-slate-500 dark:text-slate-400">
                  {tc("baseUrlLabel")}
                </label>
                <input
                  id="apprise-url"
                  value={baseUrl}
                  placeholder="https://ntfy.example.com"
                  onChange={(e) => setBaseUrl(e.target.value)}
                  className={inputClass}
                />
              </div>
              <div>
                <label htmlFor="apprise-timeout" className="mb-1 block text-xs text-slate-500 dark:text-slate-400">
                  {tc("timeoutLabel")}
                </label>
                <input
                  id="apprise-timeout"
                  type="number"
                  min="1"
                  max="300"
                  value={timeout}
                  onChange={(e) => setTimeout(e.target.value)}
                  className={inputClass}
                />
              </div>
              <div>
                <label htmlFor="apprise-urls" className="mb-1 block text-xs text-slate-500 dark:text-slate-400">
                  {settings?.apprise_urls_configured
                    ? tc("urlsSetLabel")
                    : tc("urlsLabel")}
                </label>
                <input
                  id="apprise-urls"
                  value={urls}
                  placeholder={tc("urlsPlaceholder")}
                  autoComplete="off"
                  onChange={(e) => setUrls(e.target.value)}
                  className={inputClass}
                />
              </div>
              <div>
                <label htmlFor="apprise-key" className="mb-1 block text-xs text-slate-500 dark:text-slate-400">
                  {settings?.apprise_key_configured
                    ? tc("keySetLabel")
                    : tc("keyLabel")}
                </label>
                <input
                  id="apprise-key"
                  type="password"
                  value={key}
                  placeholder={tc("keyPlaceholder")}
                  autoComplete="new-password"
                  onChange={(e) => setKey(e.target.value)}
                  className={inputClass}
                />
              </div>
            </div>
            {!urlValid && (
              <p className="text-xs text-amber-700 dark:text-amber-400">
                {tc("urlInvalid")}
              </p>
            )}
            <button
              type="button"
              onClick={handleSave}
              disabled={saving || !dirty || !urlValid || !timeoutValid}
              className="flex items-center gap-1.5 rounded-lg border border-blue-700 bg-blue-700 px-4 py-2 text-sm font-medium text-white shadow-sm transition-all hover:border-blue-800 hover:bg-blue-800 disabled:opacity-50"
            >
              {saving ? (
                <Loader2 size={14} className="animate-spin" />
              ) : (
                <Save size={14} />
              )}
              {tc("save")}
            </button>
          </>
        )}
      </div>
    </Tile>
  );
}

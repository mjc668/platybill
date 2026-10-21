"use client";

import { useEffect, useState } from "react";
import { Check, Loader2, Mail, Save } from "lucide-react";
import { useTranslations } from "next-intl";
import {
  fetchNotificationSettings,
  updateNotificationSettings,
  type NotificationSettings,
} from "@/lib/notifications-api";
import { Tile, type TileTranslator } from "./Tile";

export function SmtpTile({
  t,
  isCollapsed,
  onToggle,
}: {
  t: TileTranslator;
  isCollapsed?: boolean;
  onToggle?: () => void;
}) {
  const tc = useTranslations("SettingsPage.smtp");
  const [settings, setSettings] = useState<NotificationSettings | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<{ tone: "ok" | "error"; text: string } | null>(
    null,
  );
  const [host, setHost] = useState("");
  const [port, setPort] = useState("587");
  const [user, setUser] = useState("");
  const [password, setPassword] = useState("");
  const [useTls, setUseTls] = useState(true);
  const [fromAddr, setFromAddr] = useState("");

  useEffect(() => {
    let cancelled = false;
    fetchNotificationSettings()
      .then((data) => {
        if (cancelled) return;
        setSettings(data);
        setHost(data.smtp_host ?? "");
        setPort(String(data.smtp_port));
        setUseTls(data.smtp_use_tls);
        setFromAddr(data.smtp_from ?? "");
        setLoading(false);
      })
      .catch(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const portValue = parseInt(port, 10);
  const portValid =
    Number.isFinite(portValue) && portValue >= 1 && portValue <= 65535;
  const dirty =
    settings !== null &&
    (host !== (settings.smtp_host ?? "") ||
      portValue !== settings.smtp_port ||
      user.trim() !== "" ||
      password !== "" ||
      useTls !== settings.smtp_use_tls ||
      fromAddr !== (settings.smtp_from ?? ""));

  async function handleSave() {
    if (!portValid) return;
    setSaving(true);
    setMessage(null);
    try {
      const updated = await updateNotificationSettings({
        smtp: {
          ...(host.trim() !== "" ? { host: host.trim() } : {}),
          ...(portValid ? { port: portValue } : {}),
          ...(user.trim() !== "" ? { user: user.trim() } : {}),
          ...(password !== "" ? { password } : {}),
          use_tls: useTls,
          ...(fromAddr.trim() !== ""
            ? { from_addr: fromAddr.trim() }
            : {}),
        },
      });
      setSettings(updated);
      setHost(updated.smtp_host ?? "");
      setPort(String(updated.smtp_port));
      setUser("");
      setPassword("");
      setUseTls(updated.smtp_use_tls);
      setFromAddr(updated.smtp_from ?? "");
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
      icon={Mail}
      title={tc("title")}
      description={tc("description")}
      t={t}
      isCollapsed={isCollapsed}
      onToggle={onToggle}
    >
      <div data-testid="smtp-tile" className="space-y-4">
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
                <label htmlFor="smtp-host" className="mb-1 block text-xs text-slate-500 dark:text-slate-400">
                  {tc("hostLabel")}
                </label>
                <input
                  id="smtp-host"
                  value={host}
                  placeholder="smtp.example.com"
                  onChange={(e) => setHost(e.target.value)}
                  className={inputClass}
                />
              </div>
              <div>
                <label htmlFor="smtp-port" className="mb-1 block text-xs text-slate-500 dark:text-slate-400">
                  {tc("portLabel")}
                </label>
                <input
                  id="smtp-port"
                  type="number"
                  min="1"
                  max="65535"
                  value={port}
                  onChange={(e) => setPort(e.target.value)}
                  className={inputClass}
                />
              </div>
              <div>
                <label htmlFor="smtp-user" className="mb-1 block text-xs text-slate-500 dark:text-slate-400">
                  {settings?.smtp_user
                    ? tc("userSetLabel", { user: settings.smtp_user })
                    : tc("userLabel")}
                </label>
                <input
                  id="smtp-user"
                  value={user}
                  placeholder={tc("userPlaceholder")}
                  autoComplete="off"
                  onChange={(e) => setUser(e.target.value)}
                  className={inputClass}
                />
              </div>
              <div>
                <label htmlFor="smtp-password" className="mb-1 block text-xs text-slate-500 dark:text-slate-400">
                  {settings?.smtp_password_configured
                    ? tc("passwordSetLabel")
                    : tc("passwordLabel")}
                </label>
                <input
                  id="smtp-password"
                  type="password"
                  value={password}
                  placeholder={
                    settings?.smtp_password_configured
                      ? tc("passwordSetPlaceholder")
                      : tc("passwordPlaceholder")
                  }
                  autoComplete="new-password"
                  onChange={(e) => setPassword(e.target.value)}
                  className={inputClass}
                />
              </div>
              <div>
                <label htmlFor="smtp-from" className="mb-1 block text-xs text-slate-500 dark:text-slate-400">
                  {tc("fromLabel")}
                </label>
                <input
                  id="smtp-from"
                  value={fromAddr}
                  placeholder={tc("fromPlaceholder")}
                  onChange={(e) => setFromAddr(e.target.value)}
                  className={inputClass}
                />
              </div>
              <label className="flex cursor-pointer items-center gap-2 text-sm text-slate-600 dark:text-slate-400">
                <input
                  type="checkbox"
                  checked={useTls}
                  onChange={(e) => setUseTls(e.target.checked)}
                  className="h-4 w-4 rounded accent-blue-700"
                />
                {tc("tlsLabel")}
              </label>
            </div>
            <button
              type="button"
              onClick={handleSave}
              disabled={saving || !dirty || !portValid}
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

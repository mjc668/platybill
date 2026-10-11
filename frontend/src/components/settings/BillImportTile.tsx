"use client";

import { useEffect, useState } from "react";
import { AlertTriangle, FileSearch, Loader2, RefreshCw, Server } from "lucide-react";
import { useTranslations } from "next-intl";
import {
  fetchImportStatus,
  scanNow,
  testOllama,
  type ImportStatusOut,
} from "@/lib/imports-api";
import { Tile } from "./Tile";

function StatusRow({
  label,
  value,
  tone = "ok",
}: {
  label: string;
  value: string;
  tone?: "ok" | "warn" | "off";
}) {
  const toneClass =
    tone === "ok"
      ? "text-blue-700 dark:text-blue-400"
      : tone === "warn"
        ? "text-amber-700 dark:text-amber-400"
        : "text-slate-400 dark:text-slate-500";
  return (
    <div className="flex items-baseline justify-between gap-3 text-sm">
      <span className="text-slate-500 dark:text-slate-400">{label}</span>
      <span className={`text-right font-medium ${toneClass}`}>{value}</span>
    </div>
  );
}

export function BillImportTile({
  t,
  isCollapsed,
  onToggle,
}: {
  t: ReturnType<typeof useTranslations>;
  isCollapsed?: boolean;
  onToggle?: () => void;
}) {
  const tp = useTranslations("SettingsPage");
  const ti = useTranslations("BillImport");

  const [status, setStatus] = useState<ImportStatusOut | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<"test" | "scan" | null>(null);
  const [message, setMessage] = useState<{ tone: "ok" | "error"; text: string } | null>(
    null,
  );
  const [refreshToken, setRefreshToken] = useState(0);

  useEffect(() => {
    let cancelled = false;
    fetchImportStatus()
      .then((data) => {
        if (cancelled) return;
        setStatus(data);
        setLoading(false);
      })
      .catch(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [refreshToken]);

  async function handleTest() {
    setBusy("test");
    setMessage(null);
    try {
      const result = await testOllama();
      setMessage({
        tone: result.ok ? "ok" : "error",
        text: result.ok
          ? result.model_available
            ? ti("testOkModelReady", { model: result.model })
            : ti("testOkModelMissing", { model: result.model })
          : (result.error ?? ti("testFailed")),
      });
    } catch (err) {
      setMessage({ tone: "error", text: err instanceof Error ? err.message : ti("testFailed") });
    } finally {
      setBusy(null);
      setRefreshToken((token) => token + 1);
    }
  }

  async function handleScan() {
    setBusy("scan");
    setMessage(null);
    try {
      await scanNow();
      setMessage({ tone: "ok", text: ti("scanDone") });
    } catch (err) {
      setMessage({ tone: "error", text: err instanceof Error ? err.message : ti("scanFailed") });
    } finally {
      setBusy(null);
      setRefreshToken((token) => token + 1);
    }
  }

  const ollamaTone = status?.ollama_reachable
    ? status.model_available
      ? "ok"
      : "warn"
    : status?.ollama_configured
      ? "warn"
      : "off";

  return (
    <Tile
      color="blue"
      icon={FileSearch}
      title={tp("billImport.title")}
      description={tp("billImport.description")}
      t={t}
      isCollapsed={isCollapsed}
      onToggle={onToggle}
    >
      {loading && !status ? (
        <div className="flex items-center gap-2 text-sm text-slate-500 dark:text-slate-400">
          <Loader2 size={15} className="animate-spin" />
          {ti("loading")}
        </div>
      ) : status ? (
        <div className="space-y-3">
          <div className="space-y-1.5">
            <StatusRow
              label={ti("ollamaLabel")}
              value={
                !status.ollama_configured
                  ? ti("notConfigured")
                  : status.ollama_reachable
                    ? status.model_available
                      ? ti("ready", { model: status.ollama_model })
                      : ti("modelMissing", { model: status.ollama_model })
                    : ti("unreachable")
              }
              tone={ollamaTone}
            />
            <StatusRow
              label={ti("watchDirLabel")}
              value={
                status.import_enabled
                  ? status.import_dir
                  : `${status.import_dir} · ${ti("disabled")}`
              }
              tone={status.import_enabled ? "ok" : "off"}
            />
            <StatusRow
              label={ti("imapLabel")}
              value={
                status.imap_configured
                  ? (status.imap_user ?? ti("configured"))
                  : ti("notConfigured")
              }
              tone={status.imap_configured ? "ok" : "off"}
            />
            <StatusRow
              label={ti("pendingLabel")}
              value={String(status.pending_count)}
              tone={status.pending_count > 0 ? "warn" : "off"}
            />
          </div>

          {status.last_error && (
            <p className="flex items-start gap-2 rounded-xl bg-amber-50 px-3 py-2 text-xs text-amber-700 dark:bg-amber-900/20 dark:text-amber-400">
              <AlertTriangle size={13} className="mt-0.5 shrink-0" />
              {status.last_error}
            </p>
          )}

          {message && (
            <p
              className={`rounded-xl px-3 py-2 text-xs ${
                message.tone === "ok"
                  ? "bg-blue-50 text-blue-700 dark:bg-blue-900/20 dark:text-blue-400"
                  : "bg-red-50 text-red-600 dark:bg-red-900/20 dark:text-red-400"
              }`}
            >
              {message.text}
            </p>
          )}

          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={handleTest}
              disabled={busy !== null || !status.ollama_configured}
              className="flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-600 shadow-sm transition-all hover:border-blue-300 hover:bg-blue-50 hover:text-blue-700 disabled:cursor-not-allowed disabled:opacity-50 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-400 dark:hover:border-blue-700 dark:hover:bg-blue-900/20 dark:hover:text-blue-400"
            >
              {busy === "test" ? (
                <Loader2 size={13} className="animate-spin" />
              ) : (
                <Server size={13} />
              )}
              {ti("testButton")}
            </button>
            <button
              type="button"
              onClick={handleScan}
              disabled={busy !== null || !status.import_enabled}
              className="flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-600 shadow-sm transition-all hover:border-blue-300 hover:bg-blue-50 hover:text-blue-700 disabled:cursor-not-allowed disabled:opacity-50 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-400 dark:hover:border-blue-700 dark:hover:bg-blue-900/20 dark:hover:text-blue-400"
            >
              {busy === "scan" ? (
                <Loader2 size={13} className="animate-spin" />
              ) : (
                <RefreshCw size={13} />
              )}
              {ti("scanButton")}
            </button>
          </div>
        </div>
      ) : null}
    </Tile>
  );
}

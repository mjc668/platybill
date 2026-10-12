"use client";

import { useEffect, useState } from "react";
import {
  AlertTriangle,
  Check,
  FileSearch,
  Loader2,
  RefreshCw,
  Save,
  Server,
} from "lucide-react";
import { useTranslations } from "next-intl";
import {
  fetchImportStatus,
  scanNow,
  testOllama,
  updateImportSettings,
  type ImportStatusOut,
} from "@/lib/imports-api";
import { Switch } from "@/components/ui/Switch";
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
  const [busy, setBusy] = useState<"test" | "scan" | "save" | null>(null);
  const [message, setMessage] = useState<{ tone: "ok" | "error"; text: string } | null>(
    null,
  );
  const [refreshToken, setRefreshToken] = useState(0);

  const [enabled, setEnabled] = useState(false);
  const [directory, setDirectory] = useState("/data/import");
  const [minutes, setMinutes] = useState("15");
  const [ollamaUrl, setOllamaUrl] = useState("");
  const [ollamaModel, setOllamaModel] = useState("");

  useEffect(() => {
    let cancelled = false;
    fetchImportStatus()
      .then((data) => {
        if (cancelled) return;
        setStatus(data);
        setEnabled(data.import_enabled);
        setDirectory(data.import_dir);
        setMinutes(String(data.import_poll_minutes));
        setOllamaUrl(data.ollama_base_url ?? "");
        setOllamaModel(data.ollama_model);
        setLoading(false);
      })
      .catch(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [refreshToken]);

  const minutesValue = parseInt(minutes, 10);
  const minutesValid = Number.isFinite(minutesValue) && minutesValue >= 1 && minutesValue <= 1440;
  const directoryValid = directory.startsWith("/");
  const urlValid = ollamaUrl === "" || /^https?:\/\//.test(ollamaUrl);
  const dirty =
    status !== null &&
    (enabled !== status.import_enabled ||
      directory !== status.import_dir ||
      minutesValue !== status.import_poll_minutes ||
      ollamaUrl !== (status.ollama_base_url ?? "") ||
      ollamaModel !== status.ollama_model);

  async function handleSave() {
    if (!minutesValid || !directoryValid || !urlValid || ollamaModel === "") return;
    setBusy("save");
    setMessage(null);
    try {
      const updated = await updateImportSettings({
        enabled,
        directory,
        poll_minutes: minutesValue,
        ollama_base_url: ollamaUrl,
        ollama_model: ollamaModel,
      });
      setStatus(updated);
      setEnabled(updated.import_enabled);
      setDirectory(updated.import_dir);
      setMinutes(String(updated.import_poll_minutes));
      setOllamaUrl(updated.ollama_base_url ?? "");
      setOllamaModel(updated.ollama_model);
      setMessage({ tone: "ok", text: ti("saved") });
    } catch (err) {
      setMessage({
        tone: "error",
        text: err instanceof Error ? err.message : ti("saveFailed"),
      });
    } finally {
      setBusy(null);
    }
  }

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

  const inputClass =
    "rounded-lg border border-slate-200 bg-white px-2 py-1.5 text-sm text-slate-800 outline-none focus:border-blue-500 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-100";

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

          <div className="space-y-3 rounded-xl border border-slate-200 bg-slate-50 p-3 dark:border-slate-700 dark:bg-slate-900/40">
            <Switch
              checked={enabled}
              onChange={setEnabled}
              label={ti("pollToggle")}
            />
            <div className="flex flex-wrap items-end gap-3">
              <div className="flex flex-col gap-1">
                <label
                  htmlFor="ollama-url"
                  className="text-xs text-slate-500 dark:text-slate-400"
                >
                  {ti("ollamaUrlLabel")}
                </label>
                <input
                  id="ollama-url"
                  value={ollamaUrl}
                  placeholder="http://host:11434"
                  onChange={(e) => setOllamaUrl(e.target.value)}
                  className={`${inputClass} w-64`}
                />
              </div>
              <div className="flex flex-col gap-1">
                <label
                  htmlFor="ollama-model"
                  className="text-xs text-slate-500 dark:text-slate-400"
                >
                  {ti("ollamaModelLabel")}
                </label>
                <select
                  id="ollama-model"
                  value={ollamaModel}
                  onChange={(e) => setOllamaModel(e.target.value)}
                  className={`${inputClass} w-48`}
                >
                  {status.available_models.length === 0 && ollamaModel !== "" && (
                    <option value={ollamaModel}>{ollamaModel}</option>
                  )}
                  {status.available_models.map((model) => (
                    <option key={model} value={model}>
                      {model}
                    </option>
                  ))}
                </select>
              </div>
            </div>
            <div className="flex flex-wrap items-end gap-3">
              <div className="flex flex-col gap-1">
                <label
                  htmlFor="import-directory"
                  className="text-xs text-slate-500 dark:text-slate-400"
                >
                  {ti("directoryLabel")}
                </label>
                <input
                  id="import-directory"
                  value={directory}
                  onChange={(e) => setDirectory(e.target.value)}
                  className={`${inputClass} w-64`}
                />
              </div>
              <div className="flex flex-col gap-1">
                <label
                  htmlFor="import-minutes"
                  className="text-xs text-slate-500 dark:text-slate-400"
                >
                  {ti("pollMinutesLabel")}
                </label>
                <input
                  id="import-minutes"
                  type="number"
                  min="1"
                  max="1440"
                  value={minutes}
                  onChange={(e) => setMinutes(e.target.value)}
                  className={`${inputClass} w-24`}
                />
              </div>
              <button
                type="button"
                onClick={handleSave}
                disabled={
                  busy !== null ||
                  !dirty ||
                  !minutesValid ||
                  !directoryValid ||
                  !urlValid ||
                  ollamaModel === ""
                }
                className="flex items-center gap-1.5 rounded-lg border border-blue-700 bg-blue-700 px-3 py-1.5 text-xs font-medium text-white shadow-sm transition-all hover:border-blue-800 hover:bg-blue-800 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {busy === "save" ? (
                  <Loader2 size={13} className="animate-spin" />
                ) : (
                  <Save size={13} />
                )}
                {ti("save")}
              </button>
            </div>
            {!directoryValid && (
              <p className="text-xs text-amber-700 dark:text-amber-400">
                {ti("directoryInvalid")}
              </p>
            )}
            {!urlValid && (
              <p className="text-xs text-amber-700 dark:text-amber-400">
                {ti("ollamaUrlInvalid")}
              </p>
            )}
          </div>

          {status.last_error && (
            <p className="flex items-start gap-2 rounded-xl bg-amber-50 px-3 py-2 text-xs text-amber-700 dark:bg-amber-900/20 dark:text-amber-400">
              <AlertTriangle size={13} className="mt-0.5 shrink-0" />
              {status.last_error}
            </p>
          )}

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
              disabled={busy !== null || !enabled}
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

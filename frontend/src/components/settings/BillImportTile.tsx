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
  fetchImapFolders,
  fetchImportStatus,
  scanNow,
  testImap,
  testOllama,
  updateImportSettings,
  type ImportStatusOut,
  type LlmProvider,
  LLM_PROVIDERS,
} from "@/lib/imports-api";
import { Switch } from "@/components/ui/Switch";
import { Tile, type TileTranslator } from "./Tile";

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
  t: TileTranslator;
  isCollapsed?: boolean;
  onToggle?: () => void;
}) {
  const tp = useTranslations("SettingsPage");
  const ti = useTranslations("BillImport");

  const [status, setStatus] = useState<ImportStatusOut | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<"test" | "testImap" | "scan" | "save" | null>(null);
  const [message, setMessage] = useState<{ tone: "ok" | "error"; text: string } | null>(
    null,
  );
  const [refreshToken, setRefreshToken] = useState(0);

  const [enabled, setEnabled] = useState(false);
  const [directory, setDirectory] = useState("/data/import");
  const [minutes, setMinutes] = useState("15");
  const [ollamaUrl, setOllamaUrl] = useState("");
  const [llmProvider, setLlmProvider] = useState<LlmProvider>("ollama");
  const [llmModel, setLlmModel] = useState("");
  const [llmBaseUrl, setLlmBaseUrl] = useState("");
  const [llmApiKey, setLlmApiKey] = useState("");
  const [imapHost, setImapHost] = useState("");
  const [imapPort, setImapPort] = useState("993");
  const [imapUser, setImapUser] = useState("");
  const [imapPassword, setImapPassword] = useState("");
  const [imapFolder, setImapFolder] = useState("INBOX");
  const [imapTls, setImapTls] = useState(true);
  const [imapPollMinutes, setImapPollMinutes] = useState("15");
  const [imapMarkRead, setImapMarkRead] = useState(true);
  const [imapSenders, setImapSenders] = useState("");
  const [folders, setFolders] = useState<string[]>([]);
  const [foldersLoading, setFoldersLoading] = useState(false);

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
        setLlmProvider(data.llm_provider);
        setLlmModel(data.llm_model);
        setLlmBaseUrl(data.llm_base_url ?? "");
        setImapHost(data.imap_host ?? "");
        setImapPort(String(data.imap_port));
        setImapFolder(data.imap_folder);
        setImapTls(data.imap_tls);
        setImapPollMinutes(String(data.imap_poll_minutes));
        setImapMarkRead(data.imap_mark_read);
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
  const llmUrlValid = llmBaseUrl === "" || /^https?:\/\//.test(llmBaseUrl);
  const imapPortValue = parseInt(imapPort, 10);
  const imapPortValid =
    Number.isFinite(imapPortValue) && imapPortValue >= 1 && imapPortValue <= 65535;
  const imapMinutesValue = parseInt(imapPollMinutes, 10);
  const imapMinutesValid =
    Number.isFinite(imapMinutesValue) && imapMinutesValue >= 1 && imapMinutesValue <= 1440;
  const dirty =
    status !== null &&
    (enabled !== status.import_enabled ||
      directory !== status.import_dir ||
      minutesValue !== status.import_poll_minutes ||
      ollamaUrl !== (status.ollama_base_url ?? "") ||
      llmProvider !== status.llm_provider ||
      llmModel !== status.llm_model ||
      llmBaseUrl !== (status.llm_base_url ?? "") ||
      llmApiKey !== "" ||
      imapHost !== (status.imap_host ?? "") ||
      imapPortValue !== status.imap_port ||
      imapFolder !== status.imap_folder ||
      imapTls !== status.imap_tls ||
      imapMinutesValue !== status.imap_poll_minutes ||
      imapMarkRead !== status.imap_mark_read ||
      imapUser.trim() !== "" ||
      imapPassword !== "" ||
      imapSenders.trim() !== "");

  async function handleSave() {
    if (!minutesValid || !directoryValid || !urlValid || !llmUrlValid) return;
    if (!imapPortValid || !imapMinutesValid) return;
    if (llmProvider !== "ollama" && llmModel.trim() === "") return;
    setBusy("save");
    setMessage(null);
    try {
      const updated = await updateImportSettings({
        enabled,
        directory,
        poll_minutes: minutesValue,
        ollama_base_url: ollamaUrl,
        ...(llmProvider === "ollama" ? { ollama_model: llmModel.trim() || undefined } : {}),
        llm_provider: llmProvider,
        llm_model: llmModel.trim() || undefined,
        llm_base_url: llmBaseUrl.trim() === "" ? null : llmBaseUrl.trim(),
        ...(imapHost.trim() !== "" ? { imap_host: imapHost.trim() } : {}),
        imap_port: imapPortValid ? imapPortValue : undefined,
        ...(imapUser.trim() !== "" ? { imap_user: imapUser.trim() } : {}),
        ...(imapPassword !== "" ? { imap_password: imapPassword } : {}),
        imap_folder: imapFolder.trim() || undefined,
        imap_tls: imapTls,
        imap_poll_minutes: imapMinutesValid ? imapMinutesValue : undefined,
        imap_mark_read: imapMarkRead,
        ...(imapSenders.trim() !== "" ? { imap_allowed_senders: imapSenders.trim() } : {}),
      });
      setStatus(updated);
      setEnabled(updated.import_enabled);
      setDirectory(updated.import_dir);
      setMinutes(String(updated.import_poll_minutes));
      setOllamaUrl(updated.ollama_base_url ?? "");
      setLlmProvider(updated.llm_provider);
      setLlmModel(updated.llm_model);
      setLlmBaseUrl(updated.llm_base_url ?? "");
      setLlmApiKey("");
      setImapHost(updated.imap_host ?? "");
      setImapPort(String(updated.imap_port));
      setImapUser("");
      setImapFolder(updated.imap_folder);
      setImapTls(updated.imap_tls);
      setImapPollMinutes(String(updated.imap_poll_minutes));
      setImapMarkRead(updated.imap_mark_read);
      setImapPassword("");
      setImapSenders("");
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

  async function handleLoadFolders() {
    setFoldersLoading(true);
    setMessage(null);
    try {
      setFolders(await fetchImapFolders());
    } catch (err) {
      setMessage({
        tone: "error",
        text: err instanceof Error ? err.message : ti("foldersFailed"),
      });
    } finally {
      setFoldersLoading(false);
    }
  }

  async function handleTestImap() {
    setBusy("testImap");
    setMessage(null);
    try {
      const result = await testImap();
      setMessage({
        tone: result.ok ? "ok" : "error",
        text: result.ok
          ? ti("imapTestOk", { folder: result.folder ?? "", unseen: result.unseen ?? 0 })
          : (result.error ?? ti("testFailed")),
      });
    } catch (err) {
      setMessage({ tone: "error", text: err instanceof Error ? err.message : ti("testFailed") });
    } finally {
      setBusy(null);
      setRefreshToken((token) => token + 1);
    }
  }

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
              label={ti("llmLabel")}
              value={
                !status.llm_configured
                  ? ti("notConfigured")
                  : ti("llmReady", { provider: status.llm_provider, model: status.llm_model })
              }
              tone={status.llm_configured ? "ok" : "off"}
            />
            <StatusRow
              label={ti("imapLabel")}
              value={
                status.imap_configured
                  ? ti("imapReady", { folder: status.imap_folder })
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
                  htmlFor="llm-provider"
                  className="text-xs text-slate-500 dark:text-slate-400"
                >
                  {ti("llmProviderLabel")}
                </label>
                <select
                  id="llm-provider"
                  value={llmProvider}
                  onChange={(e) => setLlmProvider(e.target.value as LlmProvider)}
                  className={`${inputClass} w-40`}
                >
                  {LLM_PROVIDERS.map((p) => (
                    <option key={p} value={p}>
                      {ti(`llmProvider_${p}`)}
                    </option>
                  ))}
                </select>
              </div>
              <div className="flex flex-col gap-1">
                <label
                  htmlFor="llm-model"
                  className="text-xs text-slate-500 dark:text-slate-400"
                >
                  {ti("llmModelLabel")}
                </label>
                {llmProvider === "ollama" ? (
                  <select
                    id="llm-model"
                    value={llmModel}
                    onChange={(e) => setLlmModel(e.target.value)}
                    className={`${inputClass} w-48`}
                  >
                    {status.available_models.length === 0 && llmModel !== "" && (
                      <option value={llmModel}>{llmModel}</option>
                    )}
                    {status.available_models.map((model) => (
                      <option key={model} value={model}>
                        {model}
                      </option>
                    ))}
                  </select>
                ) : (
                  <input
                    id="llm-model"
                    value={llmModel}
                    placeholder={ti("llmModelPlaceholder")}
                    onChange={(e) => setLlmModel(e.target.value)}
                    className={`${inputClass} w-48`}
                  />
                )}
              </div>
              {(llmProvider === "ollama" || llmProvider === "opencode") && (
                <div className="flex flex-col gap-1">
                  <label
                    htmlFor="llm-url"
                    className="text-xs text-slate-500 dark:text-slate-400"
                  >
                    {ti("llmUrlLabel")}
                  </label>
                  <input
                    id="llm-url"
                    value={llmProvider === "ollama" ? ollamaUrl : llmBaseUrl}
                    placeholder={
                      llmProvider === "ollama" ? "http://host:11434" : "http://host:11434/v1"
                    }
                    onChange={(e) =>
                      llmProvider === "ollama"
                        ? setOllamaUrl(e.target.value)
                        : setLlmBaseUrl(e.target.value)
                    }
                    className={`${inputClass} w-64`}
                  />
                </div>
              )}
              {llmProvider !== "ollama" && (
                <div className="flex flex-col gap-1">
                  <label
                    htmlFor="llm-key"
                    className="text-xs text-slate-500 dark:text-slate-400"
                  >
                    {status.llm_api_key_configured
                      ? ti("llmKeySetLabel")
                      : ti("llmKeyLabel")}
                  </label>
                  <input
                    id="llm-key"
                    type="password"
                    value={llmApiKey}
                    placeholder={
                      status.llm_api_key_configured
                        ? ti("llmKeySetPlaceholder")
                        : ti("llmKeyPlaceholder")
                    }
                    autoComplete="off"
                    onChange={(e) => setLlmApiKey(e.target.value)}
                    className={`${inputClass} w-56`}
                  />
                </div>
              )}
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
                  !llmUrlValid ||
                  !imapPortValid ||
                  !imapMinutesValid ||
                  llmModel.trim() === ""
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
            {!llmUrlValid && (
              <p className="text-xs text-amber-700 dark:text-amber-400">
                {ti("llmUrlInvalid")}
              </p>
            )}
          </div>

          <div className="space-y-3 rounded-xl border border-slate-200 bg-slate-50 p-3 dark:border-slate-700 dark:bg-slate-900/40">
            <div className="flex flex-wrap items-end gap-3">
              <div className="flex flex-col gap-1">
                <label
                  htmlFor="imap-host"
                  className="text-xs text-slate-500 dark:text-slate-400"
                >
                  {ti("imapHostLabel")}
                </label>
                <input
                  id="imap-host"
                  value={imapHost}
                  placeholder="imap.example.com"
                  onChange={(e) => setImapHost(e.target.value)}
                  className={`${inputClass} w-48`}
                />
              </div>
              <div className="flex flex-col gap-1">
                <label
                  htmlFor="imap-port"
                  className="text-xs text-slate-500 dark:text-slate-400"
                >
                  {ti("imapPortLabel")}
                </label>
                <input
                  id="imap-port"
                  type="number"
                  min="1"
                  max="65535"
                  value={imapPort}
                  onChange={(e) => setImapPort(e.target.value)}
                  className={`${inputClass} w-24`}
                />
              </div>
              <div className="flex flex-col gap-1">
                <label
                  htmlFor="imap-user"
                  className="text-xs text-slate-500 dark:text-slate-400"
                >
                  {status.imap_user
                    ? ti("imapUserSetLabel", { user: status.imap_user })
                    : ti("imapUserLabel")}
                </label>
                <input
                  id="imap-user"
                  value={imapUser}
                  placeholder={ti("imapUserPlaceholder")}
                  autoComplete="off"
                  onChange={(e) => setImapUser(e.target.value)}
                  className={`${inputClass} w-48`}
                />
              </div>
              <div className="flex flex-col gap-1">
                <label
                  htmlFor="imap-password"
                  className="text-xs text-slate-500 dark:text-slate-400"
                >
                  {status.imap_password_configured
                    ? ti("imapPasswordSetLabel")
                    : ti("imapPasswordLabel")}
                </label>
                <input
                  id="imap-password"
                  type="password"
                  value={imapPassword}
                  placeholder={
                    status.imap_password_configured
                      ? ti("imapPasswordSetPlaceholder")
                      : ti("imapPasswordPlaceholder")
                  }
                  autoComplete="new-password"
                  onChange={(e) => setImapPassword(e.target.value)}
                  className={`${inputClass} w-48`}
                />
              </div>
            </div>
            <div className="flex flex-wrap items-end gap-3">
              <div className="flex flex-col gap-1">
                <label
                  htmlFor="imap-folder"
                  className="text-xs text-slate-500 dark:text-slate-400"
                >
                  {ti("imapFolderLabel")}
                </label>
                <div className="flex gap-2">
                  {folders.length > 0 ? (
                    <select
                      id="imap-folder"
                      value={imapFolder}
                      onChange={(e) => setImapFolder(e.target.value)}
                      className={`${inputClass} w-48`}
                    >
                      {!folders.includes(imapFolder) && (
                        <option value={imapFolder}>{imapFolder}</option>
                      )}
                      {folders.map((f) => (
                        <option key={f} value={f}>
                          {f}
                        </option>
                      ))}
                    </select>
                  ) : (
                    <input
                      id="imap-folder"
                      value={imapFolder}
                      onChange={(e) => setImapFolder(e.target.value)}
                      className={`${inputClass} w-48`}
                    />
                  )}
                  <button
                    type="button"
                    onClick={handleLoadFolders}
                    disabled={foldersLoading || busy !== null}
                    title={ti("foldersButton")}
                    className="rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 text-slate-600 shadow-sm transition-all hover:border-blue-300 hover:bg-blue-50 hover:text-blue-700 disabled:cursor-not-allowed disabled:opacity-50 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-400"
                  >
                    {foldersLoading ? (
                      <Loader2 size={13} className="animate-spin" />
                    ) : (
                      <RefreshCw size={13} />
                    )}
                  </button>
                </div>
              </div>
              <div className="flex flex-col gap-1">
                <label
                  htmlFor="imap-minutes"
                  className="text-xs text-slate-500 dark:text-slate-400"
                >
                  {ti("pollMinutesLabel")}
                </label>
                <input
                  id="imap-minutes"
                  type="number"
                  min="1"
                  max="1440"
                  value={imapPollMinutes}
                  onChange={(e) => setImapPollMinutes(e.target.value)}
                  className={`${inputClass} w-24`}
                />
              </div>
              <label className="flex cursor-pointer items-center gap-2 pb-2 text-xs text-slate-600 dark:text-slate-400">
                <input
                  type="checkbox"
                  checked={imapTls}
                  onChange={(e) => setImapTls(e.target.checked)}
                  className="h-4 w-4 rounded accent-blue-700"
                />
                {ti("imapTlsLabel")}
              </label>
              <label className="flex cursor-pointer items-center gap-2 pb-2 text-xs text-slate-600 dark:text-slate-400">
                <input
                  type="checkbox"
                  checked={imapMarkRead}
                  onChange={(e) => setImapMarkRead(e.target.checked)}
                  className="h-4 w-4 rounded accent-blue-700"
                />
                {ti("imapMarkReadLabel")}
              </label>
            </div>
            <div className="flex flex-col gap-1">
              <label
                htmlFor="imap-senders"
                className="text-xs text-slate-500 dark:text-slate-400"
              >
                {ti("imapSendersLabel")}
              </label>
              <input
                id="imap-senders"
                value={imapSenders}
                placeholder={ti("imapSendersPlaceholder")}
                onChange={(e) => setImapSenders(e.target.value)}
                className={`${inputClass} w-full`}
              />
            </div>
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
              disabled={busy !== null || !status.llm_configured}
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
              onClick={handleTestImap}
              disabled={busy !== null || !status.imap_configured}
              className="flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-600 shadow-sm transition-all hover:border-blue-300 hover:bg-blue-50 hover:text-blue-700 disabled:cursor-not-allowed disabled:opacity-50 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-400 dark:hover:border-blue-700 dark:hover:bg-blue-900/20 dark:hover:text-blue-400"
            >
              {busy === "testImap" ? (
                <Loader2 size={13} className="animate-spin" />
              ) : (
                <Server size={13} />
              )}
              {ti("imapTestButton")}
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

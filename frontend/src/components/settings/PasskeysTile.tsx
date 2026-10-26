"use client";

import { useEffect, useState, useCallback, useSyncExternalStore, FormEvent } from "react";
import {
  Fingerprint,
  Trash2,
  Plus,
  ShieldAlert,
  Loader2,
  CheckCircle2,
  Clock,
  KeyRound,
} from "lucide-react";
import { Tile, TileTranslator } from "./Tile";
import {
  fetchPasskeys,
  deletePasskey,
  registerPasskey,
  browserSupportsWebAuthn,
  PasskeyItem,
} from "@/lib/passkeys-api";

function subscribeNever() {
  return () => {};
}

function getSecureContextSnapshot(): boolean {
  if (typeof window === "undefined") return true;
  return window.isSecureContext;
}

function getSecureContextServerSnapshot(): boolean {
  return true;
}

function getWebAuthnSnapshot(): boolean {
  if (typeof window === "undefined") return false;
  return browserSupportsWebAuthn();
}

function getWebAuthnServerSnapshot(): boolean {
  return false;
}

export function PasskeysTile({
  t,
  isCollapsed,
  onToggle,
}: {
  t: TileTranslator;
  isCollapsed?: boolean;
  onToggle?: () => void;
}) {
  const isSecure = useSyncExternalStore(
    subscribeNever,
    getSecureContextSnapshot,
    getSecureContextServerSnapshot,
  );
  const isSupported = useSyncExternalStore(
    subscribeNever,
    getWebAuthnSnapshot,
    getWebAuthnServerSnapshot,
  );

  const [passkeys, setPasskeys] = useState<PasskeyItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [registering, setRegistering] = useState(false);
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const [keyName, setKeyName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const loadPasskeys = useCallback(() => {
    fetchPasskeys()
      .then(setPasskeys)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    loadPasskeys();
  }, [loadPasskeys]);

  async function handleRegister(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSuccess(null);
    setRegistering(true);

    try {
      const created = await registerPasskey(keyName);
      setPasskeys((prev) => [created, ...prev.filter((p) => p.id !== created.id)]);
      setKeyName("");
      setSuccess(`Successfully registered "${created.name}"`);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      if (
        message.toLowerCase().includes("user canceled") ||
        message.toLowerCase().includes("abort") ||
        message.toLowerCase().includes("not allowed")
      ) {
        setError("Passkey registration was cancelled or timed out.");
      } else {
        setError(message || "Failed to register passkey.");
      }
    } finally {
      setRegistering(false);
    }
  }

  async function handleDelete(passkey: PasskeyItem) {
    if (!window.confirm(t("passkeys.deleteConfirm"))) {
      return;
    }
    setError(null);
    setSuccess(null);
    setDeletingId(passkey.id);

    try {
      await deletePasskey(passkey.id);
      setPasskeys((prev) => prev.filter((p) => p.id !== passkey.id));
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      setError(message || "Failed to delete passkey.");
    } finally {
      setDeletingId(null);
    }
  }

  function formatDate(iso: string | null): string {
    if (!iso) return t("passkeys.neverUsed");
    try {
      return new Date(iso).toLocaleDateString(undefined, {
        year: "numeric",
        month: "short",
        day: "numeric",
      });
    } catch {
      return iso;
    }
  }

  return (
    <Tile
      color="blue"
      icon={Fingerprint}
      title={t("passkeys.title")}
      description={t("passkeys.description")}
      isCollapsed={isCollapsed}
      onToggle={onToggle}
      t={t}
    >
      <div className="space-y-4">
        {!isSecure && (
          <div className="flex items-start gap-3 rounded-lg border border-amber-300 bg-amber-50 p-3.5 text-amber-900 dark:border-amber-700/60 dark:bg-amber-950/30 dark:text-amber-200">
            <ShieldAlert size={18} className="shrink-0 mt-0.5 text-amber-600 dark:text-amber-400" />
            <div className="text-xs leading-relaxed">
              <span className="font-semibold block mb-0.5">Insecure Connection Detected</span>
              {t("passkeys.notSecureWarning")}
            </div>
          </div>
        )}

        {isSecure && !isSupported && (
          <div className="flex items-start gap-3 rounded-lg border border-amber-300 bg-amber-50 p-3.5 text-amber-900 dark:border-amber-700/60 dark:bg-amber-950/30 dark:text-amber-200">
            <ShieldAlert size={18} className="shrink-0 mt-0.5 text-amber-600 dark:text-amber-400" />
            <div className="text-xs leading-relaxed">
              Passkeys and WebAuthn are not supported by this browser.
            </div>
          </div>
        )}

        {/* Existing Passkeys List */}
        <div>
          <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400 mb-2">
            Registered Passkeys ({passkeys.length})
          </h3>

          {loading ? (
            <div className="flex items-center gap-2 py-4 text-xs text-slate-500 dark:text-slate-400">
              <Loader2 size={16} className="animate-spin text-blue-600 dark:text-blue-400" />
              Loading passkeys…
            </div>
          ) : passkeys.length === 0 ? (
            <div className="rounded-lg border border-dashed border-slate-200 dark:border-slate-700 p-4 text-center text-xs text-slate-500 dark:text-slate-400">
              {t("passkeys.noPasskeys")}
            </div>
          ) : (
            <div className="divide-y divide-slate-100 dark:divide-slate-700/60 rounded-lg border border-slate-200 dark:border-slate-700 overflow-hidden">
              {passkeys.map((p) => (
                <div
                  key={p.id}
                  className="flex items-center justify-between p-3.5 bg-slate-50/50 dark:bg-slate-800/50 hover:bg-slate-50 dark:hover:bg-slate-800 transition-colors"
                >
                  <div className="flex items-center gap-3 min-w-0">
                    <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-blue-100 text-blue-600 dark:bg-blue-900/50 dark:text-blue-400 shrink-0">
                      <KeyRound size={16} />
                    </div>
                    <div className="min-w-0">
                      <p className="text-sm font-medium text-slate-800 dark:text-slate-200 truncate">
                        {p.name}
                      </p>
                      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-slate-500 dark:text-slate-400 mt-0.5">
                        <span>
                          {t("passkeys.registeredOn")}: {formatDate(p.created_at)}
                        </span>
                        <span className="flex items-center gap-1">
                          <Clock size={11} className="inline" />
                          {t("passkeys.lastUsed")}: {formatDate(p.last_used_at)}
                        </span>
                      </div>
                    </div>
                  </div>

                  <button
                    type="button"
                    onClick={() => handleDelete(p)}
                    disabled={deletingId === p.id}
                    title="Remove passkey"
                    className="p-1.5 rounded-lg text-slate-400 hover:text-red-600 hover:bg-red-50 dark:hover:bg-red-950/40 dark:hover:text-red-400 transition-colors disabled:opacity-50"
                  >
                    {deletingId === p.id ? (
                      <Loader2 size={16} className="animate-spin text-red-500" />
                    ) : (
                      <Trash2 size={16} />
                    )}
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Register New Passkey Form */}
        <form onSubmit={handleRegister} className="pt-2 border-t border-slate-100 dark:border-slate-700/60">
          <div className="flex flex-col sm:flex-row gap-2.5 items-stretch sm:items-end">
            <div className="flex-1">
              <label
                htmlFor="passkey-name"
                className="block text-xs font-medium text-slate-700 dark:text-slate-300 mb-1"
              >
                {t("passkeys.keyNameLabel")}
              </label>
              <input
                id="passkey-name"
                type="text"
                value={keyName}
                onChange={(e) => setKeyName(e.target.value)}
                placeholder={t("passkeys.keyNamePlaceholder")}
                disabled={registering || !isSupported}
                className="w-full rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-sm text-slate-800 placeholder:text-slate-400 outline-none transition-all focus:border-blue-500 focus:ring-2 focus:ring-blue-100 dark:border-slate-600 dark:bg-slate-700 dark:text-slate-100 dark:focus:border-blue-600 dark:focus:ring-blue-900/40 disabled:opacity-50"
              />
            </div>
            <button
              type="submit"
              disabled={registering || !isSupported}
              className="inline-flex items-center justify-center gap-1.5 rounded-lg border border-blue-700 bg-blue-700 px-4 py-2 text-sm font-medium text-white shadow-sm transition-all hover:border-blue-800 hover:bg-blue-800 disabled:opacity-50 shrink-0"
            >
              {registering ? (
                <>
                  <Loader2 size={16} className="animate-spin" />
                  {t("passkeys.registering")}
                </>
              ) : (
                <>
                  <Plus size={16} />
                  {t("passkeys.registerButton")}
                </>
              )}
            </button>
          </div>
        </form>

        {error && (
          <p className="text-xs text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-950/30 border border-red-200 dark:border-red-900/40 rounded-lg p-2.5">
            {error}
          </p>
        )}

        {success && (
          <div className="flex items-center gap-2 text-xs text-emerald-700 dark:text-emerald-300 bg-emerald-50 dark:bg-emerald-950/30 border border-emerald-200 dark:border-emerald-900/40 rounded-lg p-2.5">
            <CheckCircle2 size={15} className="text-emerald-600 dark:text-emerald-400 shrink-0" />
            <span>{success}</span>
          </div>
        )}
      </div>
    </Tile>
  );
}

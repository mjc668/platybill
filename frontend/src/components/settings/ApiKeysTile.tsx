"use client";

import { useCallback, useEffect, useState } from "react";
import { Check, Copy, KeyRound, Loader2, Plus, Trash2 } from "lucide-react";
import {
  createApiKey,
  deleteApiKey,
  fetchApiKeys,
  type ApiKeyOut,
} from "@/lib/api-keys-api";
import {
  ALL_SCOPES,
  SCOPE_LABELS,
  SCOPE_PRESETS,
  type PermissionScope,
} from "@/lib/scopes";
import { Tile, type TileTranslator } from "./Tile";

export function ApiKeysTile({ t }: { t: TileTranslator }) {
  const [keys, setKeys] = useState<ApiKeyOut[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [name, setName] = useState("");
  const [scopes, setScopes] = useState<PermissionScope[]>(SCOPE_PRESETS.viewer);
  const [expiresInDays, setExpiresInDays] = useState<string>("90");
  const [creating, setCreating] = useState(false);

  const [newRawKey, setNewRawKey] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [deletingId, setDeletingId] = useState<number | null>(null);

  const load = useCallback(async () => {
    try {
      const list = await fetchApiKeys();
      setKeys(list);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load API keys");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    fetchApiKeys()
      .then((list) => {
        if (!cancelled) {
          setKeys(list);
          setError(null);
          setLoading(false);
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Failed to load API keys");
          setLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  function toggleScope(scope: PermissionScope) {
    setScopes((prev) =>
      prev.includes(scope) ? prev.filter((s) => s !== scope) : [...prev, scope],
    );
  }

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim() || scopes.length === 0) return;
    setCreating(true);
    setError(null);
    setNewRawKey(null);
    setCopied(false);
    try {
      const parsedDays = expiresInDays === "" ? null : parseInt(expiresInDays, 10);
      const created = await createApiKey({
        name: name.trim(),
        scopes,
        expires_in_days: Number.isFinite(parsedDays) ? parsedDays : null,
      });
      setNewRawKey(created.key);
      setName("");
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create API key");
    } finally {
      setCreating(false);
    }
  }

  async function handleCopy() {
    if (!newRawKey) return;
    await navigator.clipboard.writeText(newRawKey);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  async function handleRevoke(keyId: number) {
    setDeletingId(keyId);
    setError(null);
    try {
      await deleteApiKey(keyId);
      setKeys((prev) => prev.filter((k) => k.id !== keyId));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to revoke API key");
    } finally {
      setDeletingId(null);
    }
  }

  return (
    <Tile
      color="blue"
      icon={KeyRound}
      title={t("apiKeys.title")}
      description={t("apiKeys.description")}
      t={t}
    >
      {loading ? (
        <div className="h-20 animate-pulse rounded-lg bg-slate-100 dark:bg-slate-700" />
      ) : (
        <div className="space-y-4 text-sm">
          {error && (
            <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700 dark:border-red-800 dark:bg-red-900/20 dark:text-red-400">
              {error}
            </div>
          )}

          {newRawKey && (
            <div className="space-y-2 rounded-lg border border-amber-300 bg-amber-50 p-3 dark:border-amber-700 dark:bg-amber-900/20">
              <p className="text-xs font-semibold text-amber-900 dark:text-amber-300">
                Copy your new API key now — it will not be shown again:
              </p>
              <div className="flex items-center gap-2">
                <code className="flex-1 break-all rounded bg-white px-2.5 py-1.5 font-mono text-xs text-slate-800 dark:bg-slate-900 dark:text-slate-100">
                  {newRawKey}
                </code>
                <button
                  type="button"
                  onClick={handleCopy}
                  className="flex shrink-0 items-center gap-1 rounded-lg bg-amber-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-amber-700"
                >
                  {copied ? <Check size={13} /> : <Copy size={13} />}
                  {copied ? "Copied" : "Copy"}
                </button>
              </div>
              <p className="text-[11px] text-amber-800 dark:text-amber-400">
                Pass via <code>Authorization: Bearer &lt;key&gt;</code> or{" "}
                <code>X-API-Key: &lt;key&gt;</code>.
              </p>
            </div>
          )}

          {keys.length > 0 && (
            <div className="space-y-2">
              {keys.map((item) => (
                <div
                  key={item.id}
                  className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-slate-200 px-3 py-2.5 dark:border-slate-700"
                >
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="font-medium text-slate-800 dark:text-slate-100">
                        {item.name}
                      </span>
                      <code className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-[11px] text-slate-600 dark:bg-slate-700 dark:text-slate-300">
                        {item.key_prefix}…
                      </code>
                    </div>
                    <div className="mt-1 flex flex-wrap items-center gap-1.5 text-[11px] text-slate-500 dark:text-slate-400">
                      <span>{item.scopes.join(", ")}</span>
                      {item.expires_at && (
                        <span>
                          · Expires {new Date(item.expires_at).toLocaleDateString()}
                        </span>
                      )}
                      {item.last_used_at && (
                        <span>
                          · Last used {new Date(item.last_used_at).toLocaleDateString()}
                        </span>
                      )}
                    </div>
                  </div>
                  <button
                    type="button"
                    disabled={deletingId === item.id}
                    onClick={() => handleRevoke(item.id)}
                    aria-label={`Revoke ${item.name}`}
                    className="rounded-lg p-1.5 text-slate-400 hover:bg-red-50 hover:text-red-600 dark:hover:bg-red-900/20 dark:hover:text-red-400"
                  >
                    <Trash2 size={14} />
                  </button>
                </div>
              ))}
            </div>
          )}

          <form
            onSubmit={handleCreate}
            className="space-y-3 rounded-lg border border-slate-200 bg-slate-50/70 p-3 dark:border-slate-700 dark:bg-slate-900/30"
          >
            <p className="text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
              Create API key
            </p>
            <div className="grid gap-2 sm:grid-cols-2">
              <input
                type="text"
                required
                maxLength={100}
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="e.g. Home Assistant / Agent"
                className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-800 outline-none focus:border-blue-500 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-100"
              />
              <select
                value={expiresInDays}
                onChange={(e) => setExpiresInDays(e.target.value)}
                aria-label="Key expiration"
                className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-800 outline-none focus:border-blue-500 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-100"
              >
                <option value="30">Expires in 30 days</option>
                <option value="90">Expires in 90 days</option>
                <option value="365">Expires in 1 year</option>
                <option value="">No expiration</option>
              </select>
            </div>

            <div className="flex flex-wrap items-center gap-2 text-xs">
              <span className="text-slate-500 dark:text-slate-400">Presets:</span>
              <button
                type="button"
                onClick={() => setScopes(SCOPE_PRESETS.viewer)}
                className="rounded-md border border-slate-200 bg-white px-2 py-1 text-slate-600 hover:border-blue-300 hover:text-blue-700 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-300"
              >
                Read-only
              </button>
              <button
                type="button"
                onClick={() => setScopes(SCOPE_PRESETS.contributor)}
                className="rounded-md border border-slate-200 bg-white px-2 py-1 text-slate-600 hover:border-blue-300 hover:text-blue-700 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-300"
              >
                Agent (bills + payments + imports)
              </button>
            </div>

            <div className="grid gap-2 sm:grid-cols-2">
              {ALL_SCOPES.map((scope) => (
                <label
                  key={scope}
                  className="flex items-start gap-2 text-xs text-slate-700 dark:text-slate-300"
                >
                  <input
                    type="checkbox"
                    checked={scopes.includes(scope)}
                    onChange={() => toggleScope(scope)}
                    className="mt-0.5 rounded border-slate-300 text-blue-600"
                  />
                  <span>
                    <span className="font-medium">{SCOPE_LABELS[scope].label}</span>
                    <span className="block text-[11px] text-slate-400">{scope}</span>
                  </span>
                </label>
              ))}
            </div>

            <button
              type="submit"
              disabled={creating || !name.trim() || scopes.length === 0}
              className="flex items-center gap-1.5 rounded-lg bg-blue-700 px-3.5 py-2 text-xs font-medium text-white shadow-sm hover:bg-blue-800 disabled:opacity-50"
            >
              {creating ? (
                <Loader2 size={14} className="animate-spin" />
              ) : (
                <Plus size={14} />
              )}
              Create API key
            </button>
          </form>
        </div>
      )}
    </Tile>
  );
}

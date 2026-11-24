"use client";

import { useCallback, useEffect, useState } from "react";
import { Check, Loader2, Pencil, Plus, Trash2, Users } from "lucide-react";
import {
  acceptFamilyInvite,
  addFamilyMember,
  deleteFamilyInvite,
  fetchFamily,
  removeFamilyMember,
  updateFamilyMemberScopes,
  type FamilyMemberOut,
  type FamilyOverviewOut,
} from "@/lib/family-api";
import {
  ALL_SCOPES,
  SCOPE_LABELS,
  SCOPE_PRESETS,
  type PermissionScope,
} from "@/lib/scopes";
import { Tile, type TileTranslator } from "./Tile";

export function FamilyTile({ t }: { t: TileTranslator }) {
  const [data, setData] = useState<FamilyOverviewOut | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [email, setEmail] = useState("");
  const [initialPassword, setInitialPassword] = useState("");
  const [scopes, setScopes] = useState<PermissionScope[]>(SCOPE_PRESETS.contributor);
  const [submitting, setSubmitting] = useState(false);

  const [editingMemberId, setEditingMemberId] = useState<number | null>(null);
  const [editScopes, setEditScopes] = useState<PermissionScope[]>([]);
  const [busyId, setBusyId] = useState<number | null>(null);

  const load = useCallback(async () => {
    try {
      const res = await fetchFamily();
      setData(res);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load family");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    fetchFamily()
      .then((res) => {
        if (!cancelled) {
          setData(res);
          setError(null);
          setLoading(false);
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Failed to load family");
          setLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  function toggleScope(
    list: PermissionScope[],
    setter: (next: PermissionScope[]) => void,
    scope: PermissionScope,
  ) {
    setter(list.includes(scope) ? list.filter((s) => s !== scope) : [...list, scope]);
  }

  async function handleAdd(e: React.FormEvent) {
    e.preventDefault();
    if (!email.trim() || scopes.length === 0) return;
    setSubmitting(true);
    setError(null);
    try {
      const next = await addFamilyMember({
        email: email.trim(),
        scopes,
        ...(initialPassword ? { initial_password: initialPassword } : {}),
      });
      setData(next);
      setEmail("");
      setInitialPassword("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to add family member");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleSaveEdit(member: FamilyMemberOut) {
    if (editScopes.length === 0) return;
    setBusyId(member.id);
    setError(null);
    try {
      await updateFamilyMemberScopes(member.id, editScopes);
      setEditingMemberId(null);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to update permissions");
    } finally {
      setBusyId(null);
    }
  }

  async function handleRemove(memberId: number) {
    setBusyId(memberId);
    setError(null);
    try {
      await removeFamilyMember(memberId);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to remove member");
    } finally {
      setBusyId(null);
    }
  }

  async function handleAcceptInvite(inviteId: number) {
    setBusyId(inviteId);
    setError(null);
    try {
      await acceptFamilyInvite(inviteId);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to accept invite");
    } finally {
      setBusyId(null);
    }
  }

  async function handleDeleteInvite(inviteId: number) {
    setBusyId(inviteId);
    setError(null);
    try {
      await deleteFamilyInvite(inviteId);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to remove invite");
    } finally {
      setBusyId(null);
    }
  }

  return (
    <Tile
      color="blue"
      icon={Users}
      title={t("family.title")}
      description={t("family.description")}
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

          {/* Incoming invites for this user */}
          {data && data.incoming_invites.length > 0 && (
            <div className="space-y-2 rounded-lg border border-blue-200 bg-blue-50/70 p-3 dark:border-blue-800 dark:bg-blue-900/20">
              <p className="text-xs font-semibold uppercase tracking-wide text-blue-700 dark:text-blue-300">
                Pending family invitations
              </p>
              {data.incoming_invites.map((inv) => (
                <div
                  key={inv.id}
                  className="flex flex-wrap items-center justify-between gap-2 rounded-lg bg-white px-3 py-2 dark:bg-slate-800"
                >
                  <div>
                    <p className="font-medium text-slate-800 dark:text-slate-100">
                      {inv.owner_email}
                    </p>
                    <p className="text-xs text-slate-500 dark:text-slate-400">
                      Scopes: {inv.scopes.join(", ")}
                    </p>
                  </div>
                  <div className="flex items-center gap-2">
                    <button
                      type="button"
                      disabled={busyId === inv.id}
                      onClick={() => handleAcceptInvite(inv.id)}
                      className="rounded-lg bg-blue-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-700 disabled:opacity-50"
                    >
                      Accept
                    </button>
                    <button
                      type="button"
                      disabled={busyId === inv.id}
                      onClick={() => handleDeleteInvite(inv.id)}
                      className="rounded-lg border border-slate-200 px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-50 dark:border-slate-600 dark:text-slate-300 dark:hover:bg-slate-700"
                    >
                      Decline
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* Non-owner member banner */}
          {data && !data.is_owner && (
            <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 dark:border-slate-700 dark:bg-slate-900/40">
              <p className="font-medium text-slate-800 dark:text-slate-100">
                Member of {data.owner_email}&apos;s family
              </p>
              <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                Your scopes: {data.my_scopes.join(", ")}
              </p>
            </div>
          )}

          {/* Existing members list */}
          {data && data.members.length > 0 && (
            <div className="space-y-2">
              <p className="text-xs font-semibold uppercase tracking-wide text-slate-400 dark:text-slate-500">
                Family members
              </p>
              {data.members.map((member) => (
                <div
                  key={member.id}
                  className="rounded-lg border border-slate-200 p-3 dark:border-slate-700"
                >
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div>
                      <p className="font-medium text-slate-800 dark:text-slate-100">
                        {member.email}
                      </p>
                      {editingMemberId !== member.id && (
                        <div className="mt-1 flex flex-wrap gap-1">
                          {member.scopes.map((s) => (
                            <span
                              key={s}
                              className="rounded bg-slate-100 px-1.5 py-0.5 text-[11px] font-medium text-slate-600 dark:bg-slate-700 dark:text-slate-300"
                            >
                              {s}
                            </span>
                          ))}
                        </div>
                      )}
                    </div>
                    {data.is_owner && (
                      <div className="flex items-center gap-1.5">
                        {editingMemberId === member.id ? (
                          <button
                            type="button"
                            disabled={busyId === member.id || editScopes.length === 0}
                            onClick={() => handleSaveEdit(member)}
                            className="flex items-center gap-1 rounded-lg bg-blue-600 px-2.5 py-1 text-xs font-medium text-white hover:bg-blue-700 disabled:opacity-50"
                          >
                            <Check size={13} /> Save
                          </button>
                        ) : (
                          <button
                            type="button"
                            onClick={() => {
                              setEditingMemberId(member.id);
                              setEditScopes(member.scopes);
                            }}
                            aria-label={`Edit ${member.email}`}
                            className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-700 dark:hover:bg-slate-700 dark:hover:text-slate-200"
                          >
                            <Pencil size={14} />
                          </button>
                        )}
                        <button
                          type="button"
                          disabled={busyId === member.id}
                          onClick={() => handleRemove(member.id)}
                          aria-label={`Remove ${member.email}`}
                          className="rounded-lg p-1.5 text-slate-400 hover:bg-red-50 hover:text-red-600 dark:hover:bg-red-900/20 dark:hover:text-red-400"
                        >
                          <Trash2 size={14} />
                        </button>
                      </div>
                    )}
                  </div>

                  {editingMemberId === member.id && (
                    <div className="mt-3 grid gap-2 sm:grid-cols-2">
                      {ALL_SCOPES.map((scope) => (
                        <label
                          key={scope}
                          className="flex items-start gap-2 text-xs text-slate-700 dark:text-slate-300"
                        >
                          <input
                            type="checkbox"
                            checked={editScopes.includes(scope)}
                            onChange={() => toggleScope(editScopes, setEditScopes, scope)}
                            className="mt-0.5 rounded border-slate-300 text-blue-600"
                          />
                          <span>
                            <span className="font-medium">{SCOPE_LABELS[scope].label}</span>
                            <span className="block text-[11px] text-slate-400">
                              {scope}
                            </span>
                          </span>
                        </label>
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}

          {/* Outgoing invites */}
          {data && data.is_owner && data.outgoing_invites.length > 0 && (
            <div className="space-y-2">
              <p className="text-xs font-semibold uppercase tracking-wide text-slate-400 dark:text-slate-500">
                Pending invites
              </p>
              {data.outgoing_invites.map((inv) => (
                <div
                  key={inv.id}
                  className="flex items-center justify-between rounded-lg border border-dashed border-slate-200 px-3 py-2 text-xs dark:border-slate-700"
                >
                  <div>
                    <span className="font-medium text-slate-700 dark:text-slate-200">
                      {inv.email}
                    </span>
                    <span className="ml-2 text-slate-400">({inv.scopes.join(", ")})</span>
                  </div>
                  <button
                    type="button"
                    disabled={busyId === inv.id}
                    onClick={() => handleDeleteInvite(inv.id)}
                    className="text-slate-400 hover:text-red-600"
                  >
                    Cancel
                  </button>
                </div>
              ))}
            </div>
          )}

          {/* Add member form (owner only) */}
          {(!data || data.is_owner) && (
            <form
              onSubmit={handleAdd}
              className="space-y-3 rounded-lg border border-slate-200 bg-slate-50/70 p-3 dark:border-slate-700 dark:bg-slate-900/30"
            >
              <p className="text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
                Add or invite family member
              </p>
              <div className="grid gap-2 sm:grid-cols-2">
                <input
                  type="email"
                  required
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="member@example.com"
                  className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-800 outline-none focus:border-blue-500 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-100"
                />
                <input
                  type="password"
                  value={initialPassword}
                  onChange={(e) => setInitialPassword(e.target.value)}
                  placeholder="Initial password (if new account)"
                  autoComplete="new-password"
                  className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-800 outline-none focus:border-blue-500 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-100"
                />
              </div>

              <div className="flex flex-wrap items-center gap-2 text-xs">
                <span className="text-slate-500 dark:text-slate-400">Presets:</span>
                {(["viewer", "contributor", "admin"] as const).map((preset) => (
                  <button
                    key={preset}
                    type="button"
                    onClick={() => setScopes(SCOPE_PRESETS[preset])}
                    className="rounded-md border border-slate-200 bg-white px-2 py-1 capitalize text-slate-600 hover:border-blue-300 hover:text-blue-700 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-300"
                  >
                    {preset}
                  </button>
                ))}
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
                      onChange={() => toggleScope(scopes, setScopes, scope)}
                      className="mt-0.5 rounded border-slate-300 text-blue-600"
                    />
                    <span>
                      <span className="font-medium">{SCOPE_LABELS[scope].label}</span>
                      <span className="block text-[11px] text-slate-400">
                        {SCOPE_LABELS[scope].hint}
                      </span>
                    </span>
                  </label>
                ))}
              </div>

              <button
                type="submit"
                disabled={submitting || !email.trim() || scopes.length === 0}
                className="flex items-center gap-1.5 rounded-lg bg-blue-700 px-3.5 py-2 text-xs font-medium text-white shadow-sm hover:bg-blue-800 disabled:opacity-50"
              >
                {submitting ? (
                  <Loader2 size={14} className="animate-spin" />
                ) : (
                  <Plus size={14} />
                )}
                Add member
              </button>
            </form>
          )}
        </div>
      )}
    </Tile>
  );
}

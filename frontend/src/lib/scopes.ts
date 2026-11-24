export type PermissionScope =
  | "bills:read"
  | "bills:write"
  | "payments:write"
  | "imports:read"
  | "imports:write"
  | "export:write";

export const ALL_SCOPES: PermissionScope[] = [
  "bills:read",
  "bills:write",
  "payments:write",
  "imports:read",
  "imports:write",
  "export:write",
];

export const SCOPE_LABELS: Record<PermissionScope, { label: string; hint: string }> = {
  "bills:read": { label: "View bills & payments", hint: "Read bills, payments, stats, and exports" },
  "bills:write": { label: "Manage bills", hint: "Create, edit, archive, and delete bills/categories/accounts" },
  "payments:write": { label: "Record payments", hint: "Mark bills paid, partial payments, and revert" },
  "imports:read": { label: "View imports", hint: "Read pending bill import drafts" },
  "imports:write": { label: "Manage imports", hint: "Upload bills and confirm/discard import drafts" },
  "export:write": { label: "Restore backups", hint: "Restore JSON backups and snapshots (destructive)" },
};

export const SCOPE_PRESETS: Record<"viewer" | "contributor" | "admin", PermissionScope[]> = {
  viewer: ["bills:read", "imports:read"],
  contributor: ["bills:read", "bills:write", "payments:write", "imports:read", "imports:write"],
  admin: ALL_SCOPES,
};

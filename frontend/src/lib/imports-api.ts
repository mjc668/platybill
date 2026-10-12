import { apiFetch, extractApiError, getApiBaseUrl, getApiPrefix } from "./api";

export type ImportSource = "upload" | "directory" | "email";
export type ImportStatus = "pending" | "confirmed" | "discarded" | "failed";

export interface ImportDraftOut {
  id: number;
  source: ImportSource;
  filename: string | null;
  provider: string | null;
  amount: string | null;
  currency: string | null;
  due_date: string | null;
  period: string | null;
  matched_bill_id: number | null;
  matched_bill_name: string | null;
  status: ImportStatus;
  error: string | null;
  created_at: string;
  processed_at: string | null;
}

export interface ImportStatusOut {
  ollama_configured: boolean;
  ollama_reachable: boolean;
  ollama_model: string;
  model_available: boolean | null;
  import_enabled: boolean;
  import_dir: string;
  import_poll_minutes: number;
  imap_configured: boolean;
  imap_user: string | null;
  pending_count: number;
  last_error: string | null;
}

export interface TestOllamaOut {
  ok: boolean;
  model: string;
  model_available: boolean;
  error: string | null;
}

export interface ImportConfirmOut {
  draft_id: number;
  bill_id: number;
  instance_id: number;
  created_instance: boolean;
}

export function fetchImportDrafts(status = "pending"): Promise<ImportDraftOut[]> {
  return apiFetch<ImportDraftOut[]>(`/import/drafts?status=${encodeURIComponent(status)}`);
}

export function fetchImportStatus(): Promise<ImportStatusOut> {
  return apiFetch<ImportStatusOut>("/import/status");
}

export function updateImportSettings(data: {
  enabled?: boolean;
  directory?: string;
  poll_minutes?: number;
}): Promise<ImportStatusOut> {
  return apiFetch<ImportStatusOut>("/import/settings", {
    method: "PATCH",
    body: JSON.stringify(data),
  });
}

export function testOllama(): Promise<TestOllamaOut> {
  return apiFetch<TestOllamaOut>("/import/test-ollama", { method: "POST" });
}

export function scanNow(): Promise<{ directory: unknown; email: unknown }> {
  return apiFetch("/import/scan-now", { method: "POST" });
}

export interface ImportDraftUpdate {
  provider?: string | null;
  amount?: string | null;
  currency?: string | null;
  due_date?: string | null;
  period?: string | null;
  matched_bill_id?: number | null;
}

export function updateImportDraft(
  id: number,
  data: ImportDraftUpdate,
): Promise<ImportDraftOut> {
  return apiFetch<ImportDraftOut>(`/import/drafts/${id}`, {
    method: "PATCH",
    body: JSON.stringify(data),
  });
}

export function confirmImportDraft(
  id: number,
  billId?: number | null,
): Promise<ImportConfirmOut> {
  return apiFetch<ImportConfirmOut>(`/import/drafts/${id}/confirm`, {
    method: "POST",
    body: JSON.stringify({ bill_id: billId ?? null }),
  });
}

export function discardImportDraft(id: number): Promise<void> {
  return apiFetch<void>(`/import/drafts/${id}/discard`, { method: "POST" });
}

export async function uploadBill(file: File): Promise<ImportDraftOut> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`${getApiBaseUrl()}${getApiPrefix()}/import/upload`, {
    method: "POST",
    credentials: "include",
    body: form,
  });
  if (!res.ok) throw await extractApiError(res);
  return res.json();
}

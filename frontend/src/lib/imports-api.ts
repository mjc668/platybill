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

export type LlmProvider = "ollama" | "openai" | "anthropic" | "google" | "opencode";

export const LLM_PROVIDERS: readonly LlmProvider[] = [
  "ollama",
  "openai",
  "anthropic",
  "google",
  "opencode",
];

export interface ImportStatusOut {
  ollama_configured: boolean;
  ollama_base_url: string | null;
  ollama_reachable: boolean;
  ollama_model: string;
  model_available: boolean | null;
  available_models: string[];
  llm_provider: LlmProvider;
  llm_model: string;
  llm_base_url: string | null;
  llm_configured: boolean;
  llm_api_key_configured: boolean;
  import_enabled: boolean;
  import_dir: string;
  import_poll_minutes: number;
  imap_configured: boolean;
  imap_user: string | null;
  imap_host: string | null;
  imap_port: number;
  imap_folder: string;
  imap_tls: boolean;
  imap_poll_minutes: number;
  imap_mark_read: boolean;
  imap_password_configured: boolean;
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

export interface TestImapOut {
  ok: boolean;
  folder: string | null;
  unseen: number | null;
  error: string | null;
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
  ollama_base_url?: string;
  ollama_model?: string;
  llm_provider?: LlmProvider;
  llm_model?: string;
  llm_base_url?: string | null;
  llm_api_key?: string | null;
  llm_timeout_seconds?: number;
  imap_host?: string;
  imap_port?: number;
  imap_user?: string;
  imap_password?: string | null;
  imap_folder?: string;
  imap_tls?: boolean;
  imap_poll_minutes?: number;
  imap_mark_read?: boolean;
  imap_allowed_senders?: string;
}): Promise<ImportStatusOut> {
  return apiFetch<ImportStatusOut>("/import/settings", {
    method: "PATCH",
    body: JSON.stringify(data),
  });
}

export function testOllama(): Promise<TestOllamaOut> {
  return apiFetch<TestOllamaOut>("/import/test-ollama", { method: "POST" });
}

export function fetchImapFolders(): Promise<string[]> {
  return apiFetch<string[]>("/import/imap-folders");
}

export function testImap(): Promise<TestImapOut> {
  return apiFetch<TestImapOut>("/import/test-imap", { method: "POST" });
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

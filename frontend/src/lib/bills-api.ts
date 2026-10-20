import { apiFetch } from "./api";
import type { BankAccount } from "./bank-accounts-api";
import type { Category } from "./categories-api";

export type BillFrequency = "weekly" | "monthly" | "annual" | "one_off";

const BILL_FREQUENCIES: readonly BillFrequency[] = ["weekly", "monthly", "annual", "one_off"];

/**
 * Retired frequency strings (`every_2_months`, `quarterly`) may still show up
 * in stale client state or cached payloads; fall back to a known unit so
 * labels never throw.
 */
export function normalizeBillFrequency(value: string | null | undefined): BillFrequency {
  if (value === "every_2_months" || value === "quarterly") return "monthly";
  return BILL_FREQUENCIES.includes(value as BillFrequency)
    ? (value as BillFrequency)
    : "monthly";
}

export interface BillTemplateOut {
  id: number;
  name: string;
  category: Category;
  preferred_account: BankAccount | null;
  frequency: BillFrequency;
  interval_count: number;
  max_occurrences: number | null;
  start_date: string | null;
  amount: string;
  amount_varies: boolean;
  currency: string;
  due_day: number | null;
  due_month: number | null;
  start_period: string | null;
  notes: string | null;
  is_archived: boolean;
  is_paused: boolean;
  created_at: string;
  next_due_date: string | null;
  next_due_amount: string | null;
  next_due_status: "upcoming" | "overdue" | "paid" | null;
}

export interface BillTemplateCreate {
  name: string;
  category_id: number;
  preferred_account_id?: number | null;
  frequency: BillFrequency;
  interval_count?: number;
  max_occurrences?: number | null;
  start_date?: string | null;
  amount: string;
  amount_varies?: boolean;
  currency?: string;
  due_day?: number | null;
  due_month?: number | null;
  notes?: string | null;
  is_paused?: boolean;
}

export type BillTemplateUpdate = Partial<BillTemplateCreate> & {
  recreate_deleted_future?: boolean;
};

export function fetchBills(includeArchived = false): Promise<BillTemplateOut[]> {
  const qs = includeArchived ? "?include_archived=true" : "";
  return apiFetch<BillTemplateOut[]>(`/bills${qs}`);
}

export function createBill(data: BillTemplateCreate): Promise<BillTemplateOut> {
  return apiFetch<BillTemplateOut>("/bills", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export function updateBill(
  id: number,
  data: BillTemplateUpdate,
): Promise<BillTemplateOut> {
  return apiFetch<BillTemplateOut>(`/bills/${id}`, {
    method: "PATCH",
    body: JSON.stringify(data),
  });
}

export function archiveBill(id: number): Promise<void> {
  return apiFetch<void>(`/bills/${id}/archive`, { method: "POST" });
}

export function unarchiveBill(id: number): Promise<void> {
  return apiFetch<void>(`/bills/${id}/unarchive`, { method: "POST" });
}

export function deleteBill(id: number): Promise<void> {
  return apiFetch<void>(`/bills/${id}`, { method: "DELETE" });
}

export function hasDeletedFuture(id: number): Promise<{ has_deleted_future: boolean }> {
  return apiFetch<{ has_deleted_future: boolean }>(`/bills/${id}/has-deleted-future`);
}

export interface GenerateInstancesResponse {
  created: number;
  bill_count: number;
  months: number;
}

export function generateInstances(
  months: number,
  billIds?: number[],
): Promise<GenerateInstancesResponse> {
  return apiFetch<GenerateInstancesResponse>("/bills/generate-instances", {
    method: "POST",
    body: JSON.stringify({ months, bill_ids: billIds ?? null }),
  });
}

import { apiFetch } from "./api";
import type { BankAccount } from "./bank-accounts-api";
import type { BillFrequency } from "./bills-api";
import type { Category } from "./categories-api";
export type { BillFrequency };
export type PaymentStatus = "upcoming" | "overdue" | "paid";

export interface PaymentEvent {
  id: number;
  instance_id: number;
  amount: string;
  paid_on: string;
  note: string | null;
  created_at: string;
}

export interface PaymentInstanceOut {
  id: number;
  bill_id: number;
  period: string;
  due_date: string;
  amount: string;
  amount_estimated: boolean;
  status: PaymentStatus;
  paid_at: string | null;
  paid_amount: string | null;
  notes: string | null;
  bill_name: string;
  currency: string;
  frequency: BillFrequency;
  interval_count: number;
  max_occurrences: number | null;
  start_date: string | null;
  category: Category;
  preferred_account: BankAccount | null;
  payments: PaymentEvent[];
}

export interface PendingConfirmationOut extends PaymentInstanceOut {
  basis_amounts: string[];
}

export function fetchNeedsConfirmation(): Promise<PendingConfirmationOut[]> {
  return apiFetch<PendingConfirmationOut[]>("/bills/payments/needs-confirmation");
}

export function confirmInstanceAmount(
  instanceId: number,
  amount: string,
): Promise<PaymentInstanceOut> {
  return apiFetch<PaymentInstanceOut>(`/bills/payments/${instanceId}/amount`, {
    method: "PATCH",
    body: JSON.stringify({ amount }),
  });
}

export function syncInstances(month: string): Promise<void> {
  return apiFetch<void>(`/bills/sync-instances?month=${encodeURIComponent(month)}`, {
    method: "POST",
  });
}

export function fetchPayments(
  month: string,
  includeOverdue = false,
): Promise<PaymentInstanceOut[]> {
  const query = `/bills/payments?month=${encodeURIComponent(month)}${
    includeOverdue ? "&include_overdue=true" : ""
  }`;
  return apiFetch<PaymentInstanceOut[]>(query);
}

export function fetchDueSoon(windowDays = 30): Promise<PaymentInstanceOut[]> {
  return apiFetch<PaymentInstanceOut[]>(`/bills/payments?window_days=${windowDays}`);
}

export function markPaid(
  instanceId: number,
  paidAmount: string | null,
  notes?: string,
): Promise<PaymentInstanceOut> {
  const amount = paidAmount ? parseFloat(paidAmount) : null;
  return apiFetch<PaymentInstanceOut>(`/bills/payments/${instanceId}/pay`, {
    method: "POST",
    body: JSON.stringify({ paid_amount: amount, notes: notes ?? null }),
  });
}

export function addPayment(
  instanceId: number,
  amount: number,
  paidOn: string | null,
  note?: string,
): Promise<PaymentInstanceOut> {
  return apiFetch<PaymentInstanceOut>(`/bills/payments/${instanceId}/payments`, {
    method: "POST",
    body: JSON.stringify({ amount: amount.toFixed(2), paid_on: paidOn, note: note ?? null }),
  });
}

export function deletePaymentEvent(
  instanceId: number,
  paymentId: number,
): Promise<PaymentInstanceOut> {
  return apiFetch<PaymentInstanceOut>(
    `/bills/payments/${instanceId}/payments/${paymentId}`,
    { method: "DELETE" },
  );
}

export function deletePayment(instanceId: number, deleteFuture = false): Promise<void> {
  const url = `/bills/payments/${instanceId}${deleteFuture ? "?delete_future=true" : ""}`;
  return apiFetch<void>(url, { method: "DELETE" });
}

export function revertPay(instanceId: number): Promise<PaymentInstanceOut> {
  return apiFetch<PaymentInstanceOut>(`/bills/payments/${instanceId}/unpay`, {
    method: "POST",
  });
}

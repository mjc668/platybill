import { apiFetch } from "./api";

/** Shape returned by every /bank-accounts endpoint. */
export interface BankAccount {
  id: number;
  name: string;
  iban: string | null;
  note: string | null;
  is_archived: boolean;
}

export function fetchBankAccounts(includeArchived = false): Promise<BankAccount[]> {
  const qs = includeArchived ? "?include_archived=true" : "";
  return apiFetch<BankAccount[]>(`/bank-accounts${qs}`);
}

export function createBankAccount(data: {
  name: string;
  iban?: string | null;
  note?: string | null;
}): Promise<BankAccount> {
  return apiFetch<BankAccount>("/bank-accounts", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export function updateBankAccount(
  id: number,
  data: { name?: string; iban?: string | null; note?: string | null; is_archived?: boolean },
): Promise<BankAccount> {
  return apiFetch<BankAccount>(`/bank-accounts/${id}`, {
    method: "PATCH",
    body: JSON.stringify(data),
  });
}

/** Resolves with 204 when unused; rejects with the server's 400 message when in use. */
export function deleteBankAccount(id: number): Promise<void> {
  return apiFetch<void>(`/bank-accounts/${id}`, { method: "DELETE" });
}

/** Short display label: name plus masked IBAN tail when present. */
export function bankAccountLabel(account: BankAccount): string {
  if (!account.iban) return account.name;
  const tail = account.iban.replace(/\s+/g, "").slice(-4);
  return tail ? `${account.name} ····${tail}` : account.name;
}

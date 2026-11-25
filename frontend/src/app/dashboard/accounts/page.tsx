"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { fetchBankAccounts, type BankAccount } from "@/lib/bank-accounts-api";
import AccountListPanel from "@/components/accounts/AccountListPanel";
import RequirementsPanel from "@/components/accounts/RequirementsPanel";

export default function AccountsPage() {
  const t = useTranslations("AccountsPage");
  const [accounts, setAccounts] = useState<BankAccount[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [refreshToken, setRefreshToken] = useState<number>(0);

  useEffect(() => {
    let cancelled = false;
    fetchBankAccounts(true)
      .then((data) => {
        if (!cancelled) {
          setAccounts(data);
          setLoading(false);
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setLoadError(err instanceof Error ? err.message : t("list.loadError"));
          setLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [t]);

  function handleAccountsChange(next: BankAccount[]) {
    setAccounts(next);
    setRefreshToken((n) => n + 1);
  }

  return (
    <div className="mx-auto max-w-4xl px-4 py-6">
      <div className="mb-6">
        <h1 className="text-2xl font-bold tracking-tight text-slate-900 dark:text-slate-100">
          {t("title")}
        </h1>
        <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
          {t("subtitle")}
        </p>
      </div>

      <div className="flex flex-col gap-6">
        <RequirementsPanel accounts={accounts} refreshToken={refreshToken} />
        <AccountListPanel
          accounts={accounts}
          loading={loading}
          loadError={loadError}
          onAccountsChange={handleAccountsChange}
        />
      </div>
    </div>
  );
}

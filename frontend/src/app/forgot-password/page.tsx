"use client";

import { useState, FormEvent } from "react";
import Link from "next/link";
import Image from "next/image";
import { useTranslations } from "next-intl";
import { apiFetch } from "@/lib/api";
import { Input } from "@/components/ui/Input";
import { Button } from "@/components/ui/Button";

export default function ForgotPasswordPage() {
  const t = useTranslations("Auth");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sent, setSent] = useState(false);

  async function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);
    setLoading(true);

    const email = (new FormData(e.currentTarget).get("email") as string) ?? "";

    try {
      await apiFetch("/auth/forgot-password", {
        method: "POST",
        body: JSON.stringify({ email }),
      });
      setSent(true);
    } catch {
      setError(t("forgotPasswordFailed"));
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="flex min-h-screen items-center justify-center bg-slate-50 dark:bg-slate-900 px-4">
      <div className="w-full max-w-sm">
        <div className="mb-8 flex flex-col items-center gap-2">
          <Image
            src="/platybill-logo-light.png"
            alt="Platybill"
            width={104}
            height={104}
            className="rounded-2xl shadow-md dark:hidden"
            priority
          />
          <Image src="/platybill-logo.png" alt="Platybill" width={104} height={104} className="hidden rounded-2xl shadow-md dark:block" priority />
          <h1 className="text-2xl tracking-tight">
            <span className="font-normal text-slate-800 dark:text-slate-100">Platy</span>
            <span className="font-bold text-blue-600 dark:text-blue-400">bill</span>
            <span className="inline-block w-2 h-2 rounded-full bg-[#dfa90c] ml-1 align-baseline" />
          </h1>
          <p className="text-sm text-slate-500 dark:text-slate-400">
            {t("forgotPasswordTitle")}
          </p>
        </div>

        <div className="rounded-2xl border border-slate-200 bg-white p-8 shadow-sm dark:border-slate-700 dark:bg-slate-800">
          {sent ? (
            <p className="text-center text-sm text-slate-600 dark:text-slate-300">
              {t("resetLinkSent")}
            </p>
          ) : (
            <form onSubmit={handleSubmit} className="flex flex-col gap-4">
              <p className="text-sm text-slate-500 dark:text-slate-400">
                {t("forgotPasswordSubtitle")}
              </p>

              <div className="flex flex-col gap-1.5">
                <label
                  htmlFor="email"
                  className="text-sm font-medium text-slate-700 dark:text-slate-300"
                >
                  {t("emailLabel")}
                </label>
                <Input
                  id="email"
                  name="email"
                  type="email"
                  required
                  autoComplete="email"
                />
              </div>

              {error && (
                <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-800 dark:bg-red-900/20 dark:text-red-400">
                  {error}
                </div>
              )}

              <Button type="submit" loading={loading} className="mt-1 w-full py-2.5">
                {loading ? t("sendingResetLink") : t("sendResetLink")}
              </Button>
            </form>
          )}
        </div>

        <p className="mt-5 text-center text-sm text-slate-500 dark:text-slate-400">
          <Link
            href="/login"
            className="font-medium text-blue-700 hover:text-blue-800 dark:text-blue-500"
          >
            {t("signIn")}
          </Link>
        </p>
      </div>
    </main>
  );
}

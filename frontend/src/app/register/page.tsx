"use client";

import { useState, FormEvent } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import Image from "next/image";
import { useTranslations } from "next-intl";
import { apiFetch } from "@/lib/api";
import { useAuth } from "@/context/auth-context";
import { Input } from "@/components/ui/Input";
import { Button } from "@/components/ui/Button";

export default function RegisterPage() {
  const router = useRouter();
  const { login } = useAuth();
  const t = useTranslations("Auth");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);
    setLoading(true);

    const form = new FormData(e.currentTarget);
    const email = form.get("email") as string;
    const password = form.get("password") as string;

    if (password.length < 8) {
      setError(t("passwordTooShort"));
      setLoading(false);
      return;
    }

    try {
      await apiFetch<{ message: string }>("/auth/register", {
        method: "POST",
        body: JSON.stringify({ email, password }),
      });
      login();
      router.push("/dashboard");
    } catch (err) {
      setError(err instanceof Error ? err.message : t("registrationFailed"));
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="flex min-h-screen items-center justify-center bg-slate-50 dark:bg-slate-900 px-4">
      <div className="w-full max-w-sm">
        {/* Logo */}
        <div className="mb-8 flex flex-col items-center gap-2">
          <Image src="/platybill-logo-light.png" alt="Platybill" width={104} height={104} className="rounded-2xl shadow-md dark:hidden" priority />
          <Image src="/platybill-logo.png" alt="Platybill" width={104} height={104} className="hidden rounded-2xl shadow-md dark:block" priority />
          <h1 className="text-2xl tracking-tight">
            <span className="font-normal text-slate-800 dark:text-slate-100">Platy</span>
            <span className="font-bold text-blue-600 dark:text-blue-400">bill</span>
            <span className="inline-block w-2 h-2 rounded-full bg-[#dfa90c] ml-1 align-baseline" />
          </h1>
          <p className="text-sm text-slate-500 dark:text-slate-400">
            {t("registerSubtitle")}
          </p>
        </div>

        <div className="rounded-2xl border border-slate-200 bg-white p-8 shadow-sm dark:bg-slate-800 dark:border-slate-700">
          <form onSubmit={handleSubmit} className="flex flex-col gap-4">
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

            <div className="flex flex-col gap-1.5">
              <label
                htmlFor="password"
                className="text-sm font-medium text-slate-700 dark:text-slate-300"
              >
                {t("passwordLabel")}
              </label>
              <Input
                id="password"
                name="password"
                type="password"
                required
                autoComplete="new-password"
              />
              <p className="text-xs text-slate-400 dark:text-slate-500">
                {t("passwordHint")}
              </p>
            </div>

            {error && (
              <div className="rounded-xl bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700 dark:bg-red-900/20 dark:border-red-800 dark:text-red-400">
                {error}
              </div>
            )}

            <Button type="submit" loading={loading} className="mt-1 w-full py-2.5">
              {loading ? t("creatingAccount") : t("createAccount")}
            </Button>
          </form>
        </div>

        <p className="mt-5 text-center text-sm text-slate-500 dark:text-slate-400">
          {t("alreadyHaveAccount")}{" "}
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

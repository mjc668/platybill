"use client";

import { useState, FormEvent, Suspense } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import Image from "next/image";
import { useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { apiFetch } from "@/lib/api";
import { Input } from "@/components/ui/Input";
import { Button } from "@/components/ui/Button";

// Reset links now carry the token in the URL fragment (`#token=...`) so it is
// never sent to the server in request logs or Referer headers. The query
// parameter is still accepted so links emailed before this change keep working.
function readResetToken(queryToken: string | null): string {
  if (typeof window !== "undefined") {
    const hash = window.location.hash.replace(/^#/, "");
    const fromHash = new URLSearchParams(hash).get("token");
    if (fromHash) return fromHash;
  }
  return queryToken ?? "";
}

function ResetPasswordForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const t = useTranslations("Auth");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tokenInvalid, setTokenInvalid] = useState(false);

  async function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);

    const form = new FormData(e.currentTarget);
    const newPassword = form.get("new_password") as string;
    const confirmPassword = form.get("confirm_password") as string;

    if (newPassword !== confirmPassword) {
      setError(t("passwordsDoNotMatch"));
      return;
    }

    setLoading(true);
    try {
      await apiFetch("/auth/reset-password", {
        method: "POST",
        body: JSON.stringify({
          token: readResetToken(searchParams.get("token")),
          new_password: newPassword,
        }),
      });
      router.push("/login");
    } catch {
      setTokenInvalid(true);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-8 shadow-sm dark:border-slate-700 dark:bg-slate-800">
      {tokenInvalid ? (
        <div className="flex flex-col items-center gap-4 text-center">
          <p className="text-sm text-red-700 dark:text-red-400">
            {t("invalidOrExpiredToken")}
          </p>
          <Link
            href="/forgot-password"
            className="text-sm font-medium text-blue-700 hover:text-blue-800 dark:text-blue-500"
          >
            {t("requestNewLink")}
          </Link>
        </div>
      ) : (
        <form onSubmit={handleSubmit} className="flex flex-col gap-4">
          <p className="text-sm text-slate-500 dark:text-slate-400">
            {t("resetPasswordSubtitle")}
          </p>

          <div className="flex flex-col gap-1.5">
            <label
              htmlFor="new_password"
              className="text-sm font-medium text-slate-700 dark:text-slate-300"
            >
              {t("newPasswordLabel")}
            </label>
            <Input
              id="new_password"
              name="new_password"
              type="password"
              required
              autoComplete="new-password"
            />
          </div>

          <div className="flex flex-col gap-1.5">
            <label
              htmlFor="confirm_password"
              className="text-sm font-medium text-slate-700 dark:text-slate-300"
            >
              {t("confirmPasswordLabel")}
            </label>
            <Input
              id="confirm_password"
              name="confirm_password"
              type="password"
              required
              autoComplete="new-password"
            />
          </div>

          {error && (
            <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-800 dark:bg-red-900/20 dark:text-red-400">
              {error}
            </div>
          )}

          <Button type="submit" loading={loading} className="mt-1 w-full py-2.5">
            {loading ? t("settingPassword") : t("setPassword")}
          </Button>
        </form>
      )}
    </div>
  );
}

export default function ResetPasswordPage() {
  const t = useTranslations("Auth");

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
            {t("resetPasswordTitle")}
          </p>
        </div>

        <Suspense>
          <ResetPasswordForm />
        </Suspense>

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

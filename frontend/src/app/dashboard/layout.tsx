"use client";

import { useEffect, useState, useRef } from "react";
import Link from "next/link";
import Image from "next/image";
import { usePathname, useRouter } from "next/navigation";
import { Archive, Receipt, CreditCard, LayoutDashboard, LogOut, Settings } from "lucide-react";
import { useTranslations } from "next-intl";
import { useAuth } from "@/context/auth-context";
import { fetchMe } from "@/lib/user-api";
import ThemeToggle from "@/components/ThemeToggle";
import BottomNav from "@/components/navigation/BottomNav";

const NAV_ITEMS = [
  { href: "/dashboard", labelKey: "dashboard" as const, icon: LayoutDashboard, exact: true },
  { href: "/dashboard/payments", labelKey: "payments" as const, icon: CreditCard, exact: false },
  { href: "/dashboard/bills", labelKey: "bills" as const, icon: Receipt, exact: true },
  { href: "/dashboard/bills/archived", labelKey: "archived" as const, icon: Archive, exact: false },
  { href: "/dashboard/settings", labelKey: "settings" as const, icon: Settings, exact: false },
];

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const { isAuthenticated, isReady, logout } = useAuth();
  const t = useTranslations("DashboardLayout");
  const router = useRouter();
  const pathname = usePathname();
  const [userMenuOpen, setUserMenuOpen] = useState(false);
  const [userEmail, setUserEmail] = useState<string | null>(null);
  const userMenuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    // Wait for the cookie sync before deciding: redirecting during the first
    // render would kick authenticated users out before their state is known.
    if (isReady && !isAuthenticated) router.replace("/login");
  }, [isReady, isAuthenticated, router]);

  useEffect(() => {
    if (isAuthenticated) {
      fetchMe().then((p) => setUserEmail(p.email)).catch(() => {});
    }
  }, [isAuthenticated]);

  // Close user dropdown on outside click
  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (userMenuRef.current && !userMenuRef.current.contains(e.target as Node)) {
        setUserMenuOpen(false);
      }
    }
    if (userMenuOpen) document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [userMenuOpen]);

  if (!isReady || !isAuthenticated) return null;

  const initials = userEmail ? userEmail[0].toUpperCase() : "?";

  return (
    <div className="flex min-h-screen flex-col">
      {/* Top nav */}
      <header className="relative sticky top-0 z-10 border-b border-slate-200 bg-white/80 backdrop-blur dark:border-slate-700 dark:bg-slate-800/80">
        <div className="mx-auto flex max-w-4xl items-center gap-4 px-4 py-3">
          {/* Brand */}
          <Link
            href="/dashboard"
            className="flex items-center gap-2 text-blue-700 transition-opacity hover:opacity-80 dark:text-blue-500"
          >
            <Image src="/platybill-logo-light.png" alt="Platybill" width={32} height={32} className="rounded-xl dark:hidden" />
            <Image src="/platybill-logo.png" alt="Platybill" width={32} height={32} className="hidden rounded-xl dark:block" />
            <span className="text-lg tracking-tight">
              <span className="font-normal">Platy</span><span className="font-bold">bill</span>
            </span>
          </Link>

          {/* Desktop nav links */}
          <nav className="hidden md:flex flex-1 items-center gap-1 ml-4">
            {NAV_ITEMS.map(({ href, labelKey, icon: Icon, exact }) => {
              const active = pathname === href || (!exact && pathname.startsWith(href + "/"));
              return (
                <Link
                  key={href}
                  href={href}
                  className={`flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium transition-all ${
                    active
                      ? "border border-blue-200 bg-blue-50 text-blue-800 shadow-sm dark:border-blue-800 dark:bg-blue-900/30 dark:text-blue-300"
                      : "border border-transparent text-slate-600 hover:border-blue-200 hover:bg-blue-50 hover:text-blue-700 dark:text-slate-400 dark:hover:border-blue-800 dark:hover:bg-blue-900/20 dark:hover:text-blue-300"
                  }`}
                >
                  <Icon size={15} />
                  {t(labelKey)}
                </Link>
              );
            })}
          </nav>

          {/* Right side controls (theme toggle + user avatar dropdown) */}
          <div className="flex items-center gap-1.5 ml-auto">
            <ThemeToggle />

            {/* Avatar + dropdown */}
            <div className="relative" ref={userMenuRef}>
              <button
                onClick={() => setUserMenuOpen((o) => !o)}
                aria-label={t("userMenu")}
                className={`flex h-8 w-8 items-center justify-center rounded-full text-sm font-bold text-white shadow-sm transition-all ${
                  userMenuOpen
                    ? "bg-blue-800 dark:bg-blue-500"
                    : "bg-blue-700 hover:bg-blue-800 dark:bg-blue-600 dark:hover:bg-blue-500"
                }`}
              >
                {initials}
              </button>

              {/* Dropdown */}
              {userMenuOpen && (
                <div className="absolute right-0 top-full mt-2 z-50 w-64 overflow-hidden rounded-xl border border-slate-200 bg-white shadow-xl dark:border-slate-700 dark:bg-slate-800">
                  <div className="border-b border-slate-100 px-4 py-3 dark:border-slate-700">
                    <p className="text-xs font-semibold uppercase tracking-wide text-slate-400 dark:text-slate-500">
                      {t("signedInAs")}
                    </p>
                    <p className="mt-0.5 truncate text-sm font-medium text-slate-800 dark:text-slate-100">
                      {userEmail}
                    </p>
                  </div>
                  <div className="p-2 flex flex-col gap-1">
                    <Link
                      href="/dashboard/bills/archived"
                      onClick={() => setUserMenuOpen(false)}
                      className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-sm font-medium text-slate-600 transition-all hover:bg-slate-50 hover:text-slate-800 dark:text-slate-400 dark:hover:bg-slate-700/50 dark:hover:text-slate-200"
                    >
                      <Archive size={14} />
                      {t("archived")}
                    </Link>
                    <button
                      onClick={() => { setUserMenuOpen(false); logout(); }}
                      className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-sm font-medium text-slate-600 transition-all hover:bg-red-50 hover:text-red-600 dark:text-slate-400 dark:hover:bg-red-900/20 dark:hover:text-red-400"
                    >
                      <LogOut size={14} />
                      {t("logOut")}
                    </button>
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      </header>

      {/* Page content */}
      <main className="flex-1 pb-20 pb-safe md:pb-6">{children}</main>

      {/* Mobile bottom navigation bar */}
      <BottomNav />
    </div>
  );
}

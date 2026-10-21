"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { CreditCard, LayoutDashboard, Receipt, Settings } from "lucide-react";
import { useTranslations } from "next-intl";

interface BottomNavItem {
  href: string;
  labelKey: "dashboard" | "payments" | "bills" | "settings";
  icon: typeof LayoutDashboard;
  exact: boolean;
}

const ITEMS: BottomNavItem[] = [
  { href: "/dashboard", labelKey: "dashboard", icon: LayoutDashboard, exact: true },
  { href: "/dashboard/payments", labelKey: "payments", icon: CreditCard, exact: false },
  { href: "/dashboard/bills", labelKey: "bills", icon: Receipt, exact: true },
  { href: "/dashboard/settings", labelKey: "settings", icon: Settings, exact: false },
];

export default function BottomNav() {
  const pathname = usePathname();
  const t = useTranslations("DashboardLayout");

  return (
    <nav
      data-testid="mobile-bottom-nav"
      aria-label="Mobile navigation"
      className="md:hidden fixed bottom-0 inset-x-0 z-40 border-t border-slate-200/80 bg-white/95 backdrop-blur-md dark:border-slate-800 dark:bg-slate-900/95 pb-safe"
    >
      <div className="grid grid-cols-4 h-14">
        {ITEMS.map(({ href, labelKey, icon: Icon, exact }) => {
          const active = pathname === href || (!exact && pathname.startsWith(href + "/"));
          return (
            <Link
              key={href}
              href={href}
              aria-current={active ? "page" : undefined}
              className={`flex flex-col items-center justify-center gap-1 transition-colors ${
                active
                  ? "text-blue-600 dark:text-blue-400 font-semibold"
                  : "text-slate-500 hover:text-slate-800 dark:text-slate-400 dark:hover:text-slate-200"
              }`}
            >
              <div
                className={`flex h-7 w-12 items-center justify-center rounded-full transition-colors ${
                  active
                    ? "bg-blue-100/70 dark:bg-blue-900/40"
                    : "bg-transparent"
                }`}
              >
                <Icon size={19} strokeWidth={active ? 2.3 : 1.8} />
              </div>
              <span className="text-[10px] leading-tight tracking-tight">
                {t(labelKey)}
              </span>
            </Link>
          );
        })}
      </div>
    </nav>
  );
}

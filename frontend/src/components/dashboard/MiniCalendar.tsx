"use client";

import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import type { PaymentInstanceOut } from "@/lib/payments-api";
import { STATUS_STYLES } from "@/components/payments/PaymentRow";

interface Props {
  /** Displayed month in YYYY-MM form. */
  month: string;
  instances: PaymentInstanceOut[];
  /** Today as YYYY-MM-DD, used for the highlight. */
  todayStr: string;
}

const MAX_DOTS = 3;

function firstDayOffset(year: number, monthIndex: number): number {
  const jsDay = new Date(year, monthIndex, 1).getDay(); // 0 = Sunday
  return jsDay === 0 ? 6 : jsDay - 1;
}

function dateKey(year: number, monthIndex: number, day: number): string {
  return `${year}-${String(monthIndex + 1).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
}

export default function MiniCalendar({ month, instances, todayStr }: Props) {
  const t = useTranslations("Dashboard");
  const locale = useLocale();

  const [yearStr, monthStr] = month.split("-");
  const year = parseInt(yearStr, 10);
  const monthIndex = parseInt(monthStr, 10) - 1;
  const totalDays = new Date(year, monthIndex + 1, 0).getDate();
  const offset = firstDayOffset(year, monthIndex);

  const byDay = new Map<string, PaymentInstanceOut[]>();
  for (const inst of instances) {
    const list = byDay.get(inst.due_date) ?? [];
    list.push(inst);
    byDay.set(inst.due_date, list);
  }
  for (const list of byDay.values()) {
    list.sort((a, b) => a.bill_name.localeCompare(b.bill_name));
  }

  const weekdayHeaders = Array.from({ length: 7 }, (_, i) =>
    new Intl.DateTimeFormat(locale, { weekday: "short" }).format(
      new Date(2024, 0, 1 + i), // Jan 1 2024 = Monday
    ),
  );

  const monthLabel = new Intl.DateTimeFormat(locale, {
    month: "long",
    year: "numeric",
  }).format(new Date(`${month}-01T00:00:00`));
  const capitalizedMonthLabel =
    monthLabel.charAt(0).toUpperCase() + monthLabel.slice(1);

  return (
    <Link
      href={`/dashboard/payments?month=${month}`}
      data-testid="dashboard-mini-calendar"
      aria-label={t("miniCalendarLinkLabel", { month: capitalizedMonthLabel })}
      className="block rounded-xl border border-slate-200 bg-white p-3 shadow-sm transition-colors hover:border-blue-300 hover:bg-blue-50/50 dark:border-slate-700 dark:bg-slate-800 dark:hover:border-blue-700 dark:hover:bg-blue-900/10"
    >
      <div className="mb-2">
        <span className="text-sm font-semibold text-slate-700 dark:text-slate-200">
          {capitalizedMonthLabel}
        </span>
      </div>

      <div className="grid grid-cols-7 gap-1">
        {weekdayHeaders.map((wd, i) => (
          <div
            key={`weekday-${i}`}
            className="flex h-5 items-center justify-center text-[10px] font-medium capitalize text-slate-400 dark:text-slate-500"
          >
            {wd.slice(0, 2)}
          </div>
        ))}

        {Array.from({ length: offset }).map((_, i) => (
          <div key={`gap-${i}`} />
        ))}

        {Array.from({ length: totalDays }, (_, i) => i + 1).map((day) => {
          const key = dateKey(year, monthIndex, day);
          const dayInstances = byDay.get(key) ?? [];
          const visible = dayInstances.slice(0, MAX_DOTS);
          const extra = dayInstances.length - visible.length;
          const isToday = key === todayStr;
          return (
            <div
              key={key}
              data-testid={`mini-calendar-day-${key}`}
              className={`flex min-h-[38px] flex-col items-center gap-0.5 rounded-lg px-0.5 py-1 ${
                isToday ? "bg-blue-50 dark:bg-blue-900/20" : ""
              }`}
            >
              <span
                className={`flex h-4 min-w-4 items-center justify-center rounded-full px-1 text-[10px] font-semibold tabular-nums ${
                  isToday
                    ? "bg-blue-700 text-white dark:bg-blue-600"
                    : "text-slate-600 dark:text-slate-300"
                }`}
              >
                {day}
              </span>
              {(visible.length > 0 || extra > 0) && (
                <span className="flex items-center gap-0.5">
                  {visible.map((inst) => (
                    <span
                      key={inst.id}
                      className={`h-1.5 w-1.5 rounded-full bg-current ${
                        inst.amount_estimated && inst.status !== "paid"
                          ? "text-amber-500 dark:text-amber-400"
                          : (STATUS_STYLES[inst.status] ?? "")
                      }`}
                    />
                  ))}
                  {extra > 0 && (
                    <span className="text-[9px] font-semibold leading-none text-slate-400 dark:text-slate-500">
                      +{extra}
                    </span>
                  )}
                </span>
              )}
            </div>
          );
        })}

        {Array.from({ length: (7 - ((offset + totalDays) % 7)) % 7 }).map(
          (_, i) => (
            <div key={`tail-${i}`} />
          ),
        )}
      </div>
    </Link>
  );
}

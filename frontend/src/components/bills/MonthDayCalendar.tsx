"use client";

import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { CalendarDays, ChevronLeft, ChevronRight } from "lucide-react";
import { useLocale } from "next-intl";

interface Props {
  month: number; // 1–12
  day: number;
  onChange: (month: number, day: number) => void;
}

// 2024 is a leap year — Feb has 29 days, all other months correct
const REF_YEAR = 2024;

function daysInMonth(month: number): number {
  return new Date(REF_YEAR, month, 0).getDate();
}

// Monday-first offset (0=Mon … 6=Sun)
function firstDayOffset(month: number): number {
  const jsDay = new Date(REF_YEAR, month - 1, 1).getDay(); // 0=Sun
  return jsDay === 0 ? 6 : jsDay - 1;
}

export default function MonthDayCalendar({ month, day, onChange }: Props) {
  const locale = useLocale();
  const [open, setOpen] = useState(false);
  const [viewMonth, setViewMonth] = useState(month);
  const containerRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const [popupStyle, setPopupStyle] = useState<React.CSSProperties>({});

  useEffect(() => {
    if (!open) return;
    function onMouseDown(e: MouseEvent) {
      if (
        containerRef.current && !containerRef.current.contains(e.target as Node) &&
        triggerRef.current && !triggerRef.current.contains(e.target as Node)
      )
        setOpen(false);
    }
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onMouseDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onMouseDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  function prevMonth() {
    setViewMonth((m) => (m === 1 ? 12 : m - 1));
  }
  function nextMonth() {
    setViewMonth((m) => (m === 12 ? 1 : m + 1));
  }

  function handleSelectDay(d: number) {
    onChange(viewMonth, d);
    setOpen(false);
  }

  const fmt = (m: number) =>
    new Intl.DateTimeFormat(locale, { month: "long" }).format(
      new Date(REF_YEAR, m - 1, 1),
    );

  const triggerLabel = new Intl.DateTimeFormat(locale, {
    day: "numeric",
    month: "long",
  }).format(new Date(REF_YEAR, month - 1, day));

  // Short weekday headers starting Monday
  const weekdayHeaders = Array.from({ length: 7 }, (_, i) =>
    new Intl.DateTimeFormat(locale, { weekday: "short" })
      .format(new Date(REF_YEAR, 0, 6 + i)) // Jan 6 2024 = Monday
      .slice(0, 2),
  );

  const maxDay = daysInMonth(viewMonth);
  const offset = firstDayOffset(viewMonth);

  function handleOpen() {
    if (!triggerRef.current) return;
    const rect = triggerRef.current.getBoundingClientRect();
    const popupWidth = Math.min(288, window.innerWidth - 16);
    const popupHeight = 320;
    const spaceBelow = window.innerHeight - rect.bottom;
    const openUpward = spaceBelow < popupHeight + 8;
    const left = Math.max(8, Math.min(rect.left, window.innerWidth - popupWidth - 8));
    setPopupStyle(
      openUpward
        ? { position: "fixed", bottom: window.innerHeight - rect.top + 6, left, width: popupWidth, zIndex: 9999 }
        : { position: "fixed", top: rect.bottom + 6, left, width: popupWidth, zIndex: 9999 }
    );
    setViewMonth(month);
    setOpen((o) => !o);
  }

  return (
    <div className="relative">
      <button
        ref={triggerRef}
        type="button"
        onClick={handleOpen}
        aria-haspopup="true"
        aria-expanded={open}
        className="flex w-full items-center gap-2 rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm text-slate-800 outline-none transition-colors hover:border-blue-500 focus:border-blue-500 focus:ring-2 focus:ring-blue-100 dark:bg-slate-800 dark:border-slate-600 dark:text-slate-100 dark:hover:border-blue-600 dark:focus:border-blue-600 dark:focus:ring-blue-900/40"
      >
        <CalendarDays size={15} className="shrink-0 text-slate-400 dark:text-slate-500" />
        <span className="capitalize">{triggerLabel}</span>
      </button>

      {open && createPortal(
        <div ref={containerRef} style={popupStyle} className="rounded-xl border border-slate-200 bg-white p-3 shadow-lg dark:border-slate-600 dark:bg-slate-800">
          {/* Month navigation */}
          <div className="mb-2 flex items-center justify-between">
            <button
              type="button"
              onClick={prevMonth}
              className="rounded-lg p-1 text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors"
            >
              <ChevronLeft size={16} />
            </button>
            <span className="text-sm font-semibold text-slate-700 dark:text-slate-200 capitalize">
              {fmt(viewMonth)}
            </span>
            <button
              type="button"
              onClick={nextMonth}
              className="rounded-lg p-1 text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors"
            >
              <ChevronRight size={16} />
            </button>
          </div>

          {/* Weekday headers */}
          <div className="mb-1 grid grid-cols-7">
            {weekdayHeaders.map((wd, i) => (
              <div
                key={i}
                className="flex h-7 items-center justify-center text-xs font-medium text-slate-400 dark:text-slate-500 capitalize"
              >
                {wd}
              </div>
            ))}
          </div>

          {/* Day grid */}
          <div className="grid grid-cols-7 gap-0.5">
            {Array.from({ length: offset }).map((_, i) => (
              <div key={`gap-${i}`} />
            ))}
            {Array.from({ length: maxDay }, (_, i) => i + 1).map((d) => {
              const selected = d === day && viewMonth === month;
              return (
                <button
                  key={d}
                  type="button"
                  onClick={() => handleSelectDay(d)}
                  className={`mx-auto flex h-8 w-8 items-center justify-center rounded-lg text-sm transition-colors ${
                    selected
                      ? "bg-blue-700 font-semibold text-white"
                      : "text-slate-700 hover:bg-blue-50 hover:text-blue-800 dark:text-slate-300 dark:hover:bg-blue-900/30 dark:hover:text-blue-300"
                  }`}
                >
                  {d}
                </button>
              );
            })}
          </div>
        </div>,
        document.body
      )}
    </div>
  );
}

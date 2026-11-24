"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { fetchPayments } from "@/lib/payments-api";

const notificationsSupported =
  typeof window !== "undefined" && "Notification" in window;

const BROWSER_NOTIF_KEY = "browser_notif_enabled";

function getPermission(): NotificationPermission {
  if (!notificationsSupported) return "default";
  return Notification.permission;
}

function getInitialEnabled(): boolean {
  if (!notificationsSupported) return false;
  if (Notification.permission !== "granted") return false;
  return localStorage.getItem(BROWSER_NOTIF_KEY) === "1";
}

export function useNotifications(): {
  permission: NotificationPermission;
  isEnabled: boolean;
  requestPermission: () => Promise<void>;
  setEnabled: (v: boolean) => void;
  notifyDueToday: () => Promise<void>;
} {
  const [permission, setPermission] = useState<NotificationPermission>(getPermission);
  const [isEnabled, setIsEnabledState] = useState(getInitialEnabled);
  // Requires a next-intl NextIntlClientProvider ancestor — notification title is i18n'd here intentionally.
  const t = useTranslations("NotificationToggle");

  // Track OS-level permission changes via the Permissions API.
  // navigator.permissions reflects macOS-level blocks even when Notification.permission still reads "granted".
  useEffect(() => {
    if (!notificationsSupported || !("permissions" in navigator)) return;
    let status: PermissionStatus;
    navigator.permissions
      .query({ name: "notifications" as PermissionName })
      .then((s) => {
        status = s;
        setPermission(s.state as NotificationPermission);
        s.onchange = () => setPermission(s.state as NotificationPermission);
      })
      .catch(() => {});
    return () => {
      if (status) status.onchange = null;
    };
  }, []);

  function setEnabled(v: boolean) {
    localStorage.setItem(BROWSER_NOTIF_KEY, v ? "1" : "0");
    setIsEnabledState(v);
  }

  async function requestPermission() {
    if (!notificationsSupported) return;
    const result = await Notification.requestPermission();
    setPermission(result);
    if (result === "granted") {
      setEnabled(true);
    }
  }

  async function notifyDueToday() {
    if (localStorage.getItem(BROWSER_NOTIF_KEY) !== "1") return;
    if (!notificationsSupported || Notification.permission !== "granted") return;
    if (!("serviceWorker" in navigator)) return;

    const today = new Date().toLocaleDateString("en-CA"); // YYYY-MM-DD in local timezone
    const month = today.slice(0, 7); // YYYY-MM

    let payments;
    try {
      // Keep browser due-today alerts consistent with backend reminders:
      // only notify for confirmed amounts, not unconfirmed estimates.
      payments = await fetchPayments(month, false, false);
    } catch (err) {
      console.error("[useNotifications] fetchPayments failed:", err);
      return;
    }

    const due = payments.filter(
      (p) => p.due_date === today && p.status !== "paid",
    );

    let reg: ServiceWorkerRegistration;
    try {
      reg = await navigator.serviceWorker.ready;
    } catch {
      return;
    }

    // Prune dedup keys from past dates to prevent localStorage growth.
    for (const k of Object.keys(localStorage)) {
      if (k.startsWith("notified_") && !k.includes(`notified_${today}_`)) {
        localStorage.removeItem(k);
      }
    }

    for (const p of due) {
      const key = `notified_${p.due_date}_${p.id}`;
      if (localStorage.getItem(key)) continue;
      const formattedDate = new Date(`${p.due_date}T12:00:00`).toLocaleDateString();
      await reg.showNotification(t("paymentIncoming"), {
        body: `${p.bill_name} — ${formattedDate}`,
        requireInteraction: true,
      });
      try {
        localStorage.setItem(key, "1");
      } catch {
        // Storage quota exceeded — notification still shown, dedup skipped.
      }
    }
  }

  return { permission, isEnabled, requestPermission, setEnabled, notifyDueToday };
}

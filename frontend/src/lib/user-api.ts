import { apiFetch } from "@/lib/api";

export interface UserProfile {
  email: string;
  language_preference: "en" | "pl" | "de" | null;
  timezone: string | null;
  default_currency: string | null;
  email_reminders_enabled: boolean;
  notify_2_days_before: boolean;
  notify_1_day_before: boolean;
  notify_on_day: boolean;
  notify_1_day_after: boolean;
  reminder_send_minute: number;
  monthly_summary_enabled: boolean;
  upcoming_digest_enabled: boolean;
  upcoming_digest_weekday: number;
  upcoming_digest_minute: number;
  upcoming_digest_days: number;
}

export function fetchMe(): Promise<UserProfile> {
  return apiFetch<UserProfile>("/auth/me");
}

export function updateMe(
  data: Partial<
    Pick<
      UserProfile,
      | "language_preference"
      | "timezone"
      | "default_currency"
      | "email_reminders_enabled"
      | "notify_2_days_before"
      | "notify_1_day_before"
      | "notify_on_day"
      | "notify_1_day_after"
      | "reminder_send_minute"
      | "monthly_summary_enabled"
      | "upcoming_digest_enabled"
      | "upcoming_digest_weekday"
      | "upcoming_digest_minute"
      | "upcoming_digest_days"
    >
  >,
): Promise<UserProfile> {
  return apiFetch<UserProfile>("/auth/me", {
    method: "PATCH",
    body: JSON.stringify(data),
  });
}

export function changePassword(
  currentPassword: string,
  newPassword: string,
): Promise<void> {
  return apiFetch<void>("/auth/change-password", {
    method: "PATCH",
    body: JSON.stringify({
      current_password: currentPassword,
      new_password: newPassword,
    }),
  });
}

export function sendNotificationNow(): Promise<{ sent: number }> {
  return apiFetch<{ sent: number }>("/auth/send-notification-now", {
    method: "POST",
  });
}

export function sendMonthlySummaryNow(): Promise<{ sent: boolean }> {
  return apiFetch<{ sent: boolean }>("/auth/send-monthly-summary-now", {
    method: "POST",
  });
}

export interface NotificationStatus {
  smtp_configured: boolean;
  apprise_configured: boolean;
}

export interface TestNotificationResult {
  ok: boolean;
  channel: "apprise" | "email" | null;
  detail: string | null;
}

export function fetchNotificationStatus(): Promise<NotificationStatus> {
  return apiFetch<NotificationStatus>("/auth/notification-status");
}

export function sendTestNotification(): Promise<TestNotificationResult> {
  return apiFetch<TestNotificationResult>("/auth/send-test-notification", {
    method: "POST",
  });
}

export function fetchServerTime(): Promise<{ server_time: string }> {
  return apiFetch<{ server_time: string }>("/auth/server-time");
}

export function changeEmail(
  newEmail: string,
  currentPassword: string,
): Promise<UserProfile> {
  return apiFetch<UserProfile>("/auth/change-email", {
    method: "PATCH",
    body: JSON.stringify({
      new_email: newEmail,
      current_password: currentPassword,
    }),
  });
}

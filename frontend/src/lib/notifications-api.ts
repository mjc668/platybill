import { apiFetch } from "./api";

export interface NotificationSettings {
  smtp_configured: boolean;
  smtp_host: string | null;
  smtp_port: number;
  smtp_user: string | null;
  smtp_password_configured: boolean;
  smtp_use_tls: boolean;
  smtp_from: string | null;
  apprise_configured: boolean;
  apprise_base_url: string | null;
  apprise_urls_configured: boolean;
  apprise_key_configured: boolean;
  apprise_timeout_seconds: number;
}

export function fetchNotificationSettings(): Promise<NotificationSettings> {
  return apiFetch<NotificationSettings>("/notifications/settings");
}

export function updateNotificationSettings(data: {
  smtp?: {
    host?: string | null;
    port?: number;
    user?: string | null;
    password?: string | null;
    use_tls?: boolean;
    from_addr?: string | null;
  };
  apprise?: {
    base_url?: string | null;
    urls?: string | null;
    key?: string | null;
    timeout_seconds?: number;
  };
}): Promise<NotificationSettings> {
  return apiFetch<NotificationSettings>("/notifications/settings", {
    method: "PATCH",
    body: JSON.stringify(data),
  });
}

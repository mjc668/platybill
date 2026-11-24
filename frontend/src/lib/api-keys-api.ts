import { apiFetch } from "./api";
import type { PermissionScope } from "./scopes";

export interface ApiKeyOut {
  id: number;
  name: string;
  key_prefix: string;
  scopes: PermissionScope[];
  expires_at: string | null;
  last_used_at: string | null;
  created_at: string;
}

export interface ApiKeyCreatedOut extends ApiKeyOut {
  key: string;
}

export function fetchApiKeys(): Promise<ApiKeyOut[]> {
  return apiFetch<ApiKeyOut[]>("/auth/api-keys");
}

export function createApiKey(params: {
  name: string;
  scopes: PermissionScope[];
  expires_in_days?: number | null;
}): Promise<ApiKeyCreatedOut> {
  return apiFetch<ApiKeyCreatedOut>("/auth/api-keys", {
    method: "POST",
    body: JSON.stringify(params),
  });
}

export function deleteApiKey(keyId: number): Promise<void> {
  return apiFetch<void>(`/auth/api-keys/${keyId}`, {
    method: "DELETE",
  });
}

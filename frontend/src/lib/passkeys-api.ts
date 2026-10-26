import {
  startRegistration,
  startAuthentication,
  browserSupportsWebAuthn,
  PublicKeyCredentialCreationOptionsJSON,
  PublicKeyCredentialRequestOptionsJSON,
} from "@simplewebauthn/browser";
import { apiFetch } from "./api";

export interface PasskeyItem {
  id: number;
  name: string;
  created_at: string;
  last_used_at: string | null;
  transports: string[];
}

export interface PasskeyRegistrationOptionsResponse {
  options: PublicKeyCredentialCreationOptionsJSON;
}

export interface PasskeyLoginOptionsResponse {
  options: PublicKeyCredentialRequestOptionsJSON;
}

export { browserSupportsWebAuthn };

export async function fetchPasskeys(): Promise<PasskeyItem[]> {
  return apiFetch<PasskeyItem[]>("/auth/passkeys");
}

export async function deletePasskey(passkeyId: number): Promise<void> {
  await apiFetch(`/auth/passkeys/${passkeyId}`, { method: "DELETE" });
}

export async function registerPasskey(name?: string): Promise<PasskeyItem> {
  // 1. Get creation options from backend
  const { options } = await apiFetch<PasskeyRegistrationOptionsResponse>(
    "/auth/passkeys/register/options",
    { method: "POST" },
  );

  // 2. Prompt user via browser/OS WebAuthn dialog
  const registrationResponse = await startRegistration({ optionsJSON: options });

  // 3. Send response back to backend to verify and store
  return apiFetch<PasskeyItem>("/auth/passkeys/register/verify", {
    method: "POST",
    body: JSON.stringify({
      response: registrationResponse,
      name: name?.trim() || undefined,
    }),
  });
}

export async function loginWithPasskey(rememberMe: boolean = false): Promise<void> {
  // 1. Get assertion request options from backend
  const { options } = await apiFetch<PasskeyLoginOptionsResponse>(
    "/auth/passkeys/login/options",
    { method: "POST" },
  );

  // 2. Prompt user for passkey
  const authResponse = await startAuthentication({ optionsJSON: options });

  // 3. Verify on backend; sets HttpOnly access_token and presence cookie
  await apiFetch<{ message: string }>("/auth/passkeys/login/verify", {
    method: "POST",
    body: JSON.stringify({
      response: authResponse,
      remember_me: rememberMe,
    }),
  });
}

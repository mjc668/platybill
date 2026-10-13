import * as fs from 'fs';
import type { Page } from '@playwright/test';

export const API = process.env.E2E_API_URL ?? 'http://localhost:8010';
const E2E_USERS_FILE = '/tmp/e2e-users.json';

/**
 * Reads the access_token cookie out of a response's set-cookie header.
 * Playwright joins multiple set-cookie values with newlines; each cookie's
 * value ends at the first `;` or separator.
 */
function extractAccessToken(setCookieHeader: string | undefined): string {
  const match = setCookieHeader?.match(/(?:^|[\n,])\s*access_token=([^;\s,]+)/);
  if (!match) {
    throw new Error(
      'Registration succeeded but the set-cookie response header contained no access_token cookie',
    );
  }
  return match[1];
}

/**
 * Registers a fresh user via the backend API and returns their credentials.
 * Because page.request shares the browser context's cookie jar, the
 * access_token and auth_logged_in cookies set by the register endpoint are
 * immediately available to the page — no UI login required.
 *
 * The token is written to E2E_USERS_FILE so globalTeardown can delete the
 * user via DELETE /auth/users/me after the suite finishes.
 */
export async function loginNewUser(page: Page): Promise<{ email: string; password: string }> {
  const email = `e2e-${Date.now()}@test.com`;
  const password = 'testpass123'; // pragma: allowlist secret

  const res = await page.request.post(`${API}/auth/register`, {
    data: { email, password },
    headers: { 'Content-Type': 'application/json' },
  });

  if (!res.ok()) {
    throw new Error(`Registration failed: ${res.status()} — ${await res.text()}`);
  }

  const token = extractAccessToken(res.headers()['set-cookie']);

  const existing: Array<{ email: string; token: string }> = fs.existsSync(E2E_USERS_FILE)
    ? (JSON.parse(fs.readFileSync(E2E_USERS_FILE, 'utf-8')) as Array<{ email: string; token: string }>)
    : [];
  existing.push({ email, token });
  fs.writeFileSync(E2E_USERS_FILE, JSON.stringify(existing), { mode: 0o600 });

  return { email, password };
}

export type SettingsTab = 'Account' | 'Notifications' | 'Bills' | 'Data';

/**
 * Opens the Settings page on the given tab. Sections below Account live in
 * client-side tabs (hash-synced), so tests must activate the target tab
 * before interacting with its content.
 */
export async function openSettingsTab(page: Page, tab: SettingsTab): Promise<void> {
  await page.goto(`/dashboard/settings#${tab.toLowerCase()}`);
  await page.getByRole('tab', { name: tab, exact: true }).click();
}

export interface BillOverrides {
  category?: string;
  frequency?: string;
  interval_count?: number;
  start_date?: string | null;
  amount?: string;
  currency?: string;
  due_day?: number;
  is_paused?: boolean;
}

/**
 * Creates a bill via the backend API. Requires an authenticated page context
 * (call loginNewUser first). Defaults to a monthly 99.99 PLN utilities bill
 * due on the 15th; pass overrides to vary category, state, etc.
 */
export async function createBillViaApi(
  page: Page,
  name: string,
  overrides: BillOverrides = {},
): Promise<number> {
  const res = await page.request.post(`${API}/bills`, {
    data: {
      name,
      category: 'utilities',
      frequency: 'monthly',
      amount: '99.99',
      currency: 'PLN',
      due_day: 15,
      is_paused: false,
      ...overrides,
    },
    headers: { 'Content-Type': 'application/json' },
  });

  if (!res.ok()) {
    throw new Error(`Create bill failed: ${res.status()} — ${await res.text()}`);
  }

  const bill = await res.json();
  return bill.id as number;
}

/**
 * Syncs payment instances for the current month via API, so rows appear on
 * the payments page without needing a UI interaction.
 */
export async function syncPaymentsViaApi(page: Page): Promise<void> {
  const month = new Date().toISOString().slice(0, 7);
  await page.request.post(`${API}/bills/sync-instances?month=${month}`);
}

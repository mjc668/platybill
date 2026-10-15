/**
 * Flow 17: Timezone preference, one-off usage toggle, instance amount editing
 * Risk: date-sensitive behaviour cannot follow the user's timezone; a one-off
 *       bill can still be marked usage-based (hiding it from the ledger); a
 *       wrong amount on an unpaid entry cannot be corrected.
 * Real boundaries: auth, PATCH /auth/me, POST /bills, GET /bills/payments,
 *                  PATCH /bills/payments/:id/amount, Settings and Payments UI.
 */
import { test, expect } from '@playwright/test';
import {
  loginNewUser,
  createBillViaApi,
  syncPaymentsViaApi,
  openSettingsTab,
} from './helpers';

test('one-off frequency hides the usage-based bill toggle', async ({ page }) => {
  await loginNewUser(page);
  await page.goto('/dashboard/bills');
  await page.getByRole('button', { name: 'New Bill' }).click();

  // Monthly (default): the toggle is available.
  await expect(page.getByLabel('Usage-based bill')).toBeVisible();

  await page.getByRole('button', { name: 'One-off', exact: true }).click();
  await expect(page.getByLabel('Usage-based bill')).not.toBeVisible();

  await page.getByRole('button', { name: 'Monthly', exact: true }).click();
  await expect(page.getByLabel('Usage-based bill')).toBeVisible();
});

test('timezone selection persists across reloads', async ({ page }) => {
  await loginNewUser(page);
  await openSettingsTab(page, 'Account');

  const select = page.getByLabel('Timezone');
  await expect(select).toBeVisible();
  await select.selectOption('Australia/Sydney');
  await page.getByRole('button', { name: 'Save', exact: true }).first().click();

  await page.reload();
  await openSettingsTab(page, 'Account');
  await expect(page.getByLabel('Timezone')).toHaveValue('Australia/Sydney');
});

test('editing the amount of an unpaid instance updates the row', async ({
  page,
}) => {
  await loginNewUser(page);
  await createBillViaApi(page, 'E2E Edit Amount');
  await syncPaymentsViaApi(page);

  await page.goto('/dashboard/payments');
  // Scope to the payment row: the amount also appears in summary tiles.
  const row = page
    .getByTestId('payment-row')
    .filter({ hasText: 'E2E Edit Amount' })
    .first();
  await expect(row.getByText('99.99 PLN')).toBeVisible();

  await row.getByRole('button', { name: 'Edit amount' }).click();
  const dialog = page.getByRole('dialog');
  await expect(dialog).toBeVisible();
  const input = dialog.getByLabel('Amount (PLN)');
  await input.fill('123.45');
  await dialog.getByRole('button', { name: 'Save' }).click();

  await expect(dialog).not.toBeVisible();
  await expect(row.getByText('123.45 PLN')).toBeVisible();
});

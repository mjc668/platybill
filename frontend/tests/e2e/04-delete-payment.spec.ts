/**
 * Flow 4: Delete a payment → disappears from list
 * Risk: DELETE API succeeds but UI retains the stale row — user thinks payment
 *       still exists and count never decrements.
 * Real boundaries: auth, DELETE /bills/payments/:id, UI list re-render.
 * Each test uses a fresh isolated user → exactly one payment row on the page.
 */
import { test, expect } from '@playwright/test';
import { loginNewUser, createBillViaApi, syncPaymentsViaApi } from './helpers';

test('deleted payment row disappears from the payments list', async ({ page }) => {
  const billName = `E2E Delete ${Date.now()}`;

  // Setup: authenticate + create bill + sync instances via API
  await loginNewUser(page);
  await createBillViaApi(page, billName);
  await syncPaymentsViaApi(page);

  // Step: navigate to payments page
  await page.goto('/dashboard/payments');
  const row = page.getByTestId('payment-row').filter({ hasText: billName }).first();
  await expect(row).toBeVisible();

  // Step: delete this month's row — and its future siblings, so the state is
  // deterministic even when the next occurrence is inside the due-soon window.
  await row.getByLabel('Delete payment').click();

  const dialog = page.getByRole('dialog');
  await expect(dialog).toBeVisible();
  await dialog
    .getByLabel('Also delete all future unpaid entries for this bill')
    .check();
  await dialog.getByRole('button', { name: 'Delete' }).click();

  // Reload so the client state reflects the future rows tombstoned above.
  await page.reload();

  // Assert: the payment row is gone (exact: true avoids matching parent containers
  // whose combined text content includes billName + other text like frequency)
  await expect(page.getByText(billName, { exact: true })).not.toBeVisible();

  // Assert: "No bills for this month" empty state appears (first() because the text
  // appears in both the heading and the description of the empty state)
  await expect(page.getByText('No bills for this month').first()).toBeVisible();
});

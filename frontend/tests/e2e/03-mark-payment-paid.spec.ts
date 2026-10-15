/**
 * Flow 3: Record a payment → status changes, ledger updates
 * Risk: optimistic UI update not reflected — "Mark as Paid" stays after payment
 *       is recorded, "Revert payment" never appears, or the ledger entry is missing.
 * Real boundaries: auth, POST /bills/payments/:id/payments, UI state re-render.
 * Each test uses a fresh isolated user → exactly one payment row on the page.
 */
import { test, expect } from '@playwright/test';
import { loginNewUser, createBillViaApi, syncPaymentsViaApi } from './helpers';

// Must match the amount created by createBillViaApi.
const BILL_AMOUNT = '99.99';

test('marking a payment paid replaces Mark as Paid with Revert payment', async ({ page }) => {
  const billName = `E2E Paid ${Date.now()}`;

  // Setup: authenticate + create bill + sync instances via API
  await loginNewUser(page);
  await createBillViaApi(page, billName);
  await syncPaymentsViaApi(page);

  // Step: navigate to payments page
  await page.goto('/dashboard/payments');
  // The due-soon view can list several occurrences of the same bill; the
  // earliest (this month's) row sorts first.
  const row = page.getByTestId('payment-row').filter({ hasText: billName }).first();
  await expect(row).toBeVisible();

  // Step: click "Mark as Paid" on this month's row
  await row.getByRole('button', { name: 'Mark as Paid' }).click();

  // MarkPaidDialog appears with a date field and the full amount pre-filled
  const dialog = page.getByRole('dialog');
  await expect(dialog).toBeVisible();
  await expect(dialog.getByLabel('Payment date')).toBeVisible();
  await expect(dialog.getByLabel('Amount paid')).toHaveValue(BILL_AMOUNT);
  await dialog.getByRole('button', { name: 'Mark as Paid' }).click();

  // After paying, the row moves sections — re-locate it via its Revert button.
  const paidRow = page
    .getByTestId('payment-row')
    .filter({ has: page.getByLabel('Revert payment') });
  await expect(paidRow).toHaveCount(1);
  await expect(paidRow.getByText(billName)).toBeVisible();

  // Assert: its "Mark as Paid" button is gone
  await expect(
    paidRow.getByRole('button', { name: 'Mark as Paid' }),
  ).not.toBeVisible();

  // Assert: a payment history entry is rendered on that row
  await expect(
    paidRow.getByText(`paid ${BILL_AMOUNT} of ${BILL_AMOUNT}`),
  ).toBeVisible();
  await expect(paidRow.getByLabel('Delete payment record')).toHaveCount(1);
});

test('partial payment keeps the row unpaid and shows the remaining balance', async ({ page }) => {
  const billName = `E2E Partial ${Date.now()}`;

  // Setup: authenticate + create bill + sync instances via API
  await loginNewUser(page);
  await createBillViaApi(page, billName);
  await syncPaymentsViaApi(page);

  await page.goto('/dashboard/payments');
  const row = page.getByTestId('payment-row').filter({ hasText: billName }).first();
  await expect(row).toBeVisible();

  // Derive the partial amount so the test works on any amount/date
  const half = (parseFloat(BILL_AMOUNT) / 2).toFixed(2);
  const remaining = (parseFloat(BILL_AMOUNT) - parseFloat(half)).toFixed(2);

  // Record a partial payment — only one "Mark as Paid" button here.
  await row.getByRole('button', { name: 'Mark as Paid' }).click();
  const dialog = page.getByRole('dialog');
  await expect(dialog).toBeVisible();
  await dialog.getByLabel('Amount paid').fill(half);
  await dialog.getByRole('button', { name: 'Mark as Paid' }).click();
  await expect(dialog).not.toBeVisible();

  // Assert: row is still unpaid, with paid-so-far and remaining shown
  await expect(row.getByRole('button', { name: 'Mark as Paid' })).toBeVisible();
  await expect(row.getByLabel('Revert payment')).not.toBeVisible();
  await expect(row.getByText(`paid ${half} of ${BILL_AMOUNT}`)).toBeVisible();
  await expect(row.getByText(`remaining ${remaining} PLN`)).toBeVisible();

  // Complete the payment — the dialog defaults to the remaining balance
  await row.getByRole('button', { name: 'Mark as Paid' }).click();
  const completeDialog = page.getByRole('dialog');
  await expect(completeDialog).toBeVisible();
  await expect(completeDialog.getByLabel('Amount paid')).toHaveValue(remaining);
  await completeDialog.getByRole('button', { name: 'Mark as Paid' }).click();
  await expect(completeDialog).not.toBeVisible();

  // Assert: fully paid, both ledger entries visible (re-locate: re-sorted)
  const paidRow = page
    .getByTestId('payment-row')
    .filter({ has: page.getByLabel('Revert payment') });
  await expect(paidRow).toHaveCount(1);
  await expect(
    paidRow.getByRole('button', { name: 'Mark as Paid' }),
  ).not.toBeVisible();
  await expect(
    paidRow.getByText(`paid ${BILL_AMOUNT} of ${BILL_AMOUNT}`),
  ).toBeVisible();
  await expect(paidRow.getByLabel('Delete payment record')).toHaveCount(2);
});

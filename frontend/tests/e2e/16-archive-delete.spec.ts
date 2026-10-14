/**
 * Flow 16: Delete an archived bill (soft delete)
 * Risk: a duplicate or closed bill cannot be removed from the archived list,
 *       or a deleted bill leaks back into any surface (bills lists, payments)
 *       instead of staying hidden while remaining in backups.
 * Real boundaries: auth, POST /bills/:id/archive, DELETE /bills/:id,
 *                  GET /bills, GET /bills/payments, GET /export/json.
 */
import { test, expect } from '@playwright/test';
import { API, loginNewUser, createBillViaApi, syncPaymentsViaApi } from './helpers';

test('deleting an archived bill hides it everywhere and keeps it in backups', async ({
  page,
}) => {
  const billName = `E2E Delete ${Date.now()}`;
  await loginNewUser(page);
  const billId = await createBillViaApi(page, billName);
  await syncPaymentsViaApi(page);

  const archiveRes = await page.request.post(`${API}/bills/${billId}/archive`);
  expect(archiveRes.ok()).toBeTruthy();

  // Step: the archived page lists the bill; delete it via the dialog.
  await page.goto('/dashboard/bills/archived');
  const row = page.getByTestId(`archived-bill-${billId}`);
  await expect(row).toBeVisible();
  await row.getByRole('button', { name: 'Delete', exact: true }).click();

  const dialog = page.getByRole('dialog');
  await expect(dialog).toBeVisible();
  await dialog.getByRole('button', { name: 'Delete', exact: true }).click();

  // Gone from the archived list immediately (and the dialog closes). Scope to
  // the row: the dialog title also contains the bill name while it is open.
  await expect(row).not.toBeVisible();
  await expect(dialog).not.toBeVisible();

  // Gone from the active bills page too.
  await page.goto('/dashboard/bills');
  await expect(page.getByText(billName)).not.toBeVisible();

  // Gone from payments — including the synced current-month row.
  await page.goto('/dashboard/payments');
  await expect(page.getByText(billName)).not.toBeVisible();

  // Backups still carry the row, flagged as deleted.
  const exportRes = await page.request.get(`${API}/export/json`);
  expect(exportRes.ok()).toBeTruthy();
  const backup = await exportRes.json();
  const saved = backup.bill_templates.find(
    (t: { name: string }) => t.name === billName,
  );
  expect(saved).toBeTruthy();
  expect(saved.is_deleted).toBe(true);
});

test('cancelling the delete dialog keeps the bill archived', async ({ page }) => {
  const billName = `E2E Keep ${Date.now()}`;
  await loginNewUser(page);
  const billId = await createBillViaApi(page, billName);

  const archiveRes = await page.request.post(`${API}/bills/${billId}/archive`);
  expect(archiveRes.ok()).toBeTruthy();

  await page.goto('/dashboard/bills/archived');
  const row = page.getByTestId(`archived-bill-${billId}`);
  await row.getByRole('button', { name: 'Delete', exact: true }).click();

  const dialog = page.getByRole('dialog');
  await expect(dialog).toBeVisible();
  await dialog.getByRole('button', { name: 'Cancel' }).click();
  await expect(dialog).not.toBeVisible();

  await expect(row).toBeVisible();
  await expect(page.getByText(billName)).toBeVisible();
});

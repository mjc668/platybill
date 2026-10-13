/**
 * Flow 8: Restore safety net — snapshot recovery
 * Risk: a mistaken restore permanently destroys the user's prior data with no
 * way back — the pre-restore snapshot must actually be recoverable through the
 * real UI, not just exist as a DB row.
 * Real boundaries: auth, POST /export/restore, GET /export/last-snapshot,
 * POST /export/restore-snapshot, DB round-trip, Settings page rendering.
 */
import { test, expect } from '@playwright/test';
import { loginNewUser, createBillViaApi, openSettingsTab } from './helpers';

test('restoring a backup creates a recoverable snapshot that restores the prior data', async ({
  page,
}) => {
  const billName = `E2E Snapshot ${Date.now()}`;

  // Setup: authenticate + create a bill via API (data that will be lost by the restore below)
  await loginNewUser(page);
  await createBillViaApi(page, billName);

  // Step: restore an empty backup — this wipes the bill created above and,
  // per the safety net, must snapshot it first.
  const apiUrl = process.env.E2E_API_URL ?? 'http://localhost:8010';
  const emptyBackup = {
    schema_version: 3,
    exported_by: 'e2e@test.com',
    exported_at: new Date().toISOString(),
    bill_templates: [],
    payment_instances: [],
  };
  const restoreRes = await page.request.post(`${apiUrl}/export/restore`, {
    multipart: {
      file: {
        name: 'backup.json',
        mimeType: 'application/json',
        buffer: Buffer.from(JSON.stringify(emptyBackup)),
      },
    },
  });
  expect(restoreRes.ok()).toBeTruthy();

  // Confirm the wipe actually happened.
  await page.goto('/dashboard/bills');
  await expect(page.getByText(billName)).not.toBeVisible();

  // Step: the recovery section appears in Settings > Data > Restore.
  await openSettingsTab(page, 'Data');
  await expect(
    page.getByText(/A snapshot of your data was saved on/)
  ).toBeVisible();

  // Step: restore from the snapshot.
  await page
    .getByRole('button', { name: 'Restore This Snapshot' })
    .click();
  const dialog = page.getByRole('dialog');
  await expect(dialog).toBeVisible();

  // Confirming triggers window.location.reload() on success (same URL, so
  // waitForURL wouldn't detect it) — wait for the reload's load event instead.
  await Promise.all([
    page.waitForEvent('load'),
    dialog.getByRole('button', { name: 'Restore', exact: true }).click(),
  ]);

  // Assert: the original bill is back.
  await page.goto('/dashboard/bills');
  await expect(page.getByText(billName)).toBeVisible();

  // Assert: the snapshot was consumed — recovery section no longer shows.
  await openSettingsTab(page, 'Data');
  await expect(
    page.getByText(/A snapshot of your data was saved on/)
  ).not.toBeVisible();
});

test('a user with no prior restore sees no recovery section', async ({ page }) => {
  await loginNewUser(page);

  await openSettingsTab(page, 'Data');
  await expect(
    page.getByText(/A snapshot of your data was saved on/)
  ).not.toBeVisible();
  await expect(
    page.getByRole('button', { name: 'Restore This Snapshot' })
  ).not.toBeVisible();
});

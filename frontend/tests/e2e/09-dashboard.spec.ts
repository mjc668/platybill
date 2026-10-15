/**
 * Flow 9: Dashboard stats overview
 * Risk: stats data is not rendered — the summary card ignores the recorded
 *       partial payment, the bills vs payments chart SVG is missing, the
 *       forecast series is absent for an active recurring bill, the rolling
 *       window cards are missing, the mini-calendar is missing, or the
 *       attention row links to the wrong month.
 * Real boundaries: auth, POST /bills, POST /bills/payments/:id/pay,
 *                  GET /bills/payments, GET /stats/overview, client render.
 */
import { test, expect } from '@playwright/test';
import { loginNewUser, createBillViaApi, syncPaymentsViaApi } from './helpers';

// Must match the amount created by createBillViaApi.
const BILL_AMOUNT = '99.99';

test('dashboard renders summary, trend chart and attention link after a partial payment', async ({
  page,
}) => {
  const billName = `E2E Dashboard ${Date.now()}`;

  // Setup: authenticate + create bill + sync instances via API
  await loginNewUser(page);
  await createBillViaApi(page, billName);
  await syncPaymentsViaApi(page);

  // Step: record a partial payment through the UI
  await page.goto('/dashboard/payments');
  const row = page.getByTestId('payment-row').filter({ hasText: billName }).first();
  await expect(row).toBeVisible();

  const half = (parseFloat(BILL_AMOUNT) / 2).toFixed(2);
  await row.getByRole('button', { name: 'Mark as Paid' }).click();
  const dialog = page.getByRole('dialog');
  await expect(dialog).toBeVisible();
  await dialog.getByLabel('Amount paid').fill(half);
  await dialog.getByRole('button', { name: 'Mark as Paid' }).click();
  await expect(dialog).not.toBeVisible();

  // Step: open the dashboard
  await page.goto('/dashboard');

  // Assert: the Paid summary card reflects the partial payment amount
  const paidCard = page.getByTestId('summary-paid');
  await expect(paidCard).toBeVisible();
  await expect(paidCard).toContainText(half);

  // Assert: the bills vs payments chart renders as an accessible image
  await expect(
    page.getByRole('img', { name: 'Bills vs payments chart' }),
  ).toBeVisible();

  // Assert: the rolling-window cards render. Their counts depend on today's
  // date relative to the bill's due day (15), so assert them structurally
  // (visible, primary currency shown) rather than hardcoding amounts.
  const next7dCard = page.getByTestId('summary-next-7d');
  await expect(next7dCard).toBeVisible();
  await expect(next7dCard).toContainText('PLN');
  const next30dCard = page.getByTestId('summary-next-30d');
  await expect(next30dCard).toBeVisible();
  await expect(next30dCard).toContainText('PLN');

  // Assert: the attention list shows the unpaid bill and links to its period
  // Several occurrences can be listed (overdue + upcoming); the overdue
  // link for this month's entry sorts first.
  const attentionRow = page
    .getByRole('link', { name: new RegExp(billName) })
    .first();
  await expect(attentionRow).toBeVisible();
  const month = new Date().toISOString().slice(0, 7);
  await expect(attentionRow).toHaveAttribute(
    'href',
    `/dashboard/payments?month=${month}`,
  );

  // Assert: the mini-calendar renders and links to the current month
  const miniCalendar = page.getByTestId('dashboard-mini-calendar');
  await expect(miniCalendar).toBeVisible();
  await expect(miniCalendar).toHaveAttribute(
    'href',
    `/dashboard/payments?month=${month}`,
  );

  // Assert: the forecast series shows up in the trend chart legend, because
  // the bill created above is active and recurring.
  await expect(page.getByTestId('trend-legend-forecast')).toBeVisible();
});

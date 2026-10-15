/**
 * Flow 10: Payments calendar view and filters
 * Risk: the calendar view does not render the month's instance chips or its
 *       selected-day panel, filters fail to narrow the list, or clearing
 *       filters does not restore the full month.
 * Real boundaries: auth, POST /bills, POST /bills/sync-instances,
 *                  GET /bills/payments, client-side render and filtering.
 */
import { test, expect } from '@playwright/test';
import { loginNewUser, createBillViaApi, syncPaymentsViaApi } from './helpers';

// Must match the default amount created by createBillViaApi.
const BILL_AMOUNT = '99.99';
const DUE_DAY = 15;

function isoDate(year: number, monthIndex: number, day: number): string {
  return `${year}-${String(monthIndex + 1).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
}

test('calendar view shows instance chips and the selected-day rows keep actions', async ({
  page,
}) => {
  const billName = `E2E Calendar ${Date.now()}`;

  // Setup: authenticate + create bill + sync instances via API
  await loginNewUser(page);
  await createBillViaApi(page, billName);
  await syncPaymentsViaApi(page);

  await page.goto('/dashboard/payments');
  await expect(page.getByText(billName).first()).toBeVisible();

  // Step: switch to the calendar view
  await page.getByRole('button', { name: 'Calendar' }).click();

  // Assert: the chip for this month's instance renders with its amount
  const grid = page.getByTestId('payment-calendar-grid');
  await expect(grid).toBeVisible();
  await expect(grid.getByText(billName).first()).toContainText(BILL_AMOUNT);

  // Step: select the due day
  const now = new Date();
  const dueDate = isoDate(now.getFullYear(), now.getMonth(), DUE_DAY);
  await page.getByTestId(`calendar-day-${dueDate}`).click();

  // Assert: the selected-day panel renders the existing PaymentRow actions
  const panel = page.getByTestId('calendar-selected-day');
  await expect(panel.getByText(billName).first()).toBeVisible();
  await expect(panel.getByRole('button', { name: 'Mark as Paid' })).toBeVisible();

  // Step: back to the list view — the row and its action are still there
  await page.getByRole('button', { name: 'List' }).click();
  await expect(page.getByText(billName).first()).toBeVisible();
  await expect(
    page.getByRole('button', { name: 'Mark as Paid' }).first(),
  ).toBeVisible();
});

test('filters narrow the payments list and clearing restores it', async ({ page }) => {
  const stamp = Date.now();
  const alpha = `E2E Filter Alpha ${stamp}`;
  const beta = `E2E Filter Beta ${stamp}`;

  // Setup: two bills in different categories
  await loginNewUser(page);
  await createBillViaApi(page, alpha);
  await createBillViaApi(page, beta, { category: 'housing' });
  await syncPaymentsViaApi(page);

  await page.goto('/dashboard/payments');
  await expect(page.getByText(alpha).first()).toBeVisible();
  await expect(page.getByText(beta).first()).toBeVisible();

  const filters = page.getByTestId('payment-filters');

  // Step: search narrows the list to one bill
  await filters.getByLabel('Search').fill('Alpha');
  await expect(page.getByText(alpha).first()).toBeVisible();
  await expect(page.getByText(beta).first()).not.toBeVisible();

  // Step: category filter narrows to the housing bill
  await filters.getByLabel('Search').fill('');
  await filters.getByLabel('Category').selectOption('housing');
  await expect(page.getByText(beta).first()).toBeVisible();
  await expect(page.getByText(alpha).first()).not.toBeVisible();

  // Step: clearing filters restores both bills
  await filters.getByRole('button', { name: 'Clear filters' }).click();
  await expect(page.getByText(alpha).first()).toBeVisible();
  await expect(page.getByText(beta).first()).toBeVisible();

  // Assert: a search with no hits shows the distinct "no matches" state,
  // and its action restores the list
  await filters.getByLabel('Search').fill('zzz-no-such-bill');
  await expect(page.getByText('No payments match these filters')).toBeVisible();
  await page
    .getByTestId('payment-no-matches')
    .getByRole('button', { name: 'Clear filters' })
    .click();
  await expect(page.getByText(alpha).first()).toBeVisible();
  await expect(page.getByText(beta).first()).toBeVisible();
});

/**
 * Flow 13: Editable categories
 * Risk: a custom category cannot be created (Settings or the bill form picker),
 *       a bill does not adopt/relabel with it, archiving leaves it selectable,
 *       or an in-use category is deleted instead of the server 400 being shown.
 * Real boundaries: auth, POST/PATCH/DELETE /categories, GET /categories,
 *                  POST /bills, GET /bills, client-side grouping and pickers.
 */
import { test, expect } from '@playwright/test';
import { loginNewUser } from './helpers';

test('custom category can be created, used, renamed, archived, and deleted', async ({
  page,
}) => {
  const stamp = Date.now();
  const customName = `E2E Custom ${stamp}`;
  const renamedName = `E2E Renamed ${stamp}`;
  const unusedName = `E2E Unused ${stamp}`;
  const billName = `E2E Category Bill ${stamp}`;

  await loginNewUser(page);

  // Setup: create a custom category in Settings
  await page.goto('/dashboard/settings');
  const categoriesTile = page.getByTestId('categories-tile');
  await expect(categoriesTile).toBeVisible();
  await categoriesTile.getByLabel('New category').fill(customName);
  await categoriesTile.getByRole('button', { name: 'Add', exact: true }).click();
  await expect(categoriesTile.getByText(customName, { exact: true })).toBeVisible();

  // Step: create a bill with the custom category through the form
  await page.goto('/dashboard/bills');
  await page.getByRole('button', { name: 'New Bill' }).click();
  await page.getByLabel('Name').fill(billName);
  await page.getByLabel('Amount').fill('45.00');
  await page.getByLabel('Category').selectOption({ label: customName });
  await page.getByRole('button', { name: 'Save' }).click();

  // Assert: the bill is grouped under the custom category label
  await expect(page.getByText(billName)).toBeVisible();
  await page.getByRole('button', { name: 'By category' }).click();
  await expect(
    page.getByRole('button', { name: new RegExp(customName) }),
  ).toBeVisible();

  // Step: rename the category in Settings
  await page.goto('/dashboard/settings');
  await expect(categoriesTile).toBeVisible();
  const row = categoriesTile.getByRole('listitem').filter({ hasText: customName });
  await expect(row).toBeVisible();
  await row.getByRole('button', { name: 'Rename' }).click();
  await categoriesTile.locator('input[aria-label="Rename"]').fill(renamedName);
  await categoriesTile.getByRole('button', { name: 'Save' }).click();
  await expect(categoriesTile.getByText(renamedName, { exact: true })).toBeVisible();

  // Assert: the bill relabels with the new category name
  await page.goto('/dashboard/bills');
  await expect(page.getByText(billName)).toBeVisible();
  await page.getByRole('button', { name: 'By category' }).click();
  await expect(
    page.getByRole('button', { name: new RegExp(renamedName) }),
  ).toBeVisible();
  await expect(page.getByText(customName, { exact: true })).toHaveCount(0);

  // Step: deleting an in-use category is refused with the server message
  await page.goto('/dashboard/settings');
  await expect(categoriesTile).toBeVisible();
  const renamedRow = categoriesTile
    .getByRole('listitem')
    .filter({ hasText: renamedName });
  await renamedRow.getByRole('button', { name: 'Delete' }).click();
  await renamedRow.getByRole('button', { name: 'Delete' }).click();
  await expect(categoriesTile.getByTestId('category-error')).toContainText(/\S/);
  await expect(renamedRow).toBeVisible();

  // Step: archive the category
  await renamedRow.getByRole('button', { name: 'Archive' }).click();
  await expect(renamedRow.getByText('Archived')).toBeVisible();

  // Assert: an archived category is gone from the bill form picker
  await page.goto('/dashboard/bills');
  await page.getByRole('button', { name: 'New Bill' }).click();
  const picker = page.getByLabel('Category').last();
  await expect(picker.getByRole('option', { name: renamedName })).toHaveCount(0);

  // Step: create an unused category and delete it
  await page.goto('/dashboard/settings');
  await expect(categoriesTile).toBeVisible();
  await categoriesTile.getByLabel('New category').fill(unusedName);
  await categoriesTile.getByRole('button', { name: 'Add', exact: true }).click();
  await expect(categoriesTile.getByText(unusedName, { exact: true })).toBeVisible();
  const unusedRow = categoriesTile
    .getByRole('listitem')
    .filter({ hasText: unusedName });
  await unusedRow.getByRole('button', { name: 'Delete' }).click();
  await unusedRow.getByRole('button', { name: 'Delete' }).click();
  await expect(categoriesTile.getByText(unusedName, { exact: true })).toHaveCount(0);
});

test('inline add in the bill form creates and selects a category', async ({ page }) => {
  const stamp = Date.now();
  const categoryName = `E2E Inline ${stamp}`;
  const billName = `E2E Inline Bill ${stamp}`;

  await loginNewUser(page);
  await page.goto('/dashboard/bills');
  await page.getByRole('button', { name: 'New Bill' }).click();
  await page.getByLabel('Name').fill(billName);

  // Step: pick "Add new…" and create the category inline
  await page.getByLabel('Category').selectOption({ label: 'Add new…' });
  await page.getByLabel('e.g. Utilities').fill(categoryName);
  await page.getByRole('button', { name: 'Add', exact: true }).click();
  await page.getByRole('button', { name: 'Save' }).click();

  // Assert: the bill is grouped under the inline-created category
  await expect(page.getByText(billName)).toBeVisible();
  await page.getByRole('button', { name: 'By category' }).click();
  await expect(
    page.getByRole('button', { name: new RegExp(categoryName) }),
  ).toBeVisible();
});

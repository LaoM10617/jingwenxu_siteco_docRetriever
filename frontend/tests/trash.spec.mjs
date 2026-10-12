import {test, expect} from '@playwright/test';

test('move selected material, restore, cancel and confirm empty Trash', async ({page}) => {
  const doc = {document_id: 'trash-fixture', original_filename: 'example.csv', status: 'ready', stage: 'ready', error: null, warnings: [], parsing: null};
  let trashed = false, deleted = false;
  await page.route('**/api/documents', route => route.fulfill({json: trashed || deleted ? [] : [doc]}));
  await page.route('**/api/trash', route => {
    if (route.request().method() === 'DELETE') {
      deleted = true;
      return route.fulfill({json: {deleted: 1}});
    }
    return route.fulfill({json: trashed && !deleted ? [{...doc, status: 'trashed'}] : []});
  });
  await page.route('**/api/documents/trash-fixture/trash', route => {
    trashed = true;
    return route.fulfill({json: {...doc, status: 'trashed'}});
  });
  await page.route('**/api/documents/trash-fixture/restore', route => {
    trashed = false;
    return route.fulfill({json: doc});
  });
  await page.goto('/');
  await page.getByRole('button', {name: 'Show sidebar', exact: true}).click();
  await page.getByRole('checkbox').check();
  await page.getByRole('button', {name: 'Move to Trash', exact: true}).click();
  await expect(page.getByText('No materials yet.', {exact: true})).toBeVisible();
  await page.getByRole('button', {name: 'Trash', exact: true}).click();
  await page.getByRole('button', {name: 'Restore', exact: true}).click();
  await expect(page.getByText('Trash is empty.', {exact: true})).toBeVisible();
  await page.getByRole('button', {name: 'Materials', exact: true}).click();
  await expect(page.getByRole('checkbox')).not.toBeChecked();
  await page.getByRole('button', {name: 'Move to Trash', exact: true}).click();
  await page.getByRole('button', {name: 'Trash', exact: true}).click();
  page.once('dialog', dialog => dialog.dismiss());
  await page.getByRole('button', {name: 'Empty Trash', exact: true}).click();
  expect(deleted).toBe(false);
  await expect(page.getByRole('button', {name: 'Restore', exact: true})).toBeVisible();
  page.once('dialog', dialog => dialog.accept());
  await page.getByRole('button', {name: 'Empty Trash', exact: true}).click();
  await expect(page.getByText('Trash is empty.', {exact: true})).toBeVisible();
  expect(deleted).toBe(true);
});

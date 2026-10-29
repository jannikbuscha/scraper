// Page helpers of the E2E suite: locators by role and accessible name
// (docs/UI.md; the names come from the components).
import type { Locator, Page } from '@playwright/test';

import { expect } from './fixtures';

/** The data rows of the entity table: rows with a "Select <label>" checkbox. */
export function tableRows(page: Page): Locator {
  return page
    .getByRole('table')
    .getByRole('row')
    .filter({ has: page.getByRole('checkbox', { name: /^Select (?!all rows on this page$)/ }) });
}

/** The rows show exactly these record labels, in this order. */
export async function expectRowLabels(page: Page, labels: readonly string[]): Promise<void> {
  await expect(page.getByRole('table')).toHaveAttribute('aria-busy', 'false');
  const links = page.getByRole('table').getByRole('link', { name: /^Open / });
  await expect(links).toHaveCount(labels.length);
  for (const [index, label] of labels.entries()) {
    await expect(links.nth(index)).toHaveAccessibleName(`Open ${label}`);
  }
}

/** The page URL has exactly these search parameters (decoded). */
export async function expectSearch(page: Page, expected: Readonly<Record<string, string>>): Promise<void> {
  const wanted = JSON.stringify(Object.entries(expected).sort());
  await expect(page).toHaveURL((url) => JSON.stringify([...url.searchParams.entries()].sort()) === wanted);
}

/** The sort button of a column header; its name may end with the sort position (e.g. "Name (English) 2"). */
export function sortButton(page: Page, label: string): Locator {
  return page.getByRole('button', { name: new RegExp(`^${escapeRegExp(label)}( \\d)?$`) });
}

export function columnHeader(page: Page, label: string): Locator {
  return page.getByRole('columnheader', { name: new RegExp(`^${escapeRegExp(label)}`) });
}

/** Opens the filter popover of a column and returns its form. */
export async function openFilter(page: Page, label: string): Promise<Locator> {
  await page.getByRole('button', { name: new RegExp(`^Filter ${escapeRegExp(label)}( \\(active\\))?$`) }).click();
  const form = page.getByRole('form', { name: `Filter ${label}`, exact: true });
  await expect(form).toBeVisible();
  return form;
}

/**
 * Clicks a control by its visible label: Mantine chips and segmented controls
 * hide their inputs and are operated through the label, like a user does.
 */
export async function clickLabel(scope: Page | Locator, text: string): Promise<void> {
  await scope
    .locator('label')
    .filter({ hasText: new RegExp(`^${escapeRegExp(text)}$`) })
    .click();
}

/** A labelled input whose accessible name may end with its help icon ("About <label>"). */
export function fieldInput(scope: Page | Locator, label: string): Locator {
  return scope.getByRole('textbox', { name: new RegExp(`^${escapeRegExp(label)}( About |$)`) });
}

export function escapeRegExp(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

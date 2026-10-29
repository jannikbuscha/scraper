// Scenario (h) of docs/UI.md §7: CSV and XLSX exports of a filtered, sorted view.
import { readFile } from 'node:fs/promises';

import type { Page } from '@playwright/test';

import { parseCsv, readXlsx } from './files';
import { expect, test } from './fixtures';
import { expectRowLabels } from './helpers';

/** Runs an export from the toolbar menu and returns the downloaded file. */
async function exportView(page: Page, item: string): Promise<{ name: string; content: Buffer }> {
  const downloaded = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Export' }).click();
  await page.getByRole('menuitem', { name: item }).click();
  const download = await downloaded;
  return { name: download.suggestedFilename(), content: await readFile(await download.path()) };
}

test('(h) export CSV and XLSX of a filtered view', async ({ page }) => {
  // The three projects of one paper cluster, sorted by name_en.
  const names = ['Brave1', 'Ukrainian Startup Fund', 'WINWIN'];
  await page.goto('/projects?f.paper_cluster=in:defense_technology_innovation&sort=name_en');
  await expectRowLabels(page, names);

  const csv = await exportView(page, 'CSV (for analysis tools)');
  expect(csv.name).toMatch(/^project-\d{8}-\d{6}\.csv$/);
  const text = csv.content.toString('utf8');
  expect(text.startsWith('﻿'), 'UTF-8 with byte order mark').toBe(true);
  const [header = [], ...rows] = parseCsv(text.slice(1));
  // Registry names: the ID, the list fields, a label next to each vocabulary code.
  expect(header).toEqual(expect.arrayContaining(['id', 'name_en', 'name_uk', 'paper_cluster', 'paper_cluster_label']));
  const csvColumn = (name: string) => rows.map((row) => row[header.indexOf(name)]);
  expect(csvColumn('name_en')).toEqual(names);
  expect(csvColumn('paper_cluster')).toEqual(names.map(() => 'defense_technology_innovation'));
  expect(csvColumn('name_uk')).toEqual(['', 'Український фонд стартапів', '']);

  const xlsx = await exportView(page, 'XLSX (for Excel, exact values)');
  expect(xlsx.name).toMatch(/^project-\d{8}-\d{6}\.xlsx$/);
  const [xlsxHeader, ...xlsxRows] = readXlsx(xlsx.content);
  expect(xlsxHeader).toEqual(header);
  const xlsxColumn = (name: string) => xlsxRows.map((row) => row[header.indexOf(name)]);
  expect(xlsxColumn('id')).toEqual(csvColumn('id'));
  expect(xlsxColumn('name_en')).toEqual(names);
  expect(xlsxColumn('paper_cluster_label')).toEqual(csvColumn('paper_cluster_label'));
});

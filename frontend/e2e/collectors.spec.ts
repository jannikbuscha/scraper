// Phase 2 scenarios of docs/UI.md §8.9, run serially in the `collectors`
// project against a server of their own whose collectors answer from the
// stored fixtures of backend/tests/fixtures/ministry_projects (replay; no
// request leaves the machine). Values that are not in the fixtures are
// synthetic. The scenarios build on each other in the listed order: (i)
// imports the collector values that (j) works with, and (o) and (p) use the
// runs and collected values of the earlier scenarios.
import type { Locator, Page } from '@playwright/test';

import { expect, test, uniqueSuffix, type Api, type Item } from './fixtures';
import { clickLabel, escapeRegExp, fieldInput } from './helpers';

test.describe.configure({ mode: 'serial' });

const COLLECTOR = 'ministry_projects';
const COLLECTOR_LABEL = /Ministry project list/;
/** Replayed runs take seconds; the margin covers a slow machine. */
const RUN_TIMEOUT = 120_000;

interface Run {
  id: string;
  status: string;
  stats: Record<string, number>;
}

/** Starts a run through the API and waits until it has finished. */
async function runCollector(api: Api): Promise<Run> {
  const { run } = await api.write<{ run: Run }>('POST', '/api/runs', { collector: COLLECTOR, params: {} });
  await expect
    .poll(async () => (await api.get<{ run: Run }>(`/api/runs/${run.id}`)).run.status, { timeout: RUN_TIMEOUT })
    .not.toBe('running');
  return (await api.get<{ run: Run }>(`/api/runs/${run.id}`)).run;
}

/** The value of one statistic on a run page (a `dt`/`dd` pair). */
function stat(page: Page, label: string): Locator {
  return page
    .locator('dt', { hasText: new RegExp(`^${escapeRegExp(label)}$`) })
    .locator('xpath=following-sibling::dd[1]');
}

/** The row of a field on a detail page (its `dt` label and the values beside it). */
function fieldRow(page: Page, label: string): Locator {
  return page.locator('dt', { hasText: new RegExp(`^${escapeRegExp(label)}`) }).locator('xpath=..');
}

/** Waits until the run page shows a finished status. */
async function waitUntilFinished(page: Page): Promise<string> {
  const status = page.getByRole('group', { name: 'Status' });
  await expect(status).not.toContainText('running', { timeout: RUN_TIMEOUT });
  return (await status.innerText()).trim();
}

test('(i) DoD 3: a second run of the same responses writes nothing', async ({ page, api }) => {
  await page.goto('/runs');
  await page.getByRole('button', { name: 'Start run' }).click();
  const dialog = page.getByRole('dialog', { name: 'Start a collector run' });
  await dialog.getByRole('combobox', { name: 'Collector' }).click();
  await page.getByRole('option', { name: COLLECTOR_LABEL }).click();
  await dialog.getByRole('button', { name: 'Start run' }).click();
  await expect(page).toHaveURL(/\/runs\/run_/);
  const firstId = page.url().split('/runs/')[1]?.split('?')[0] ?? '';

  // Detail pages without fixtures are refused, so the run ends partial.
  expect(await waitUntilFinished(page)).toContain('partial');
  await expect(stat(page, 'Records updated')).not.toHaveText('0');
  await expect(stat(page, 'Proposals opened')).not.toHaveText('0');
  await expect(stat(page, 'New observations')).not.toHaveText('0');

  // Messages: the refused requests and the unknown rubric code of how-tos.
  const messages = page.getByRole('tabpanel', { name: /Messages/ });
  await expect(messages.getByRole('row').filter({ hasText: 'http_error' }).first()).toBeVisible();
  await expect(messages.getByRole('row').filter({ hasText: 'unknown_code' }).filter({ hasText: /how.tos/ }).first()).toBeVisible();
  await page.getByRole('tab', { name: 'Fetch log' }).click();
  await expect(page.getByRole('tabpanel', { name: 'Fetch log' }).getByRole('row').filter({ hasText: 'refused' }).first()).toBeVisible();

  // The same responses again: nothing is created, revised or proposed.
  await page.getByRole('button', { name: 'Run again' }).click();
  // The first run's page may carry a tab in its query string: wait for another run ID.
  await expect(page).toHaveURL(/\/runs\/run_/);
  await expect(page).not.toHaveURL(new RegExp(escapeRegExp(firstId)));
  const secondId = page.url().split('/runs/')[1]?.split('?')[0] ?? '';
  await waitUntilFinished(page);
  await expect(stat(page, 'Records created')).toHaveText('0');
  await expect(stat(page, 'Revisions')).toHaveText('0');
  await expect(stat(page, 'Proposals opened')).toHaveText('0');
  await expect(stat(page, 'Proposals seen again')).not.toHaveText('0');

  await page.goto('/runs');
  await expect(page.getByRole('link', { name: `Open run ${firstId}` })).toBeVisible();
  await expect(page.getByRole('link', { name: `Open run ${secondId}` })).toBeVisible();

  await page.goto(`/changes?run_id=${secondId}`);
  await expect(page.getByText('No changes match the filters')).toBeVisible();
  const second = await api.get<{ run: Run }>(`/api/runs/${secondId}`);
  expect(second.run.stats.revisions).toBe(0);
});

test('(j) DoD 5: manual values win; accept, edit & accept and reject', async ({ page, api }) => {
  const suffix = uniqueSuffix();
  const slugs = ['brave1', 'diia-city', 'virtual-assets'] as const;
  const projects: Record<string, Item> = {};
  for (const slug of slugs) {
    const project = await api.project(slug);
    projects[slug] = project;
    // After (i), the description comes from the collector.
    await page.goto(`/projects/${project.id}`);
    await expect(fieldRow(page, 'Description (Ukrainian)').getByRole('button', { name: /^Provenance: collector:/ })).toBeVisible();
    // A person edits it: manual and locked.
    await api.patch('project', project.id, { description_uk: `Synthetic manual description ${slug} ${suffix}` }, `Synthetic edit ${suffix}`);
  }

  await runCollector(api);

  const brave1 = projects.brave1;
  if (!brave1) throw new Error('brave1 missing');
  await page.goto(`/projects/${brave1.id}`);
  const row = fieldRow(page, 'Description (Ukrainian)');
  await expect(row).toContainText(`Synthetic manual description brave1 ${suffix}`);
  await expect(row.getByLabel('Provenance: manual')).toBeVisible();
  await expect(row.getByRole('link', { name: '1 proposal' })).toBeVisible();

  await page.goto(`/review?collector=${COLLECTOR}&kind=update_field&field=description_uk`);
  const card = (label: string) => page.getByRole('article').filter({ hasText: label });
  for (const label of ['Brave1', 'Diia.City', 'Virtual Assets']) {
    await expect(card(label)).toBeVisible();
    await expect(card(label)).toContainText('manual');
    await expect(card(label)).toContainText('collector');
  }

  // Accept: the collector value, with the collector as its provenance, locked.
  await card('Brave1').getByRole('button', { name: 'Accept', exact: true }).click();
  await expect(page.getByText('Accepted the proposal.')).toBeVisible();
  await page.goto(`/projects/${brave1.id}`);
  await expect(fieldRow(page, 'Description (Ukrainian)').getByRole('button', { name: /^Provenance: collector:/ })).toBeVisible();
  await expect(fieldRow(page, 'Description (Ukrainian)').getByRole('img', { name: 'Locked' })).toBeVisible();
  await page.getByRole('tab', { name: 'History' }).click();
  await expect(page.getByRole('row').filter({ hasText: 'proposal' }).first()).toBeVisible();

  // Edit & accept: the edited value is manual; the proposal is accepted with changes.
  await page.goto(`/review?collector=${COLLECTOR}&kind=update_field&field=description_uk`);
  await card('Diia.City').getByRole('button', { name: 'Edit & accept…' }).click();
  const edit = page.getByRole('dialog', { name: 'Edit & accept' });
  const edited = `Synthetic edited description ${suffix}`;
  await edit.getByRole('textbox', { name: /Description \(Ukrainian\)/ }).fill(edited);
  await edit.getByRole('button', { name: 'Accept' }).click();
  await expect(page.getByText('Accepted the proposal.')).toBeVisible();
  await page.goto(`/review?collector=${COLLECTOR}&field=description_uk&state=accepted_modified`);
  await expect(card('Diia.City')).toContainText('accepted with changes');
  const diiaCity = projects['diia-city'];
  if (!diiaCity) throw new Error('diia-city missing');
  await page.goto(`/projects/${diiaCity.id}`);
  await expect(fieldRow(page, 'Description (Ukrainian)')).toContainText(edited);
  await expect(fieldRow(page, 'Description (Ukrainian)').getByLabel('Provenance: manual')).toBeVisible();

  // Reject with a note: the manual value stays.
  await page.goto(`/review?collector=${COLLECTOR}&kind=update_field&field=description_uk`);
  await card('Virtual Assets').getByRole('button', { name: 'Reject…' }).click();
  const reject = page.getByRole('dialog', { name: 'Reject proposal' });
  await reject.getByRole('textbox', { name: /Reason/ }).fill(`Synthetic rejection ${suffix}`);
  await reject.getByRole('button', { name: 'Reject' }).click();
  await expect(page.getByText('Rejected the proposal.')).toBeVisible();
  const virtualAssets = projects['virtual-assets'];
  if (!virtualAssets) throw new Error('virtual-assets missing');
  expect((await api.item('project', virtualAssets.id)).fields.description_uk).toBe(`Synthetic manual description virtual-assets ${suffix}`);

  // A further run opens no new proposal for the three.
  await runCollector(api);
  const open = await api.get<{ items: { subject_id: string }[] }>(
    `/api/proposals?collector=${COLLECTOR}&field=description_uk&page_size=500`,
  );
  const subjects = new Set(open.items.map((proposal) => proposal.subject_id));
  for (const project of Object.values(projects)) expect(subjects.has(project.id)).toBe(false);
});

test('(l) manual document: upload, create, tag now, confirm the suggested link', async ({ page }) => {
  const suffix = uniqueSuffix();
  const title = `Synthetic page ${suffix}`;
  const html = `<!doctype html><html><head><title>${title}</title></head><body><p>A synthetic text that mentions Brave1 (${suffix}).</p></body></html>`;

  await page.goto('/documents');
  await page.getByRole('button', { name: 'Add document' }).click();
  const dialog = page.getByRole('dialog', { name: 'Add a document' });
  await dialog.getByRole('tab', { name: 'Upload file' }).click();
  await dialog.locator('input[type="file"]').setInputFiles({ name: `synthetic-${suffix}.html`, mimeType: 'text/html', buffer: Buffer.from(html) });
  await expect(fieldInput(dialog, 'Title')).toHaveValue(title);
  await dialog.getByRole('button', { name: 'Create' }).click();
  await expect(dialog.getByText('Document created')).toBeVisible();
  await dialog.getByRole('button', { name: 'Open' }).click();

  await expect(page.getByRole('heading', { level: 1, name: title })).toBeVisible();
  await expect(page.getByRole('region', { name: 'Extracted text' })).toContainText('A synthetic text that mentions Brave1');
  const links = page.getByRole('region', { name: 'Document links' });
  await links.getByRole('button', { name: 'Tag now' }).click();
  await expect(links.getByRole('link', { name: 'Tagging run' })).toBeVisible({ timeout: RUN_TIMEOUT });
  const suggested = links.getByRole('row').filter({ hasText: 'Brave1' });
  await expect(suggested).toContainText('suggested', { timeout: RUN_TIMEOUT });
  await suggested.getByRole('button', { name: 'Confirm the link to Brave1' }).click();
  await expect(suggested).toContainText('confirmed');
});

test('(m) import: dry run, run, changes, and a conflict with a manual value', async ({ page, api }) => {
  const suffix = uniqueSuffix();
  const note = `Synthetic import note ${suffix}`;

  await page.goto('/import');
  await page.locator('input[type="file"]').setInputFiles({
    name: `synthetic-${suffix}.csv`,
    mimeType: 'text/csv',
    buffer: Buffer.from(`slug,notes\nmriia,${note}\n`),
  });
  await page.getByRole('combobox', { name: 'Record type' }).click();
  await page.getByRole('option', { name: 'Projects' }).click();
  await expect(page.getByRole('combobox', { name: 'Field for column notes' })).toHaveValue('Notes');
  await expect(page.getByRole('combobox', { name: 'Key' })).toHaveValue('Slug');
  await page.getByRole('button', { name: 'Dry run' }).click();
  await expect(page.getByLabel('Update: 1')).toBeVisible();
  await page.getByRole('button', { name: 'Run import' }).click();
  await page.getByRole('dialog', { name: 'Run the import' }).getByRole('button', { name: /^Import/ }).click();
  const result = page.getByRole('region', { name: 'Import result' });
  await expect(result).toBeVisible();
  await result.getByRole('link', { name: 'Show changes' }).click();
  await expect(page).toHaveURL(/batch_id=imp_/);
  await expect(page.getByRole('row').filter({ hasText: 'Mriia' }).first()).toContainText('import');

  // A field the user edited manually is reported as a conflict, not overwritten.
  const campus = await api.project('cdto-campus');
  await api.patch('project', campus.id, { notes: `Synthetic manual note ${suffix}` }, `Synthetic edit ${suffix}`);
  await page.goto('/import');
  await page.locator('input[type="file"]').setInputFiles({
    name: `synthetic-conflict-${suffix}.csv`,
    mimeType: 'text/csv',
    buffer: Buffer.from(`slug,notes\ncdto-campus,Synthetic imported note ${suffix}\n`),
  });
  await page.getByRole('combobox', { name: 'Record type' }).click();
  await page.getByRole('option', { name: 'Projects' }).click();
  await page.getByRole('button', { name: 'Dry run' }).click();
  await expect(page.getByLabel('Conflicts: 1')).toBeVisible();
  await expect(page.getByRole('region', { name: 'Dry run' })).toContainText('set by a person');
});

test('(n) merge two services, then unmerge them', async ({ page, api }) => {
  const suffix = uniqueSuffix();
  const project = await api.project('diia');
  const create = async (name: string, description: string) =>
    (
      await api.write<{ item: Item }>('POST', '/api/entities/service', {
        data: { project_id: project.id, name_en: name, description_en: description },
        note: `Synthetic setup ${suffix}`,
      })
    ).item;
  const survivor = await create(`Synthetic service A ${suffix}`, `Synthetic description A ${suffix}`);
  const merged = await create(`Synthetic service B ${suffix}`, `Synthetic description B ${suffix}`);

  await page.goto(`/services/${survivor.id}`);
  await page.getByRole('button', { name: 'Merge…' }).click();
  const dialog = page.getByRole('dialog', { name: 'Merge duplicates' });
  const other = dialog.getByRole('combobox', { name: /Merged into the survivor/ });
  await other.fill(`Synthetic service B ${suffix}`);
  await page.getByRole('option', { name: new RegExp(escapeRegExp(`Synthetic service B ${suffix}`)) }).click();
  const choice = dialog.getByRole('radiogroup', { name: 'Value of Description (English)' });
  await expect(choice).toBeVisible();
  await clickLabel(choice, 'Take other');
  await dialog.getByRole('button', { name: 'Merge', exact: true }).click();
  await expect(dialog).toBeHidden();
  await expect(page.getByText(`Synthetic description B ${suffix}`)).toBeVisible();

  await page.goto('/trash?type=service');
  const row = page.getByRole('row').filter({ hasText: `Synthetic service B ${suffix}` });
  // The survivor by its label, as on the merged record's page.
  await expect(row).toContainText(`Merged into Synthetic service A ${suffix}`);
  await row.getByRole('button', { name: `Unmerge Synthetic service B ${suffix}` }).click();
  const unmerge = page.getByRole('dialog', { name: 'Unmerge' });
  await expect(unmerge.getByRole('button', { name: 'Close dialog', exact: true })).toBeVisible();
  await unmerge.getByRole('button', { name: 'Unmerge' }).click();
  // The footer button; the header's close button is named "Close dialog".
  await unmerge.getByRole('button', { name: 'Close', exact: true }).click();

  expect((await api.item('service', merged.id)).fields.name_en).toBe(`Synthetic service B ${suffix}`);
  const restored = await api.get<{ item: Item & { deleted_at: string | null } }>(`/api/entities/service/${merged.id}`);
  expect(restored.item.deleted_at).toBeNull();
  await page.goto(`/services/${survivor.id}`);
  await expect(page.getByText(`Synthetic description A ${suffix}`)).toBeVisible();
});

/** A synthetic URL of about 250 characters without a single break opportunity. */
const LONG_URL = `https://example.org/${'synthetic'.repeat(26)}`;

/** Answers the matching API requests as the server does, with LONG_URL put in by `patch`. */
async function withLongUrl(page: Page, matches: (url: URL) => boolean, patch: (body: unknown) => void) {
  await page.route(matches, async (route) => {
    const response = await route.fetch();
    const body: unknown = await response.json();
    patch(body);
    await route.fulfill({ response, json: body });
  });
}

/** The DOM members the layout check reads (the E2E code is type-checked without the DOM library). */
interface Measured {
  readonly scrollWidth: number;
  readonly clientWidth: number;
  readonly ownerDocument: { readonly documentElement: { readonly clientWidth: number } };
  getBoundingClientRect(): { readonly right: number };
  getClientRects(): { readonly length: number };
  querySelectorAll(selector: string): Iterable<Measured>;
}

/** How a table fits the viewport: the right edge of its last column, cut badges and broken times. */
async function tableLayout(table: Locator) {
  return table.evaluate((element: Measured) => ({
    right: Math.max(...[...element.querySelectorAll('thead th')].map((th) => th.getBoundingClientRect().right)),
    viewport: element.ownerDocument.documentElement.clientWidth,
    cutBadges: [...element.querySelectorAll('.mantine-Badge-label')].filter((label) => label.scrollWidth > label.clientWidth + 1).length,
    timesOnSeveralLines: [...element.querySelectorAll('time')].filter((time) => time.getClientRects().length > 1).length,
  }));
}

async function expectReadable(table: Locator) {
  await expect(table.getByRole('link', { name: LONG_URL })).toBeVisible();
  const layout = await tableLayout(table);
  // Every column is on screen, no badge is cut to a letter and no time is broken over lines.
  expect(layout.right).toBeLessThanOrEqual(layout.viewport);
  expect(layout.cutBadges).toBe(0);
  expect(layout.timesOnSeveralLines).toBe(0);
}

test('(o) a long URL keeps the run, source and detail tables readable', async ({ page, api }) => {
  const runs = await api.get<{ items: Run[] }>(`/api/runs?collector=${COLLECTOR}&page_size=1`);
  const run = runs.items[0];
  if (!run) throw new Error('no run of the collector');
  // The first entry of each list gets the long URL; the rest of the answer is the server's.
  const patchFirst = (body: unknown) => {
    const first = (body as { items: { url: string | null }[] }).items[0];
    if (first) first.url = LONG_URL;
  };
  await withLongUrl(page, (url) => url.pathname === `/api/runs/${run.id}/messages`, patchFirst);
  await withLongUrl(page, (url) => url.pathname === `/api/runs/${run.id}/fetches`, patchFirst);
  await withLongUrl(page, (url) => url.pathname === '/api/observations', patchFirst);
  const usf = await api.project('usf');
  await withLongUrl(page, (url) => url.pathname === `/api/entities/project/${usf.id}`, (body) => {
    const first = (body as { item: { observations: { url: string | null }[] } }).item.observations[0];
    if (first) first.url = LONG_URL;
  });

  await page.goto(`/runs/${run.id}`);
  await expectReadable(page.getByRole('tabpanel', { name: /Messages/ }).getByRole('table'));
  await page.getByRole('tab', { name: 'Fetch log' }).click();
  await expectReadable(page.getByRole('tabpanel', { name: 'Fetch log' }).getByRole('table'));

  await page.goto(`/sources/${COLLECTOR}`);
  await expectReadable(page.getByRole('region', { name: 'Observations' }).getByRole('table'));

  await page.goto(`/projects/${usf.id}`);
  await expectReadable(page.getByRole('region', { name: 'Seen in sources' }).getByRole('table'));
});

test('(p) the provenance popover of a collected value works from the keyboard', async ({ page, api }) => {
  const usf = await api.project('usf');
  await page.goto(`/projects/${usf.id}`);
  const badge = fieldRow(page, 'Description (Ukrainian)').getByRole('button', { name: /^Provenance: collector:/ });
  await badge.focus();
  await page.keyboard.press('Enter');
  const popover = page.getByRole('dialog', { name: /^Provenance: collector:/ });
  await expect(popover).toBeVisible();
  // Focus moves into the (portaled) popover, and Tab goes through its links.
  await expect(popover.getByRole('link', { name: COLLECTOR, exact: true })).toBeFocused();
  await page.keyboard.press('Tab');
  await expect(popover.getByRole('link', { name: /^run run_/ })).toBeFocused();
  await page.keyboard.press('Tab');
  await expect(popover.getByRole('link', { name: 'snapshot 1' })).toBeFocused();
  // Escape closes it and returns to the badge.
  await page.keyboard.press('Escape');
  await expect(popover).toBeHidden();
  await expect(badge).toBeFocused();
});

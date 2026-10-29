// Scenarios (c) and (d) of docs/UI.md §7: an edit with a note shows up in the
// history with author and note; diff and restore with the dry-run preview.
import { ALICE, BOB, expect, test, uniqueSuffix } from './fixtures';
import { fieldInput } from './helpers';

test.describe('without a stored author name', () => {
  test.use({ author: null });

  test('(c) edit a field with a note; the history shows author and note', async ({ page, api }) => {
    const suffix = uniqueSuffix();
    const author = 'E2E Carol';
    const description = `Synthetic description ${suffix}`;
    const note = `Synthetic change note ${suffix}`;

    // First visit: the app asks who you are (docs/UI.md §1.5).
    await page.goto('/projects');
    const who = page.getByRole('dialog', { name: 'Who are you?' });
    await expect(who).toBeVisible();
    await who.getByRole('textbox', { name: 'Or enter your name' }).fill(author);
    await who.getByRole('button', { name: 'Save name' }).click();
    await expect(who).toBeHidden();
    await expect(page.getByRole('button', { name: `Author: ${author}. Change name` })).toBeVisible();

    await page.getByRole('link', { name: 'Open PlayCity', exact: true }).click();
    await expect(page.getByRole('heading', { level: 1, name: 'PlayCity' })).toBeVisible();
    await page.getByRole('button', { name: 'Edit', exact: true }).click();
    await expect(page).toHaveURL(/[?&]edit=1/);

    const saveBar = page.getByRole('region', { name: 'Save changes' });
    await fieldInput(page, 'Description (English)').fill(description);
    await saveBar.getByRole('textbox', { name: 'Change note (optional)' }).fill(note);
    await saveBar.getByRole('button', { name: 'Save', exact: true }).click();
    await expect(saveBar).toBeHidden();
    await expect(page).not.toHaveURL(/[?&]edit=1/);
    await expect(page.getByRole('tabpanel', { name: 'Details' }).getByText(description)).toBeVisible();

    await page.getByRole('tab', { name: 'History' }).click();
    await expect(page).toHaveURL(/[?&]tab=history/);
    const revision = page.getByRole('row').filter({ hasText: note });
    await expect(revision).toHaveCount(1);
    await expect(revision).toContainText(author);
    await expect(revision).toContainText('Description (English)');
    await expect(revision).toContainText('current');

    // The stored revision has the same attribution.
    const project = await api.project('playcity');
    const [newest] = await api.revisions('project', project.id);
    expect(newest).toMatchObject({ author, note, changed_fields: ['description_en'] });
  });
});

test('(d) diff of a revision, compare two versions, restore with the dry-run preview', async ({ page, api }) => {
  const suffix = uniqueSuffix();
  const first = `Synthetic first description ${suffix}`;
  const second = `Synthetic second description ${suffix}`;
  const notes = `Synthetic notes ${suffix}`;
  const project = await api.project('virtual-assets');
  // Two changes by two team members: vA sets the description, vB changes it and adds notes.
  const vA = (await api.patch('project', project.id, { description_en: first }, `Synthetic setup A ${suffix}`, ALICE))
    .version;
  const vB = (
    await api.patch('project', project.id, { description_en: second, notes }, `Synthetic setup B ${suffix}`, BOB)
  ).version;
  const before = vA - 1;

  await page.goto(`/projects/${project.id}?tab=history`);
  // The diff table (Field | Old | → | New) and one field's row in it.
  const diffTable = page
    .getByRole('table')
    .filter({ has: page.getByRole('columnheader', { name: 'Old', exact: true }) });
  const diffRow = (label: string) =>
    diffTable.getByRole('row').filter({ has: page.getByRole('cell', { name: label, exact: true }) });

  // One revision: its stored diff, old → new (word-level for texts).
  await page.getByRole('button', { name: `Show the changes of version ${vB}`, exact: true }).click();
  await expect(page.getByRole('heading', { name: `Changes in v${vB}`, exact: true })).toBeVisible();
  await expect(diffRow('Description (English)').getByRole('deletion')).toContainText('first');
  await expect(diffRow('Description (English)').getByRole('insertion')).toContainText('second');
  await expect(diffRow('Notes').getByRole('insertion')).toContainText(suffix);

  // Compare mode: any two versions, kept in the URL.
  await page.getByRole('switch', { name: 'Compare two versions' }).check();
  await page.getByRole('checkbox', { name: `Compare version ${before}`, exact: true }).check();
  await page.getByRole('checkbox', { name: `Compare version ${vB}`, exact: true }).check();
  await expect(page).toHaveURL(
    (url) => url.searchParams.get('from') === String(before) && url.searchParams.get('to') === String(vB),
  );
  await expect(page.getByRole('heading', { name: `Changes from v${before} to v${vB}`, exact: true })).toBeVisible();
  // Both fields changed between the two versions (vA's change is folded in).
  await expect(diffRow('Description (English)').getByRole('insertion').filter({ hasText: suffix })).toHaveCount(1);
  await expect(diffRow('Notes').getByRole('insertion').filter({ hasText: suffix })).toHaveCount(1);
  await page.getByRole('switch', { name: 'Compare two versions' }).uncheck();
  await expect(page).toHaveURL((url) => !url.searchParams.has('from') && !url.searchParams.has('to'));

  // Restore version vA: the dry run previews every change; restore only the description.
  await page.getByRole('button', { name: `Restore version ${vA}`, exact: true }).click();
  const dialog = page.getByRole('dialog', { name: `Restore version ${vA}`, exact: true });
  await expect(dialog.getByRole('checkbox', { name: 'Restore Description (English)' })).toBeChecked();
  await expect(dialog.getByRole('checkbox', { name: 'Restore Notes' })).toBeChecked();
  const previewRow = dialog
    .getByRole('row')
    .filter({ has: page.getByRole('cell', { name: 'Description (English)', exact: true }) });
  await expect(previewRow.getByRole('deletion')).toContainText('second');
  await expect(previewRow.getByRole('insertion')).toContainText('first');
  // The preview is a dry run: nothing is written yet.
  expect((await api.item('project', project.id)).version).toBe(vB);
  await dialog.getByRole('checkbox', { name: 'Restore Notes' }).uncheck();
  await expect(dialog).toContainText(`Undoes changes by: ${BOB} (1 revision)`);
  await dialog.getByRole('textbox', { name: 'Note' }).fill(`Synthetic restore note ${suffix}`);
  await dialog.getByRole('button', { name: 'Restore', exact: true }).click();
  await expect(dialog).toBeHidden();
  await expect(page.getByText(`Restored 1 field from version ${vA} as version ${vB + 1}.`)).toBeVisible();

  // A new revision (the history is never rewritten): description restored, notes kept.
  const restored = page.getByRole('row').filter({ hasText: `Synthetic restore note ${suffix}` });
  await expect(restored).toContainText(`from v${vA}`);
  await expect(restored).toContainText(ALICE);
  const item = await api.item('project', project.id);
  expect(item.version).toBe(vB + 1);
  expect(item.fields.description_en).toBe(first);
  expect(item.fields.notes).toBe(notes);
});

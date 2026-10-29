// Scenarios (e) and (f) of docs/UI.md §7: concurrent edits never overwrite
// silently (optimistic locking, conflict dialog, frozen base). Alice works in
// the test's own browser context, Bob in a second one.
import { ALICE, BOB, expect, test, uniqueSuffix } from './fixtures';
import { fieldInput } from './helpers';

const CONFLICT_DIALOG = 'Your changes conflict with a newer version';

test('(e) two users edit the same field: the second sees the conflict dialog and resolves it', async ({
  page,
  openContext,
  api,
}) => {
  const suffix = uniqueSuffix();
  const aliceValue = `Synthetic description by Alice ${suffix}`;
  const aliceNote = `Synthetic note by Alice ${suffix}`;
  const bobValue = `Synthetic description by Bob ${suffix}`;
  const project = await api.project('mriia');
  const bobPage = await (await openContext(BOB)).newPage();

  // Both open the edit form on the same version and change the same field.
  await page.goto(`/projects/${project.id}?edit=1`);
  await bobPage.goto(`/projects/${project.id}?edit=1`);
  await fieldInput(page, 'Description (English)').fill(aliceValue);
  await fieldInput(bobPage, 'Description (English)').fill(bobValue);

  const aliceBar = page.getByRole('region', { name: 'Save changes' });
  await aliceBar.getByRole('textbox', { name: 'Change note (optional)' }).fill(aliceNote);
  await aliceBar.getByRole('button', { name: 'Save', exact: true }).click();
  await expect(aliceBar).toBeHidden();

  const bobBar = bobPage.getByRole('region', { name: 'Save changes' });
  await bobBar.getByRole('button', { name: 'Save', exact: true }).click();
  const dialog = bobPage.getByRole('dialog', { name: CONFLICT_DIALOG });
  await expect(dialog).toBeVisible();
  // The intervening revision: Alice's, with her note and the changed field.
  const intervening = dialog.getByRole('listitem').filter({ hasText: aliceNote });
  await expect(intervening).toContainText(ALICE);
  await expect(intervening).toContainText('Description (English)');
  // The conflicting field with theirs and yours; nothing is saved without a choice.
  const field = dialog.getByRole('group', { name: 'Description (English)', exact: true });
  await expect(field).toContainText(aliceValue);
  await expect(field).toContainText(bobValue);
  await expect(dialog.getByRole('button', { name: 'Apply', exact: true })).toBeDisabled();
  await field.getByRole('radio', { name: 'Apply yours' }).check();
  await dialog.getByRole('button', { name: 'Apply', exact: true }).click();
  await expect(dialog).toBeHidden();
  await expect(bobBar).toBeHidden();
  await expect(bobPage.getByRole('tabpanel', { name: 'Details' }).getByText(bobValue)).toBeVisible();

  // Bob's value is current, and Alice's revision stays in the history.
  const item = await api.item('project', project.id);
  expect(item.fields.description_en).toBe(bobValue);
  const [bobRevision, aliceRevision] = await api.revisions('project', project.id);
  expect(bobRevision).toMatchObject({ author: BOB, changed_fields: ['description_en'] });
  expect(aliceRevision).toMatchObject({ author: ALICE, note: aliceNote, changed_fields: ['description_en'] });
});

test('(f) frozen base: the form survives a refetch, saving opens the conflict dialog, the other value survives', async ({
  page,
  openContext,
  api,
}) => {
  const suffix = uniqueSuffix();
  const bobValue = `Synthetic Ukrainian description by Bob ${suffix}`;
  const aliceNotes = `Synthetic notes by Alice ${suffix}`;
  const comment = `Synthetic comment while editing ${suffix}`;
  const project = await api.project('cdto-campus');
  const bobPage = await (await openContext(BOB)).newPage();

  // Bob starts editing (the base is frozen now) and types.
  await bobPage.goto(`/projects/${project.id}?edit=1&comments=open`);
  await fieldInput(bobPage, 'Description (Ukrainian)').fill(bobValue);

  // Alice saves a different field meanwhile.
  await page.goto(`/projects/${project.id}?edit=1`);
  await fieldInput(page, 'Notes').fill(aliceNotes);
  const aliceBar = page.getByRole('region', { name: 'Save changes' });
  await aliceBar.getByRole('button', { name: 'Save', exact: true }).click();
  await expect(aliceBar).toBeHidden();

  // Bob comments on the same page, which invalidates and refetches the record.
  const comments = bobPage.getByRole('complementary', { name: 'Comments' });
  await comments.getByRole('textbox', { name: 'New comment' }).fill(comment);
  await comments.getByRole('button', { name: 'Comment', exact: true }).click();
  await expect(comments.getByRole('article').filter({ hasText: comment })).toBeVisible();
  // The newer version is announced, but the form keeps Bob's base and values.
  await expect(bobPage.getByRole('alert').filter({ hasText: 'saving will open the conflict dialog' })).toContainText(
    `Changed by ${ALICE}`,
  );
  await expect(fieldInput(bobPage, 'Description (Ukrainian)')).toHaveValue(bobValue);
  await expect(fieldInput(bobPage, 'Notes')).not.toHaveValue(aliceNotes);

  await bobPage
    .getByRole('region', { name: 'Save changes' })
    .getByRole('button', { name: 'Save', exact: true })
    .click();
  const dialog = bobPage.getByRole('dialog', { name: CONFLICT_DIALOG });
  await expect(dialog).toBeVisible();
  await expect(dialog.getByRole('listitem').filter({ hasText: ALICE })).toContainText('Notes');
  // Different fields: nothing to choose. Bob's field is applied, Alice's kept.
  await expect(dialog.getByRole('heading', { name: 'Changed only by you — will be applied' })).toBeVisible();
  await expect(dialog.getByRole('heading', { name: 'Changed only by them — kept' })).toBeVisible();
  await dialog.getByRole('button', { name: 'Apply', exact: true }).click();
  await expect(dialog).toBeHidden();
  await expect(bobPage.getByRole('region', { name: 'Save changes' })).toBeHidden();

  const item = await api.item('project', project.id);
  expect(item.fields.notes).toBe(aliceNotes);
  expect(item.fields.description_uk).toBe(bobValue);
});

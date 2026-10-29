// Scenarios (e) and (f) of docs/UI.md §7: concurrent edits never overwrite
// silently (optimistic locking, conflict dialog, frozen base). Alice works in
// the test's own browser context, Bob in a second one or through the API.
import { ALICE, BOB, expect, test, uniqueSuffix } from './fixtures';
import { fieldInput } from './helpers';

const CONFLICT_DIALOG = 'Your changes conflict with a newer version';

interface CommentBody {
  comment: { id: string; version: number; body_md: string };
}

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

test('(f) frozen base of a comment edit: a refetch during editing leads to the two-way dialog, not an overwrite', async ({
  page,
  api,
}) => {
  const suffix = uniqueSuffix();
  const original = `Synthetic original comment ${suffix}`;
  const bobText = `Synthetic correction by Bob ${suffix}`;
  const aliceText = `Synthetic edit by Alice ${suffix}`;
  const otherText = `Synthetic second comment ${suffix}`;
  const project = await api.project('diia-center');
  const created = await api.write<CommentBody>(
    'POST',
    '/api/comments',
    { subject_id: project.id, field: null, parent_id: null, body_md: original },
    BOB,
  );
  const commentPath = `/api/comments/${created.comment.id}`;

  // Alice starts editing Bob's comment (the editor freezes its base) and types.
  await page.goto(`/projects/${project.id}?comments=open`);
  const panel = page.getByRole('complementary', { name: 'Comments' });
  const thread = panel.getByRole('article', { name: `Thread by ${BOB}` });
  await expect(thread).toContainText(original);
  await thread.getByRole('button', { name: 'Edit comment' }).click();
  await thread.getByRole('textbox', { name: 'Edit comment' }).fill(aliceText);

  // Bob corrects his comment meanwhile.
  await api.write('PATCH', commentPath, { expected_version: 1, body_md: bobText, note: null }, BOB);

  // Alice posts another comment in the same panel, which refetches the threads.
  await panel.getByRole('textbox', { name: 'New comment' }).fill(otherText);
  await panel.getByRole('button', { name: 'Comment', exact: true }).click();
  await expect(panel.getByRole('article').filter({ hasText: otherText })).toBeVisible();
  // The editor announces Bob's newer version and keeps Alice's text.
  await expect(thread.getByRole('alert').filter({ hasText: 'saving will open the conflict dialog' })).toContainText(
    `Changed by ${BOB}`,
  );
  await expect(thread.getByRole('textbox', { name: 'Edit comment' })).toHaveValue(aliceText);

  await thread.getByRole('button', { name: 'Save', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: 'The comment was changed meanwhile' });
  await expect(dialog).toBeVisible();
  await expect(dialog.getByRole('listitem')).toContainText(BOB);
  // Nothing is written before the confirmation: Bob's text is current.
  expect((await api.get<CommentBody>(commentPath)).comment).toMatchObject({ body_md: bobText, version: 2 });

  await dialog.getByRole('button', { name: 'Save my version' }).click();
  await expect(dialog).toBeHidden();
  await expect(thread).toContainText(aliceText);
  expect((await api.get<CommentBody>(commentPath)).comment).toMatchObject({ body_md: aliceText, version: 3 });
  // Bob's correction stays in the comment's history.
  const revisions = await api.get<{ items: { version: number; author: string }[] }>(`${commentPath}/revisions`);
  expect(revisions.items.map((revision) => [revision.version, revision.author])).toEqual([
    [3, ALICE],
    [2, BOB],
    [1, BOB],
  ]);
});

interface FieldMetaBody {
  item: { version: number; field_meta: Record<string, { verified: string; evidence_id: string | null } | undefined> };
}

test('(e) verification: a colleague\'s dispute meanwhile leads to the question with the reason, not a silent re-verification', async ({
  page,
  api,
}) => {
  const suffix = uniqueSuffix();
  const quote = `Synthetic quote ${suffix}`;
  const reason = `Synthetic reason by Bob ${suffix}`;
  const project = await api.project('digital-state-ua');
  await api.write(
    'POST',
    '/api/entities/evidence',
    { data: { subject_id: project.id, target: 'field:name_en', url: 'https://example.org/synthetic-evidence', quote } },
    ALICE,
  );

  // Alice's page shows the field unverified.
  await page.goto(`/projects/${project.id}`);
  const dot = page.getByRole('button', { name: /^Verification of Name \(English\): Unverified/ });
  await expect(dot).toBeVisible();

  // Bob disputes the field meanwhile, with a reason; Alice's page does not refetch.
  const before = (await api.get<FieldMetaBody>(`/api/entities/project/${project.id}`)).item;
  await api.write(
    'POST',
    `/api/entities/project/${project.id}/verify-field`,
    { expected_version: before.version, field: 'name_en', status: 'disputed', note: reason },
    BOB,
  );

  await dot.click();
  await page.getByRole('menuitem', { name: new RegExp(quote) }).click();
  const dialog = page.getByRole('dialog', { name: 'The record changed meanwhile' });
  await expect(dialog).toContainText(`The verification of Name (English) was changed by ${BOB}`);
  await expect(dialog).toContainText('Disputed');
  await expect(dialog).toContainText(reason);
  // Nothing was retried: Bob's dispute stands until Alice decides.
  expect((await api.get<FieldMetaBody>(`/api/entities/project/${project.id}`)).item.field_meta.name_en?.verified).toBe(
    'disputed',
  );
  await dialog.getByRole('button', { name: 'Cancel' }).click();
  await expect(dialog).toBeHidden();
  expect((await api.get<FieldMetaBody>(`/api/entities/project/${project.id}`)).item.field_meta.name_en?.verified).toBe(
    'disputed',
  );
});

test('(e) add evidence: a value changed while the quote was copied is asked about before anything is stored', async ({
  page,
  api,
}) => {
  const suffix = uniqueSuffix();
  const original = `Synthetic description ${suffix}`;
  const changed = `Synthetic description changed by Bob ${suffix}`;
  const project = await api.project('united24-media');
  await api.patch('project', project.id, { description_en: original }, `Synthetic setup ${suffix}`, ALICE);

  await page.goto(`/projects/${project.id}`);
  await page.getByRole('button', { name: /^Verification of Description \(English\)/ }).click();
  await page.getByRole('menuitem', { name: 'Add evidence…' }).click();
  const dialog = page.getByRole('dialog', { name: 'Add evidence · Description (English)' });
  await expect(dialog.getByRole('group', { name: 'The value this evidence supports' })).toContainText(original);
  await fieldInput(dialog, 'URL').fill('https://example.org/synthetic-source');
  await fieldInput(dialog, 'Quote').fill(original);

  // Bob changes the description while Alice copies the quote.
  await api.patch('project', project.id, { description_en: changed }, null, BOB);
  await dialog.getByRole('button', { name: 'Add evidence and mark verified' }).click();

  const question = dialog.getByRole('alert').filter({ hasText: 'The value changed meanwhile' });
  await expect(question).toContainText(BOB);
  await expect(question).toContainText(changed);
  // No evidence row was stored with a value its quote does not support.
  const evidence = await api.get<{ total: number }>(`/api/entities/evidence?f.subject_id=in:${project.id}`);
  expect(evidence.total).toBe(0);
  await question.getByRole('button', { name: 'Cancel' }).click();
  await expect(dialog).toBeHidden();
  const item = (await api.get<FieldMetaBody>(`/api/entities/project/${project.id}`)).item;
  expect(item.field_meta.description_en?.verified ?? 'unverified').toBe('unverified');
});

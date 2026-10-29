// Scenario (g) of docs/UI.md §7: a comment thread from creation to undelete,
// and the "Open comments" quick filter of the projects table.
import { expect, test, uniqueSuffix } from './fixtures';
import { clickLabel, expectSearch, tableRows } from './helpers';

test('(g) comment thread: create, reply, resolve, delete and undelete; the open comments quick filter', async ({
  page,
  api,
}) => {
  const suffix = uniqueSuffix();
  const rootText = `Synthetic thread ${suffix}`;
  const replyText = `Synthetic reply ${suffix}`;
  const project = await api.project('diia-education');
  const projectLink = page.getByRole('table').getByRole('link', { name: `Open ${project.label}`, exact: true });

  await page.goto(`/projects/${project.id}`);
  await page.getByRole('button', { name: /^Comments( \(\d+ open\))?$/ }).click();
  await expect(page).toHaveURL(/[?&]comments=open/);
  const panel = page.getByRole('complementary', { name: 'Comments' });

  // Create: Markdown, rendered by the server.
  await panel.getByRole('textbox', { name: 'New comment', exact: true }).fill(`Synthetic **thread** ${suffix}`);
  await panel.getByRole('button', { name: 'Comment', exact: true }).click();
  const thread = panel.getByRole('article').filter({ hasText: rootText });
  await expect(thread).toBeVisible();
  await expect(thread.getByRole('strong')).toHaveText('thread');
  await expect(thread.getByText('open', { exact: true })).toBeVisible();

  // Reply.
  await thread.getByRole('button', { name: 'Reply to thread' }).click();
  await thread.getByRole('textbox', { name: 'Reply', exact: true }).fill(replyText);
  await thread.getByRole('button', { name: 'Reply', exact: true }).click();
  await expect(thread).toContainText(replyText);
  await expect(page.getByRole('button', { name: 'Comments (1 open)' })).toBeVisible();

  // The quick filter "Open comments" lists the project now.
  await page.goto('/projects');
  await clickLabel(page, 'Open comments');
  await expectSearch(page, { 'f.open_comments': 'range:1..' });
  await expect(page.getByRole('checkbox', { name: 'Open comments' })).toBeChecked();
  // Wait for the filtered rows, not the 20 rows shown while they load.
  await expect(tableRows(page)).not.toHaveCount(20);
  await expect(projectLink).toBeVisible();

  // Resolve: the panel lists open threads by default, so the thread leaves the list.
  await page.goto(`/projects/${project.id}?comments=open`);
  await thread.getByRole('button', { name: 'Resolve thread' }).click();
  await expect(thread).toBeHidden();
  await clickLabel(panel.getByRole('radiogroup', { name: 'Status' }), 'All');
  await expect(thread).toContainText('Resolved at');
  await expect(thread.getByRole('button', { name: 'Reopen thread' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Comments', exact: true })).toBeVisible();

  // ... and the quick filter no longer lists the project.
  await page.goto('/projects?f.open_comments=range:1..');
  await expect(page.getByRole('checkbox', { name: 'Open comments' })).toBeChecked();
  await expect(page.getByText(/^\d+ rows?$/)).toBeVisible();
  await expect(projectLink).toHaveCount(0);

  // Delete the thread (soft delete): hidden unless "Show deleted" is on.
  await page.goto(`/projects/${project.id}?comments=open`);
  await clickLabel(panel.getByRole('radiogroup', { name: 'Status' }), 'All');
  await thread.getByRole('button', { name: 'Delete comment' }).first().click();
  const deleteDialog = page.getByRole('dialog', { name: 'Delete comment' });
  await expect(deleteDialog).toContainText('Delete this thread?');
  await deleteDialog.getByRole('button', { name: 'Delete', exact: true }).click();
  await expect(deleteDialog).toBeHidden();
  await expect(thread).toBeHidden();

  // Undelete: the thread comes back with its reply.
  await panel.getByRole('switch', { name: 'Show deleted' }).check();
  await expect(thread).toContainText('Deleted at');
  await thread.getByRole('button', { name: 'Undelete comment' }).click();
  const undeleteDialog = page.getByRole('dialog', { name: 'Undelete comment' });
  await undeleteDialog.getByRole('button', { name: 'Undelete', exact: true }).click();
  await expect(undeleteDialog).toBeHidden();
  await expect(thread.getByRole('button', { name: 'Undelete comment' })).toHaveCount(0);
  await panel.getByRole('switch', { name: 'Show deleted' }).uncheck();
  await expect(thread).toBeVisible();
  await expect(thread).toContainText(replyText);
  await expect(thread.getByRole('button', { name: 'Reopen thread' })).toBeVisible();
});

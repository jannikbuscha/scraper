// Scenarios (a) and (b) of docs/UI.md §7: the projects table, its filters and
// its sorting. Expected orders follow the seed (seed/projects.yaml) and the
// sort rules of docs/API.md §4.2: case-insensitive, Latin before Cyrillic in
// Ukrainian alphabetical order, empty values last in both directions, ties by
// ID (IDs grow in seed order).
import { ALICE, expect, test } from './fixtures';
import { columnHeader, expectRowLabels, expectSearch, openFilter, sortButton, tableRows } from './helpers';

const NAME_EN_ASC = [
  'Brave1',
  'CDTO Campus',
  'CodeUA',
  'Digital State UA',
  'Diia',
  'Diia.Business',
  'Diia.Center',
  'Diia.City',
  'Diia.Digital Community',
  'Diia.Education',
  'Diia.Engine',
  'European Integration',
  'Mriia',
  'PlayCity',
  'Ukrainian Startup Fund',
  'UNITED24',
  'UNITED24 Media',
  'uResidency',
  'Virtual Assets',
  'WINWIN',
];

/** Projects with a Ukrainian name, by name_uk: Віртуальні активи, Дія, Дія.City, … */
const WITH_NAME_UK_ASC = [
  'Virtual Assets',
  'Diia',
  'Diia.City',
  'Diia.Engine',
  'Diia.Business',
  'Diia.Education',
  'Diia.Center',
  'Diia.Digital Community',
  'European Integration',
  'Mriia',
  'Ukrainian Startup Fund',
];
/** Projects without a Ukrainian name: last in both directions, in seed order. */
const WITHOUT_NAME_UK = [
  'uResidency',
  'CodeUA',
  'CDTO Campus',
  'Brave1',
  'WINWIN',
  'UNITED24',
  'UNITED24 Media',
  'PlayCity',
  'Digital State UA',
];

test('(a) the projects table shows the 20 seeded projects', async ({ page }) => {
  await page.goto('/projects');
  await expect(page.getByRole('heading', { level: 1, name: 'Projects' })).toBeVisible();
  await expect(page.getByText('20 rows', { exact: true })).toBeVisible();
  await expect(tableRows(page)).toHaveCount(20);
  // European Integration, out of the paper's scope, is listed too.
  await expect(tableRows(page).filter({ hasText: 'Євроінтеграція' })).toHaveCount(1);
});

test('(b) sorting by name_en and name_uk gives the exact expected order', async ({ page }) => {
  await page.goto('/projects');
  await expect(tableRows(page)).toHaveCount(20);

  await sortButton(page, 'Name (English)').click();
  await expectSearch(page, { sort: 'name_en' });
  await expect(columnHeader(page, 'Name (English)')).toHaveAttribute('aria-sort', 'ascending');
  await expectRowLabels(page, NAME_EN_ASC);

  await sortButton(page, 'Name (English)').click();
  await expectSearch(page, { sort: '-name_en' });
  await expect(columnHeader(page, 'Name (English)')).toHaveAttribute('aria-sort', 'descending');
  await expectRowLabels(page, [...NAME_EN_ASC].reverse());

  await sortButton(page, 'Name (Ukrainian)').click();
  await expectSearch(page, { sort: 'name_uk' });
  await expect(columnHeader(page, 'Name (Ukrainian)')).toHaveAttribute('aria-sort', 'ascending');
  await expect(columnHeader(page, 'Name (English)')).toHaveAttribute('aria-sort', 'none');
  await expectRowLabels(page, [...WITH_NAME_UK_ASC, ...WITHOUT_NAME_UK]);
  await expect(tableRows(page).first()).toContainText('Віртуальні активи');

  await sortButton(page, 'Name (Ukrainian)').click();
  await expectSearch(page, { sort: '-name_uk' });
  await expect(columnHeader(page, 'Name (Ukrainian)')).toHaveAttribute('aria-sort', 'descending');
  await expectRowLabels(page, [...[...WITH_NAME_UK_ASC].reverse(), ...WITHOUT_NAME_UK]);
  await expect(tableRows(page).first()).toContainText('Український фонд стартапів');

  // A reload keeps the sort.
  await page.reload();
  await expectSearch(page, { sort: '-name_uk' });
  await expect(columnHeader(page, 'Name (Ukrainian)')).toHaveAttribute('aria-sort', 'descending');
  await expectRowLabels(page, [...[...WITH_NAME_UK_ASC].reverse(), ...WITHOUT_NAME_UK]);
});

test('(b) filter by paper cluster, sort by policy domains and verification status', async ({ page, api }) => {
  // Synthetic values on the four projects of one cluster, so that both sorts
  // have something to order (the seed leaves these fields empty/unverified).
  const note = 'Synthetic E2E setup for the sort scenario';
  const setup: [string, Record<string, string | string[]>][] = [
    ['diia-city', { policy_domains: ['economic_affairs', 'defence'], verification_status: 'disputed' }],
    ['diia-business', { policy_domains: ['general_public_services'], verification_status: 'unverified' }],
    ['uresidency', { policy_domains: [], verification_status: 'verified' }],
    ['codeua', { policy_domains: ['health'], verification_status: 'verified' }],
  ];
  for (const [slug, changes] of setup) {
    const project = await api.project(slug);
    await api.patch('project', project.id, changes, note, ALICE);
  }

  await page.goto('/projects');
  const form = await openFilter(page, 'Paper cluster');
  await form.getByRole('checkbox', { name: 'Business & economic development (4 rows)' }).check();
  await form.getByRole('button', { name: 'Apply' }).click();
  await expectSearch(page, { 'f.paper_cluster': 'in:business_economic_development' });
  await expect(page.getByRole('button', { name: 'Filter Paper cluster (active)' })).toBeVisible();
  // The default sort: paper cluster, then name_en.
  await expectRowLabels(page, ['CodeUA', 'Diia.Business', 'Diia.City', 'uResidency']);

  // vocab_list fields sort by their first (main) value's sort order; empty lists last.
  await sortButton(page, 'Policy domains').click();
  await expectSearch(page, { 'f.paper_cluster': 'in:business_economic_development', sort: 'policy_domains' });
  await expect(columnHeader(page, 'Policy domains')).toHaveAttribute('aria-sort', 'ascending');
  await expectRowLabels(page, ['Diia.Business', 'Diia.City', 'CodeUA', 'uResidency']);

  await sortButton(page, 'Policy domains').click();
  await expectSearch(page, { 'f.paper_cluster': 'in:business_economic_development', sort: '-policy_domains' });
  await expect(columnHeader(page, 'Policy domains')).toHaveAttribute('aria-sort', 'descending');
  await expectRowLabels(page, ['CodeUA', 'Diia.City', 'Diia.Business', 'uResidency']);

  // vocab fields sort by the term's sort order: unverified, verified, disputed.
  await sortButton(page, 'Verification status').click();
  await expectSearch(page, { 'f.paper_cluster': 'in:business_economic_development', sort: 'verification_status' });
  await expect(columnHeader(page, 'Verification status')).toHaveAttribute('aria-sort', 'ascending');
  await expectRowLabels(page, ['Diia.Business', 'uResidency', 'CodeUA', 'Diia.City']);

  await sortButton(page, 'Verification status').click();
  const state = { 'f.paper_cluster': 'in:business_economic_development', sort: '-verification_status' };
  await expectSearch(page, state);
  await expect(columnHeader(page, 'Verification status')).toHaveAttribute('aria-sort', 'descending');
  await expectRowLabels(page, ['Diia.City', 'uResidency', 'CodeUA', 'Diia.Business']);

  // A reload keeps filter and sort.
  await page.reload();
  await expectSearch(page, state);
  await expect(page.getByRole('button', { name: 'Filter Paper cluster (active)' })).toBeVisible();
  await expect(columnHeader(page, 'Verification status')).toHaveAttribute('aria-sort', 'descending');
  await expectRowLabels(page, ['Diia.City', 'uResidency', 'CodeUA', 'Diia.Business']);
});

test('(b) a contains filter on name_uk with Cyrillic text survives a reload', async ({ page }) => {
  await page.goto('/projects');
  const form = await openFilter(page, 'Name (Ukrainian)');
  await expect(form.getByRole('combobox', { name: 'Condition' })).toHaveValue('contains');
  await form.getByRole('textbox', { name: 'Text' }).fill('дія');
  await form.getByRole('button', { name: 'Apply' }).click();

  await expectSearch(page, { 'f.name_uk': 'contains:дія' });
  // Case-insensitive: "дія" matches "Дія…"; default sort: paper cluster, then name_en.
  const matches = [
    'Diia',
    'Diia.Center',
    'Diia.Engine',
    'Diia.Business',
    'Diia.City',
    'Diia.Education',
    'Diia.Digital Community',
  ];
  await expect(page.getByText('7 rows', { exact: true })).toBeVisible();
  await expectRowLabels(page, matches);

  await page.reload();
  await expectSearch(page, { 'f.name_uk': 'contains:дія' });
  await expect(page.getByRole('button', { name: 'Filter Name (Ukrainian) (active)' })).toBeVisible();
  await expectRowLabels(page, matches);
});

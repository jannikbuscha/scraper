import { describe, expect, it } from 'vitest';

import {
  activeFilters,
  canonicalQuery,
  chipValues,
  clearFilters,
  clickSort,
  cycleSort,
  EMPTY_TOKEN,
  exportQueryString,
  facetQueryString,
  formatDateRangeFilter,
  formatMultiselectFilter,
  formatNumberRangeFilter,
  formatRefFilter,
  formatTextFilter,
  getColumns,
  getDeletedMode,
  getPage,
  getPageSize,
  isQueryActive,
  listQueryString,
  parseBoolFilter,
  parseDateRangeFilter,
  parseFilter,
  parseMultiselectFilter,
  parseNumberRangeFilter,
  parseRefFilter,
  parseSearch,
  parseSort,
  parseTextFilter,
  periodPresets,
  searchFromQuery,
  setChipValues,
  setFilter,
  stringifySearch,
  toggleQuery,
  validateSearch,
  withColumns,
  withDeletedMode,
  withPage,
  withPageSize,
  withQuery,
} from './query-string';

/** What a reload does: serialise to the URL and parse it back. */
const roundTrip = (search: Record<string, string>) => parseSearch(stringifySearch(search));

describe('router search serialisation', () => {
  it('sorts keys canonically and drops empty values', () => {
    expect(stringifySearch({ sort: 'name_en', 'f.status': 'in:active', q: '', page: undefined })).toBe(
      '?f.status=in%3Aactive&sort=name_en',
    );
    expect(stringifySearch({})).toBe('');
  });

  it('round-trips Cyrillic values', () => {
    const search = { 'f.name_uk': 'contains:Дія.Бізнес', q: 'Мінцифри запустили' };
    expect(roundTrip(search)).toEqual(search);
  });

  it('round-trips commas, colons, ampersands and plus signs in text values', () => {
    const search = { 'f.description_en': 'contains:a, b: c & d + e=f' };
    expect(roundTrip(search)).toEqual(search);
    expect(parseTextFilter(roundTrip(search)['f.description_en'])).toEqual({
      op: 'contains',
      text: 'a, b: c & d + e=f',
    });
  });

  it('round-trips the ~empty token and chips', () => {
    const search = { 'f.wartime_relevance': `in:direct,${EMPTY_TOKEN}`, 'f.period': 'in:pre_invasion,full_scale_war' };
    expect(roundTrip(search)).toEqual(search);
  });

  it('passes every key through validateSearch, stringifying scalars', () => {
    expect(validateSearch({ 'f.kind': 'in:media', page: 2, edit: true, nested: { a: 1 } })).toEqual({
      'f.kind': 'in:media',
      page: '2',
      edit: 'true',
    });
  });
});

describe('canonical query strings', () => {
  const search = {
    sort: '-launch',
    'f.kind': 'in:e_service',
    cols: 'name_en,kind',
    page: '2',
    page_size: '100',
    q: 'Дія',
    tab: 'history',
    thread: 'cmt_1',
  };

  it('is order independent', () => {
    const reversed = Object.fromEntries(Object.entries(search).reverse());
    expect(canonicalQuery(reversed)).toBe(canonicalQuery(search));
  });

  it('builds the list key without cols and detail-page parameters', () => {
    expect(listQueryString(search)).toBe('f.kind=in%3Ae_service&page=2&page_size=100&q=%D0%94%D1%96%D1%8F&sort=-launch');
  });

  it('builds the facet key without the own filter, paging and sort', () => {
    expect(facetQueryString(search, 'kind')).toBe('q=%D0%94%D1%96%D1%8F');
    expect(facetQueryString({ ...search, 'f.status': 'in:active' }, 'kind')).toBe(
      'f.status=in%3Aactive&q=%D0%94%D1%96%D1%8F',
    );
  });

  it('builds the export query with cols and format but without paging', () => {
    expect(exportQueryString(search, 'xlsx')).toBe(
      'cols=name_en%2Ckind&f.kind=in%3Ae_service&format=xlsx&q=%D0%94%D1%96%D1%8F&sort=-launch',
    );
  });

  it('applies a saved view query as search params', () => {
    const query = canonicalQuery({ 'f.name_uk': 'contains:дія, і', sort: 'name_uk' });
    expect(searchFromQuery(query)).toEqual({ 'f.name_uk': 'contains:дія, і', sort: 'name_uk' });
  });
});

describe('field filters', () => {
  it('splits operator and value at the first colon only', () => {
    expect(parseFilter('contains:a:b,c')).toEqual({ op: 'contains', value: 'a:b,c' });
    expect(parseFilter('nocolon')).toBeNull();
    expect(parseFilter(undefined)).toBeNull();
  });

  it('sets a filter, replacing the old one and returning to page 1', () => {
    const next = setFilter({ 'f.kind': 'in:media', page: '3', sort: 'name_en' }, 'kind', 'nin:other');
    expect(next).toEqual({ 'f.kind': 'nin:other', sort: 'name_en' });
    expect(setFilter(next, 'kind', null)).toEqual({ sort: 'name_en' });
  });

  it('lists and clears active filters together with q and the deleted mode', () => {
    const search = {
      'f.b': 'eq:true',
      'f.a': 'in:x',
      q: 'text',
      deleted: 'include',
      sort: 'relevance,name_en',
      page_size: '25',
    };
    expect(activeFilters(search)).toEqual([
      ['a', 'in:x'],
      ['b', 'eq:true'],
    ]);
    expect(clearFilters(search)).toEqual({ sort: 'name_en', page_size: '25' });
  });

  it('parses and formats text filters', () => {
    expect(parseTextFilter('eq:Дія')).toEqual({ op: 'eq', text: 'Дія' });
    expect(parseTextFilter('empty:false')).toEqual({ op: 'empty', empty: false });
    expect(parseTextFilter('like:x')).toBeNull();
    expect(formatTextFilter({ op: 'contains', text: 'дія' })).toBe('contains:дія');
    expect(formatTextFilter({ op: 'contains', text: '' })).toBeNull();
    expect(formatTextFilter({ op: 'empty', empty: true })).toBe('empty:true');
  });

  it('parses multiselect filters for scalar and list fields', () => {
    expect(parseMultiselectFilter(`in:direct,${EMPTY_TOKEN}`, false)).toEqual({
      op: 'in',
      values: ['direct', EMPTY_TOKEN],
    });
    expect(parseMultiselectFilter('all:app,web', true)).toEqual({ op: 'all', values: ['app', 'web'] });
    expect(parseMultiselectFilter('any:app', false)).toBeNull();
    expect(parseMultiselectFilter('empty:true', false)).toEqual({ op: 'in', values: [EMPTY_TOKEN] });
    expect(parseMultiselectFilter('empty:false', true)).toEqual({ op: 'none', values: [EMPTY_TOKEN] });
  });

  it('formats multiselect filters; `all` never carries ~empty', () => {
    expect(formatMultiselectFilter({ op: 'none', values: ['app', EMPTY_TOKEN] })).toBe(`none:app,${EMPTY_TOKEN}`);
    expect(formatMultiselectFilter({ op: 'all', values: ['app', EMPTY_TOKEN] })).toBe('all:app');
    expect(formatMultiselectFilter({ op: 'all', values: [EMPTY_TOKEN] })).toBeNull();
    expect(formatMultiselectFilter({ op: 'in', values: [] })).toBeNull();
  });

  it('parses and formats date ranges with open bounds', () => {
    expect(parseDateRangeFilter('overlaps:2022-02-24..')).toEqual({ op: 'overlaps', from: '2022-02-24', to: '' });
    expect(parseDateRangeFilter('within:..2019-08-28')).toEqual({ op: 'within', from: '', to: '2019-08-28' });
    expect(parseDateRangeFilter('empty:true')).toEqual({ op: 'empty', empty: true });
    expect(parseDateRangeFilter('range:2020..2021')).toBeNull();
    expect(formatDateRangeFilter({ op: 'within', from: '2020-01-01', to: '' })).toBe('within:2020-01-01..');
    expect(formatDateRangeFilter({ op: 'overlaps', from: '', to: '' })).toBeNull();
  });

  it('parses bool, number range and ref filters', () => {
    expect(parseBoolFilter('eq:true')).toBe(true);
    expect(parseBoolFilter('eq:yes')).toBeNull();
    expect(parseNumberRangeFilter('range:1..')).toEqual({ min: 1, max: null });
    expect(parseNumberRangeFilter('eq:3')).toEqual({ min: 3, max: 3 });
    expect(formatNumberRangeFilter({ min: null, max: 10 })).toBe('range:..10');
    expect(formatNumberRangeFilter({ min: null, max: null })).toBeNull();
    expect(parseRefFilter('in:prj_1,prj_2')).toEqual({ op: 'in', ids: ['prj_1', 'prj_2'] });
    expect(parseRefFilter('empty:true')).toEqual({ op: 'in', ids: [EMPTY_TOKEN] });
    expect(formatRefFilter({ op: 'confirmed', ids: ['prj_1', EMPTY_TOKEN] })).toBe('confirmed:prj_1');
    expect(formatRefFilter({ op: 'in', ids: [EMPTY_TOKEN] })).toBe(`in:${EMPTY_TOKEN}`);
  });
});

describe('quick filters', () => {
  const unverified = 'f.verification_status=in:unverified';

  it('is active only for the exact key/value pair', () => {
    expect(isQueryActive({ 'f.verification_status': 'in:unverified' }, unverified)).toBe(true);
    expect(isQueryActive({ 'f.verification_status': 'in:unverified,disputed' }, unverified)).toBe(false);
    expect(isQueryActive({}, unverified)).toBe(false);
  });

  it('activating replaces the field filter; deactivating removes it', () => {
    const on = toggleQuery({ 'f.verification_status': 'in:verified', page: '2', q: 'x' }, unverified);
    expect(on).toEqual({ 'f.verification_status': 'in:unverified', q: 'x' });
    expect(toggleQuery(on, unverified)).toEqual({ q: 'x' });
  });

  it('reads and writes period chips in vocabulary order', () => {
    const order = ['pre_ministry', 'pre_invasion', 'full_scale_war', 'unknown'];
    const next = setChipValues({}, 'period', ['unknown', 'pre_invasion'], order);
    expect(next).toEqual({ 'f.period': 'in:pre_invasion,unknown' });
    expect(chipValues(next, 'period')).toEqual(['pre_invasion', 'unknown']);
    expect(chipValues({ 'f.period': 'nin:unknown' }, 'period')).toEqual([]);
    expect(setChipValues(next, 'period', [], order)).toEqual({});
  });

  it('generates mutually exclusive period presets from the cut-off dates', () => {
    const presets = periodPresets(
      'date',
      { ministry_founded: '2019-08-29', full_scale_invasion: '2022-02-24' },
      (period) => period.toUpperCase(),
    );
    expect(presets.map((preset) => searchFromQuery(preset.query))).toEqual([
      { 'f.date': 'within:..2019-08-28' },
      { 'f.date': 'within:2019-08-29..2022-02-23' },
      { 'f.date': 'within:2022-02-24..' },
    ]);
    expect(presets[0]?.label).toBe('PRE_MINISTRY');
  });
});

describe('sorting', () => {
  it('parses and cycles a single column asc → desc → none', () => {
    expect(parseSort('paper_cluster,-name_en')).toEqual([
      { field: 'paper_cluster', desc: false },
      { field: 'name_en', desc: true },
    ]);
    const asc = cycleSort([], 'name_en', false);
    expect(asc).toEqual([{ field: 'name_en', desc: false }]);
    const desc = cycleSort(asc, 'name_en', false);
    expect(desc).toEqual([{ field: 'name_en', desc: true }]);
    expect(cycleSort(desc, 'name_en', false)).toEqual([]);
  });

  it('a plain click on a column of a multi-sort starts a fresh ascending sort', () => {
    const multi = parseSort('paper_cluster,-name_en');
    expect(cycleSort(multi, 'name_en', false)).toEqual([{ field: 'name_en', desc: false }]);
  });

  it('shift-click adds up to three columns and cycles within the multi-sort', () => {
    let terms = cycleSort([], 'a', true);
    terms = cycleSort(terms, 'b', true);
    terms = cycleSort(terms, 'c', true);
    expect(cycleSort(terms, 'd', true)).toEqual(terms);
    terms = cycleSort(terms, 'b', true);
    expect(terms[1]).toEqual({ field: 'b', desc: true });
    expect(cycleSort(terms, 'b', true).map((t) => t.field)).toEqual(['a', 'c']);
  });

  it('cannot get stuck on a descending default sort', () => {
    let search: Record<string, string> = {};
    search = clickSort(search, '-date', 'date', false);
    expect(search.sort).toBe('date');
    search = clickSort(search, '-date', 'date', false);
    expect(search.sort).toBe('-date');
    search = clickSort(search, '-date', 'date', false);
    expect(search.sort).toBeUndefined();
  });

  it('shift-click extends the default sort', () => {
    expect(clickSort({ page: '4' }, 'paper_cluster,name_en', 'status', true)).toEqual({
      sort: 'paper_cluster,name_en,status',
    });
  });
});

describe('q, paging and columns', () => {
  it('drops a relevance sort when q is cleared', () => {
    expect(withQuery({ q: 'Дія', sort: 'relevance', page: '2' }, '  ')).toEqual({});
    expect(withQuery({}, ' Мрія ')).toEqual({ q: 'Мрія' });
  });

  it('reads and writes paging', () => {
    expect(getPage({ page: '3' })).toBe(3);
    expect(getPage({ page: '0' })).toBe(1);
    expect(getPage({ page: 'x' })).toBe(1);
    expect(getPageSize({})).toBe(50);
    expect(withPage({ page: '3' }, 1)).toEqual({});
    expect(withPageSize({ page: '3' }, 100)).toEqual({ page_size: '100' });
    expect(withPageSize({ page_size: '100' }, 50)).toEqual({});
  });

  it('reads and writes the deleted mode', () => {
    expect(getDeletedMode({ deleted: 'only' })).toBe('only');
    expect(getDeletedMode({ deleted: 'bogus' })).toBe('exclude');
    expect(withDeletedMode({ deleted: 'only', page: '2' }, 'exclude')).toEqual({});
    expect(withDeletedMode({}, 'include')).toEqual({ deleted: 'include' });
  });

  it('reads cols in URL order and stores only non-default choices', () => {
    const known = ['slug', 'name_en', 'kind', 'status'];
    const defaults = ['slug', 'name_en'];
    expect(getColumns({}, known, defaults)).toEqual(defaults);
    expect(getColumns({ cols: 'kind,unknown,slug' }, known, defaults)).toEqual(['kind', 'slug']);
    expect(withColumns({ cols: 'kind' }, defaults, defaults)).toEqual({});
    expect(withColumns({}, ['slug', 'kind'], defaults)).toEqual({ cols: 'slug,kind' });
  });
});

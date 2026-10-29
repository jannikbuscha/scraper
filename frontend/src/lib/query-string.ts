// The table's query string is the API query string (docs/UI.md §1.2,
// docs/API.md §4). These helpers read and write it as a flat record of
// strings; every writer returns a new record and never mutates its input.
import type { DeletedMode, QuickFilterPresetOption } from '../api/types';
import { addDays } from './partial-date';

export type SearchRecord = Record<string, string>;

// ---------------------------------------------------------------------------
// Router serialisation: exactly the functions of docs/UI.md §1.2.
// ---------------------------------------------------------------------------

export const parseSearch = (s: string): SearchRecord => Object.fromEntries(new URLSearchParams(s));

export const stringifySearch = (o: Record<string, unknown>): string => {
  const p = new URLSearchParams(
    Object.entries(o)
      .filter(([, v]) => v != null && v !== '')
      .map(([k, v]) => [k, String(v)]),
  );
  p.sort();
  const s = p.toString();
  return s ? '?' + s : '';
};

/** Passes every key through unchanged; no schema strips the dynamic `f.*` keys. */
export function validateSearch(search: Record<string, unknown>): SearchRecord {
  const out: SearchRecord = {};
  for (const [key, value] of Object.entries(search)) {
    if (typeof value === 'string') out[key] = value;
    else if (typeof value === 'number' || typeof value === 'boolean') out[key] = String(value);
  }
  return out;
}

/** The canonical (sorted) query string without `?`, as stored by saved views. */
export function canonicalQuery(search: SearchRecord, omit: (key: string) => boolean = () => false): string {
  const kept = Object.fromEntries(Object.entries(search).filter(([key]) => !omit(key)));
  return stringifySearch(kept).replace(/^\?/, '');
}

/** URL parameters that belong to the detail page, never to a list request. */
export const DETAIL_PAGE_PARAMS: ReadonlySet<string> = new Set(['tab', 'from', 'to', 'comments', 'thread', 'edit']);

/** List query key and request: canonical, without `cols` and detail-page parameters. */
export function listQueryString(search: SearchRecord): string {
  return canonicalQuery(search, (key) => key === 'cols' || DETAIL_PAGE_PARAMS.has(key));
}

/** Facet key and request: additionally without `f.<field>`, `page`, `page_size` and `sort`. */
export function facetQueryString(search: SearchRecord, field: string): string {
  const omitted = new Set(['cols', 'page', 'page_size', 'sort', filterKey(field)]);
  return canonicalQuery(search, (key) => omitted.has(key) || DETAIL_PAGE_PARAMS.has(key));
}

/** Export request: every list parameter except paging, plus `format` (docs/API.md §5). */
export function exportQueryString(search: SearchRecord, format: 'csv' | 'xlsx'): string {
  const omitted = new Set(['page', 'page_size']);
  const kept = Object.fromEntries(
    Object.entries(search).filter(([key]) => !omitted.has(key) && !DETAIL_PAGE_PARAMS.has(key)),
  );
  return canonicalQuery({ ...kept, format });
}

/** Applies a saved view's stored query by navigation (docs/UI.md §1.2). */
export function searchFromQuery(query: string): SearchRecord {
  return Object.fromEntries(new URLSearchParams(query));
}

function without(search: SearchRecord, ...keys: string[]): SearchRecord {
  return Object.fromEntries(Object.entries(search).filter(([key]) => !keys.includes(key)));
}

// ---------------------------------------------------------------------------
// Field filters: f.<field>=<op>:<value> (docs/API.md §4.1)
// ---------------------------------------------------------------------------

/** Reserved list token meaning "the field is empty". */
export const EMPTY_TOKEN = '~empty';

export const filterKey = (field: string): string => `f.${field}`;

export interface RawFilter {
  op: string;
  /** Everything after the first colon (text values may contain colons and commas). */
  value: string;
}

export function parseFilter(raw: string | undefined): RawFilter | null {
  if (raw === undefined) return null;
  const colon = raw.indexOf(':');
  if (colon <= 0) return null;
  return { op: raw.slice(0, colon), value: raw.slice(colon + 1) };
}

export const formatFilter = (op: string, value: string): string => `${op}:${value}`;

export const splitList = (value: string): string[] => (value === '' ? [] : value.split(','));

export interface DateBounds {
  from: string;
  to: string;
}

/** `<from>..<to>`; either bound may be empty. */
export function parseRange(value: string): DateBounds | null {
  const sep = value.indexOf('..');
  if (sep < 0) return null;
  return { from: value.slice(0, sep), to: value.slice(sep + 2) };
}

export const getFilter = (search: SearchRecord, field: string): string | undefined => search[filterKey(field)];

/** Sets or removes (`null`) the filter on one field; any filter change returns to page 1. */
export function setFilter(search: SearchRecord, field: string, raw: string | null): SearchRecord {
  const next = without(search, 'page', filterKey(field));
  if (raw !== null) next[filterKey(field)] = raw;
  return next;
}

/** Active field filters as `[field, raw]`, in key order. */
export function activeFilters(search: SearchRecord): [string, string][] {
  return Object.entries(search)
    .filter(([key, value]) => key.startsWith('f.') && value !== '')
    .map(([key, value]): [string, string] => [key.slice(2), value])
    .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0));
}

/** Removes every field filter, the full-text query and the `deleted` mode. */
export function clearFilters(search: SearchRecord): SearchRecord {
  return Object.fromEntries(
    Object.entries(withQuery(search, '')).filter(([key]) => !key.startsWith('f.') && key !== 'deleted'),
  );
}

// --- text ------------------------------------------------------------------

export type TextFilterValue = { op: 'contains' | 'eq'; text: string } | { op: 'empty'; empty: boolean };

export function parseTextFilter(raw: string | undefined): TextFilterValue | null {
  const f = parseFilter(raw);
  if (!f) return null;
  if (f.op === 'contains' || f.op === 'eq') return { op: f.op, text: f.value };
  if (f.op === 'empty' && (f.value === 'true' || f.value === 'false')) return { op: 'empty', empty: f.value === 'true' };
  return null;
}

export function formatTextFilter(value: TextFilterValue): string | null {
  if (value.op === 'empty') return formatFilter('empty', String(value.empty));
  return value.text === '' ? null : formatFilter(value.op, value.text);
}

// --- multiselect -----------------------------------------------------------

export type MultiselectOp = 'in' | 'nin' | 'any' | 'all' | 'none';

export interface MultiselectFilterValue {
  op: MultiselectOp;
  /** Codes, possibly including EMPTY_TOKEN. */
  values: string[];
}

const SCALAR_OPS: readonly MultiselectOp[] = ['in', 'nin'];
const LIST_OPS: readonly MultiselectOp[] = ['any', 'all', 'none'];

export const multiselectOps = (isList: boolean): readonly MultiselectOp[] => (isList ? LIST_OPS : SCALAR_OPS);

/** `empty:true|false` is shown as the equivalent `~empty` selection. */
export function parseMultiselectFilter(raw: string | undefined, isList: boolean): MultiselectFilterValue | null {
  const f = parseFilter(raw);
  if (!f) return null;
  if (f.op === 'empty' && (f.value === 'true' || f.value === 'false')) {
    const positive = f.value === 'true';
    return { op: isList ? (positive ? 'any' : 'none') : positive ? 'in' : 'nin', values: [EMPTY_TOKEN] };
  }
  const op = multiselectOps(isList).find((candidate) => candidate === f.op);
  return op ? { op, values: splitList(f.value) } : null;
}

export function formatMultiselectFilter(value: MultiselectFilterValue): string | null {
  // `all` cannot take the empty token (docs/API.md §4.1).
  const values = value.op === 'all' ? value.values.filter((v) => v !== EMPTY_TOKEN) : value.values;
  return values.length === 0 ? null : formatFilter(value.op, values.join(','));
}

// --- date range ------------------------------------------------------------

export type DateRangeFilterValue =
  | { op: 'overlaps' | 'within'; from: string; to: string }
  | { op: 'empty'; empty: boolean };

export function parseDateRangeFilter(raw: string | undefined): DateRangeFilterValue | null {
  const f = parseFilter(raw);
  if (!f) return null;
  if (f.op === 'empty' && (f.value === 'true' || f.value === 'false')) return { op: 'empty', empty: f.value === 'true' };
  if (f.op !== 'overlaps' && f.op !== 'within') return null;
  const range = parseRange(f.value);
  return range ? { op: f.op, ...range } : null;
}

export function formatDateRangeFilter(value: DateRangeFilterValue): string | null {
  if (value.op === 'empty') return formatFilter('empty', String(value.empty));
  if (value.from === '' && value.to === '') return null;
  return formatFilter(value.op, `${value.from}..${value.to}`);
}

// --- bool ------------------------------------------------------------------

export function parseBoolFilter(raw: string | undefined): boolean | null {
  const f = parseFilter(raw);
  if (f?.op !== 'eq' || (f.value !== 'true' && f.value !== 'false')) return null;
  return f.value === 'true';
}

export const formatBoolFilter = (value: boolean | null): string | null =>
  value === null ? null : formatFilter('eq', String(value));

// --- number range ----------------------------------------------------------

export interface NumberRangeFilterValue {
  min: number | null;
  max: number | null;
}

function toNumber(text: string): number | null {
  if (text.trim() === '') return null;
  const n = Number(text);
  return Number.isFinite(n) ? n : null;
}

export function parseNumberRangeFilter(raw: string | undefined): NumberRangeFilterValue | null {
  const f = parseFilter(raw);
  if (!f) return null;
  if (f.op === 'eq') {
    const n = toNumber(f.value);
    return n === null ? null : { min: n, max: n };
  }
  if (f.op !== 'range') return null;
  const range = parseRange(f.value);
  return range ? { min: toNumber(range.from), max: toNumber(range.to) } : null;
}

export function formatNumberRangeFilter(value: NumberRangeFilterValue): string | null {
  if (value.min === null && value.max === null) return null;
  return formatFilter('range', `${value.min ?? ''}..${value.max ?? ''}`);
}

// --- ref -------------------------------------------------------------------

export type RefFilterValue = { op: 'in' | 'confirmed'; ids: string[] } | { op: 'empty'; empty: boolean };

export function parseRefFilter(raw: string | undefined): RefFilterValue | null {
  const f = parseFilter(raw);
  if (!f) return null;
  if (f.op === 'empty' && (f.value === 'true' || f.value === 'false')) {
    return f.value === 'true' ? { op: 'in', ids: [EMPTY_TOKEN] } : { op: 'empty', empty: false };
  }
  if (f.op === 'in' || f.op === 'confirmed') return { op: f.op, ids: splitList(f.value) };
  return null;
}

export function formatRefFilter(value: RefFilterValue): string | null {
  if (value.op === 'empty') return formatFilter('empty', String(value.empty));
  // `confirmed:` takes document link subjects only; the empty token belongs to `in`.
  const ids = value.op === 'confirmed' ? value.ids.filter((id) => id !== EMPTY_TOKEN) : value.ids;
  return ids.length === 0 ? null : formatFilter(value.op, ids.join(','));
}

// ---------------------------------------------------------------------------
// Quick filters (docs/UI.md §3, docs/API.md §3.1)
// ---------------------------------------------------------------------------

export const queryPairs = (query: string): [string, string][] => [...new URLSearchParams(query)];

/** Active only if the URL contains exactly the query's key/value pairs. */
export function isQueryActive(search: SearchRecord, query: string): boolean {
  const pairs = queryPairs(query);
  return pairs.length > 0 && pairs.every(([key, value]) => search[key] === value);
}

/** Activating replaces any filter on the same field; deactivating removes it. */
export function toggleQuery(search: SearchRecord, query: string): SearchRecord {
  const pairs = queryPairs(query);
  const next = without(search, 'page', ...pairs.map(([key]) => key));
  if (!isQueryActive(search, query)) for (const [key, value] of pairs) next[key] = value;
  return next;
}

/** Codes of a chips quick filter: only a plain `in:` list counts. */
export function chipValues(search: SearchRecord, field: string): string[] {
  const f = parseFilter(getFilter(search, field));
  return f?.op === 'in' ? splitList(f.value).filter((v) => v !== EMPTY_TOKEN) : [];
}

/** Writes `f.<field>=in:<codes>` with the codes in vocabulary order. */
export function setChipValues(search: SearchRecord, field: string, codes: string[], order: string[]): SearchRecord {
  const rank = (code: string) => {
    const index = order.indexOf(code);
    return index < 0 ? order.length : index;
  };
  const sorted = [...new Set(codes)].sort((a, b) => rank(a) - rank(b));
  return setFilter(search, field, sorted.length ? formatFilter('in', sorted.join(',')) : null);
}

export interface PeriodParameters {
  ministry_founded: string;
  full_scale_invasion: string;
}

/** Period codes of the presets, in chronological order (vocabulary `period`). */
export const PRESET_PERIODS = ['pre_ministry', 'pre_invasion', 'full_scale_war'] as const;

/**
 * Mutually exclusive `within` presets generated from the cut-off dates
 * (docs/API.md §3.1). Dates that straddle a cut-off match no preset.
 */
export function periodPresets(
  field: string,
  params: PeriodParameters,
  label: (period: (typeof PRESET_PERIODS)[number]) => string,
): QuickFilterPresetOption[] {
  const ministry = params.ministry_founded;
  const invasion = params.full_scale_invasion;
  const ranges: Record<(typeof PRESET_PERIODS)[number], string> = {
    pre_ministry: `..${addDays(ministry, -1)}`,
    pre_invasion: `${ministry}..${addDays(invasion, -1)}`,
    full_scale_war: `${invasion}..`,
  };
  return PRESET_PERIODS.map((period) => ({
    key: period,
    label: label(period),
    query: new URLSearchParams([[filterKey(field), formatFilter('within', ranges[period])]]).toString(),
  }));
}

// ---------------------------------------------------------------------------
// Sorting: sort=field[,-field2[,field3]] (docs/API.md §4.2)
// ---------------------------------------------------------------------------

export const MAX_SORT_FIELDS = 3;
export const RELEVANCE = 'relevance';

export interface SortTerm {
  field: string;
  desc: boolean;
}

export function parseSort(value: string | undefined): SortTerm[] {
  if (!value) return [];
  return value
    .split(',')
    .filter((part) => part !== '' && part !== '-')
    .map((part) => (part.startsWith('-') ? { field: part.slice(1), desc: true } : { field: part, desc: false }));
}

export const formatSort = (terms: SortTerm[]): string =>
  terms.map((term) => (term.desc ? `-${term.field}` : term.field)).join(',');

/** The sort in effect: the URL's, else the type's default. */
export const effectiveSort = (search: SearchRecord, defaultSort: string): SortTerm[] =>
  parseSort(search.sort ?? defaultSort);

/**
 * Header click: cycles asc → desc → none on a single column. Shift-click
 * (`additive`) cycles the column inside a multi-sort and appends new columns
 * up to MAX_SORT_FIELDS.
 */
export function cycleSort(current: SortTerm[], field: string, additive: boolean): SortTerm[] {
  const index = current.findIndex((term) => term.field === field);
  const existing = index >= 0 ? current[index] : undefined;
  if (!additive) {
    if (current.length === 1 && existing) return existing.desc ? [] : [{ field, desc: true }];
    return [{ field, desc: false }];
  }
  if (existing) {
    return existing.desc
      ? current.filter((term) => term.field !== field)
      : current.map((term) => (term.field === field ? { field, desc: true } : term));
  }
  return current.length >= MAX_SORT_FIELDS ? current : [...current, { field, desc: false }];
}

/** An empty sort removes the parameter, so the default sort applies again. */
export function setSort(search: SearchRecord, terms: SortTerm[]): SearchRecord {
  const next = without(search, 'page', 'sort');
  if (terms.length) next.sort = formatSort(terms);
  return next;
}

/**
 * Applies a header click. A plain click cycles on the URL's explicit sort, so
 * a default such as `-date` cannot trap the cycle; shift-click extends the
 * sort that is in effect (default included).
 */
export function clickSort(search: SearchRecord, defaultSort: string, field: string, additive: boolean): SearchRecord {
  const base = additive ? effectiveSort(search, defaultSort) : parseSort(search.sort);
  return setSort(search, cycleSort(base, field, additive));
}

// ---------------------------------------------------------------------------
// Full-text query, paging, deleted rows, columns
// ---------------------------------------------------------------------------

/** Sets `q`; without `q`, a relevance sort would be refused (400 bad_sort). */
export function withQuery(search: SearchRecord, q: string): SearchRecord {
  const text = q.trim();
  const next = without(search, 'page', 'q');
  if (text) {
    next.q = text;
    return next;
  }
  const terms = parseSort(next.sort).filter((term) => term.field !== RELEVANCE);
  return setSort(next, terms);
}

export const DEFAULT_PAGE_SIZE = 50;
export const PAGE_SIZES = [25, 50, 100, 200] as const;

function positiveInt(value: string | undefined): number | null {
  if (value === undefined || !/^\d+$/.test(value)) return null;
  const n = Number(value);
  return n >= 1 ? n : null;
}

export const getPage = (search: SearchRecord): number => positiveInt(search.page) ?? 1;

export const getPageSize = (search: SearchRecord): number => positiveInt(search.page_size) ?? DEFAULT_PAGE_SIZE;

export function withPage(search: SearchRecord, page: number): SearchRecord {
  const next = without(search, 'page');
  if (page > 1) next.page = String(page);
  return next;
}

export function withPageSize(search: SearchRecord, size: number): SearchRecord {
  const next = without(search, 'page', 'page_size');
  if (size !== DEFAULT_PAGE_SIZE) next.page_size = String(size);
  return next;
}

export function getDeletedMode(search: SearchRecord): DeletedMode {
  const value = search.deleted;
  return value === 'only' || value === 'include' ? value : 'exclude';
}

/** `exclude` is the default and removes the parameter. */
export function withDeletedMode(search: SearchRecord, mode: DeletedMode): SearchRecord {
  const next = without(search, 'page', 'deleted');
  if (mode !== 'exclude') next.deleted = mode;
  return next;
}

/** Visible columns: `cols` (known names, in URL order), else the defaults. */
export function getColumns(search: SearchRecord, known: readonly string[], defaults: readonly string[]): string[] {
  const requested = search.cols ? splitList(search.cols).filter((name) => known.includes(name)) : [];
  return requested.length ? [...new Set(requested)] : [...defaults];
}

/** Stores the column choice; the default choice removes `cols`. */
export function withColumns(search: SearchRecord, names: readonly string[], defaults: readonly string[]): SearchRecord {
  const next = without(search, 'cols');
  const isDefault = names.length === defaults.length && names.every((name, i) => name === defaults[i]);
  if (!isDefault && names.length) next.cols = names.join(',');
  return next;
}

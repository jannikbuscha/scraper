// Reading and formatting field values per field type (docs/API.md §2,
// docs/DATA_MODEL.md §2.1). React rendering lives in components/fields.
import dayjs from 'dayjs';

import type { Alias, FieldSpec, FieldType, Item, JsonValue, RefLabel, Refs } from '../api/types';
import { formatPartialDate, isIsoDate } from './partial-date';
import { termLabel, type VocabIndex } from './vocab';

// ---------------------------------------------------------------------------
// Narrowing JSON values
// ---------------------------------------------------------------------------

export const asString = (value: JsonValue | undefined): string | null => (typeof value === 'string' ? value : null);

export const asNumber = (value: JsonValue | undefined): number | null =>
  typeof value === 'number' && Number.isFinite(value) ? value : null;

export const asBoolean = (value: JsonValue | undefined): boolean | null => (typeof value === 'boolean' ? value : null);

export function asStringArray(value: JsonValue | undefined): string[] {
  return Array.isArray(value) ? value.filter((entry): entry is string => typeof entry === 'string') : [];
}

/** The option of `options` equal to `value`, for typed state from untyped inputs. */
export function pick<T extends string>(options: readonly T[], value: string | null): T | undefined {
  return options.find((option) => option === value);
}

export function isJsonObject(value: JsonValue | undefined): value is Record<string, JsonValue> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

export function asAliases(value: JsonValue | undefined): Alias[] {
  if (!Array.isArray(value)) return [];
  return value.filter(isJsonObject).map((entry) => ({
    text: asString(entry.text) ?? '',
    lang: asString(entry.lang),
    case_sensitive: asBoolean(entry.case_sensitive) ?? true,
    kind: asString(entry.kind) ?? 'name',
    exclude_patterns: asStringArray(entry.exclude_patterns),
  }));
}

/** Empty means null or `[]` (also `''`); `false` and `0` are values (docs/DATA_MODEL.md §1.2). */
export function isEmptyValue(value: JsonValue | undefined): boolean {
  return value === undefined || value === null || value === '' || (Array.isArray(value) && value.length === 0);
}

// ---------------------------------------------------------------------------
// Where a field's value lives in an item
// ---------------------------------------------------------------------------

/** System columns are top-level item properties (docs/API.md §2). */
export const SYSTEM_COLUMNS: ReadonlySet<string> = new Set([
  'id',
  'version',
  'created_at',
  'created_by',
  'updated_at',
  'updated_by',
  'deleted_at',
  'deleted_by',
  'merged_into',
]);

function systemValue(item: Item, name: string): JsonValue {
  switch (name) {
    case 'id':
      return item.id;
    case 'version':
      return item.version;
    case 'created_at':
      return item.created_at;
    case 'created_by':
      return item.created_by;
    case 'updated_at':
      return item.updated_at;
    case 'updated_by':
      return item.updated_by;
    case 'deleted_at':
      return item.deleted_at;
    case 'deleted_by':
      return item.deleted_by;
    case 'merged_into':
      return item.merged_into;
    default:
      return null;
  }
}

export function getFieldValue(item: Item, field: FieldSpec): JsonValue {
  if (SYSTEM_COLUMNS.has(field.name)) return systemValue(item, field.name);
  if (field.derived) return item.derived?.[field.name] ?? null;
  if (field.virtual) return item.virtual[field.name] ?? item.fields[field.name] ?? null;
  return item.fields[field.name] ?? null;
}

// ---------------------------------------------------------------------------
// Derived values: basis, reason and the deciding event or participation
// ---------------------------------------------------------------------------

/** Derived fields whose detail keys use another stem (docs/API.md §2: trajectory_reason). */
const DERIVED_KEY_STEMS: Readonly<Record<string, string>> = { war_trajectory: 'trajectory' };

export interface DerivedDetails {
  basis: string | null;
  reason: string | null;
  /** The deciding event or participation, labelled from `refs`. */
  decidedBy: RefLabel | null;
}

export function derivedDetails(item: Item, field: string): DerivedDetails {
  const derived = item.derived ?? {};
  const stem = DERIVED_KEY_STEMS[field] ?? field;
  const refKey = [`${stem}_event_id`, `${stem}_participation_id`].find((key) => asString(derived[key]) !== null);
  return {
    basis: asString(derived[`${stem}_basis`]),
    reason: asString(derived[`${stem}_reason`]),
    decidedBy: refKey ? (item.refs[`derived.${refKey}`] ?? null) : null,
  };
}

// ---------------------------------------------------------------------------
// Timestamps (UTC strings with microseconds, docs/DATA_MODEL.md §1.1)
// ---------------------------------------------------------------------------

export function parseTimestamp(value: string): Date | null {
  // Date parsing is only specified for milliseconds; drop extra digits.
  const date = new Date(value.replace(/(\.\d{3})\d+/, '$1'));
  return Number.isNaN(date.getTime()) ? null : date;
}

/** Local time for display, e.g. `2026-10-28 18:00`. */
export function formatLocalTimestamp(value: string): string {
  const date = parseTimestamp(value);
  return date ? dayjs(date).format('YYYY-MM-DD HH:mm') : value;
}

/** Exact UTC time, e.g. `2026-10-28 17:00:00 UTC`. */
export function formatUtcTimestamp(value: string): string {
  const date = parseTimestamp(value);
  return date ? `${date.toISOString().slice(0, 19).replace('T', ' ')} UTC` : value;
}

/** Local calendar day of a timestamp (feeds group by local day). */
export function localDay(value: string): string {
  const date = parseTimestamp(value);
  return date ? dayjs(date).format('YYYY-MM-DD') : value.slice(0, 10);
}

/** A Date in the API timestamp format, e.g. `2026-10-28T17:00:00.000000Z`. */
export const apiTimestamp = (date: Date): string => date.toISOString().replace(/Z$/, '000Z');

/** Local midnight of a `YYYY-MM-DD` day, plus `offsetDays`. */
function localMidnight(day: string, offsetDays: number): Date | null {
  if (!isIsoDate(day)) return null;
  const [year = 0, month = 1, date = 1] = day.split('-').map(Number);
  return new Date(year, month - 1, date + offsetDays);
}

/** First instant of a local day as an API timestamp (feed filters send local days, docs/UI.md §5). */
export function localDayStart(day: string): string | null {
  const start = localMidnight(day, 0);
  return start ? apiTimestamp(start) : null;
}

/** Last microsecond of a local day as an API timestamp (`until` is inclusive). */
export function localDayEnd(day: string): string | null {
  const next = localMidnight(day, 1);
  return next ? apiTimestamp(new Date(next.getTime() - 1)).replace(/000Z$/, '999Z') : null;
}

// ---------------------------------------------------------------------------
// Plain-text formatting (tooltips, summaries, filter descriptions)
// ---------------------------------------------------------------------------

export const EMPTY_TEXT = '—';

export interface TextFormatContext {
  vocab: VocabIndex;
  refs?: Refs | undefined;
}

/** Any JSON value as text: strings verbatim, numbers and booleans as written, structures as JSON. */
export function jsonText(value: JsonValue): string {
  if (value === null) return EMPTY_TEXT;
  if (typeof value === 'string') return value;
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  return JSON.stringify(value);
}

export function formatValueText(field: FieldSpec, value: JsonValue, context: TextFormatContext): string {
  if (isEmptyValue(value)) return EMPTY_TEXT;
  switch (field.type) {
    case 'bool':
      return value === true ? 'yes' : value === false ? 'no' : jsonText(value);
    case 'vocab':
      return typeof value === 'string' ? termLabel(context.vocab, field.vocabulary, value) : jsonText(value);
    case 'vocab_list':
      return asStringArray(value)
        .map((code) => termLabel(context.vocab, field.vocabulary, code))
        .join(', ');
    case 'ref':
      return typeof value === 'string' ? (findRef(context.refs, field.name, value)?.label ?? value) : jsonText(value);
    case 'partial_date':
      return typeof value === 'string' ? formatPartialDate(value) : jsonText(value);
    case 'datetime':
      return typeof value === 'string' ? formatLocalTimestamp(value) : jsonText(value);
    case 'url_list':
    case 'string_list':
      return asStringArray(value).join('; ');
    case 'alias_list':
      return asAliases(value)
        .map((alias) => alias.text)
        .join('; ');
    case 'doc_links':
      return pluralize(Array.isArray(value) ? value.length : 0, 'link');
    default:
      return jsonText(value);
  }
}

export const pluralize = (count: number, singular: string, plural = `${singular}s`): string =>
  `${count} ${count === 1 ? singular : plural}`;

/**
 * Label of a referenced ID. Revision and conflict payloads key `refs` by ID;
 * items key them by field name, which only labels the item's current value.
 */
export function findRef(refs: Refs | undefined, field: string, id: string): RefLabel | undefined {
  const byId = refs?.[id];
  if (byId) return byId;
  const byField = refs?.[field];
  return byField?.id === id ? byField : undefined;
}

/** A field spec for names the registry does not describe (e.g. comment fields in diffs). */
export function syntheticField(name: string, type: FieldType, label = name): FieldSpec {
  return {
    name,
    label,
    type,
    vocabulary: null,
    ref_types: null,
    group: 'system',
    required: false,
    editable: false,
    create_only: false,
    system: false,
    tracked: true,
    derived: false,
    virtual: false,
    filter: null,
    sortable: false,
    in_list: false,
    in_create: false,
    default: null,
    bulk_editable: false,
    help: null,
  };
}

/** A display type guessed from values, for fields without a spec. */
export function guessFieldType(...values: JsonValue[]): FieldType {
  const present = values.filter((value) => value !== null);
  if (present.every((value) => typeof value === 'string')) return 'text';
  if (present.every((value) => typeof value === 'boolean')) return 'bool';
  if (present.every((value) => typeof value === 'number')) return 'number';
  if (present.every((value) => Array.isArray(value) && value.every((entry) => typeof entry === 'string'))) {
    return 'string_list';
  }
  return 'json';
}

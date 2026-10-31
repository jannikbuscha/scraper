// The column mapping of an import (docs/UI.md §8.5, docs/COLLECTORS.md §9.3):
// per column an importable field, the ID key or nothing; a field can be
// chosen only once. The mapping lives in component state until the run.
import type { ImportPreview } from '../../api/acquisition-types';

/** The record's ID column (a key only). */
export const ID_KEY = 'id';
/** "— ignore —". */
export const IGNORE = '';

export type Mapping = Readonly<Record<string, string>>;

/** The suggested mapping, limited to targets the type accepts and used at most once. */
export function initialMapping(preview: Pick<ImportPreview, 'columns' | 'suggested_mapping' | 'importable_fields'>): Mapping {
  const allowed = new Set([ID_KEY, ...preview.importable_fields]);
  const used = new Set<string>();
  const mapping: Record<string, string> = {};
  for (const column of preview.columns) {
    const target = preview.suggested_mapping[column];
    if (target !== undefined && allowed.has(target) && !used.has(target)) {
      mapping[column] = target;
      used.add(target);
    } else mapping[column] = IGNORE;
  }
  return mapping;
}

/** The column that maps to `field`, if any. */
export const columnOf = (mapping: Mapping, field: string): string | undefined =>
  Object.keys(mapping).find((column) => mapping[column] === field);

/**
 * Maps `column` to `field`; refused (null) when another column already maps
 * to that field. IGNORE is always allowed.
 */
export function setColumnField(mapping: Mapping, column: string, field: string): Mapping | null {
  if (field !== IGNORE) {
    const owner = columnOf(mapping, field);
    if (owner !== undefined && owner !== column) return null;
  }
  return { ...mapping, [column]: field };
}

/** `mapping` of the request: the columns that are not ignored. */
export const mappingRequest = (mapping: Mapping): Record<string, string> =>
  Object.fromEntries(Object.entries(mapping).filter(([, field]) => field !== IGNORE));

/** The default key: the ID column if mapped, else the type's natural key (slug or url) if mapped, else none. */
export function defaultKey(mapping: Mapping, keyFields: readonly string[]): string | null {
  const mapped = keyFields.filter((field) => columnOf(mapping, field) !== undefined);
  return mapped.includes(ID_KEY) ? ID_KEY : (mapped[0] ?? null);
}

/** A key field stays only while a column maps to it. */
export const validKey = (mapping: Mapping, key: string | null): string | null =>
  key !== null && columnOf(mapping, key) !== undefined ? key : null;

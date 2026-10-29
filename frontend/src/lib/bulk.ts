// Bulk edit (docs/API.md §3.2, docs/UI.md §3): the request for the selected
// rows and the per-row results.
import type { BulkRequest, BulkResult, BulkStatus, JsonObject, JsonValue } from '../api/types';

/** A selected row. */
export interface BulkTarget {
  id: string;
  label: string;
  /** The row's field values (the codes a remove can target). */
  values?: JsonObject | undefined;
}

export type BulkOp = 'set' | 'add' | 'remove';

export interface BulkEdit {
  field: string;
  op: BulkOp;
  /** A value for `set`; a list of values for `add` and `remove`. */
  value: JsonValue;
  /** Further `set` values the rules demand, e.g. `scope_note` with `in_paper_scope`. */
  alongside?: JsonObject;
}

export function bulkRequest(targets: readonly BulkTarget[], edit: BulkEdit, note: string | null): BulkRequest {
  const ids = targets.map((target) => target.id);
  const alongside = edit.alongside ?? {};
  if (edit.op === 'set') return { ids, set: { [edit.field]: edit.value, ...alongside }, note };
  const values = Array.isArray(edit.value) ? edit.value : [];
  const request: BulkRequest = { ids, [edit.op]: { [edit.field]: values }, note };
  return Object.keys(alongside).length > 0 ? { ...request, set: alongside } : request;
}

/**
 * The codes the selected rows carry in a list field, in first-seen order. A
 * bulk remove offers them although inactive: the server refuses only adding
 * inactive codes (docs/DATA_MODEL.md §7), so a deactivated code can be cleaned
 * out of many rows at once.
 */
export function codesInRows(targets: readonly BulkTarget[], field: string): string[] {
  const codes = new Set<string>();
  for (const target of targets) {
    const value = target.values?.[field];
    const listed = Array.isArray(value) ? value : [value];
    for (const code of listed) {
      if (typeof code === 'string') codes.add(code);
    }
  }
  return [...codes];
}

export const BULK_STATUSES: readonly BulkStatus[] = ['updated', 'unchanged', 'entity_deleted', 'error'];

export function countBulkResults(results: readonly BulkResult[]): Record<BulkStatus, number> {
  const counts: Record<BulkStatus, number> = { updated: 0, unchanged: 0, entity_deleted: 0, error: 0 };
  for (const result of results) counts[result.status] += 1;
  return counts;
}

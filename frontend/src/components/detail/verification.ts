// Field verification (docs/UI.md §4.1, docs/DATA_MODEL.md §6.4): which fields
// can be verified, their current state, and what to do on a 409 conflict
// (docs/UI.md §1.3): retry once if the value did not change, else ask.
import type { ConflictPayload, FieldSpec, Item, JsonValue, VerificationStatus } from '../../api/types';
import { valuesEqual } from '../../lib/diff';
import { getFieldValue, isEmptyValue } from '../../lib/format';

/** Tracked, non-system, stored fields with a value; never the record-level status itself. */
export function isVerifiable(field: FieldSpec, item: Item): boolean {
  return (
    field.tracked &&
    !field.system &&
    !field.derived &&
    !field.virtual &&
    field.name !== 'verification_status' &&
    !isEmptyValue(getFieldValue(item, field))
  );
}

export const fieldVerification = (item: Item, field: string): VerificationStatus =>
  item.field_meta[field]?.verified ?? 'unverified';

export type VerifyConflictDecision =
  /** The row was deleted meanwhile: show the reload notice. */
  | { kind: 'stale' }
  /** The field's value is unchanged: retry once with the current version. */
  | { kind: 'retry'; version: number }
  /** The value changed: ask "Value changed from A to B by X — verify B?". */
  | { kind: 'ask'; version: number; from: JsonValue; to: JsonValue; by: string | null; at: string | null };

export function verifyConflictDecision(payload: ConflictPayload, field: string): VerifyConflictDecision {
  if (payload.current_state.deleted_at !== null) return { kind: 'stale' };
  const before = payload.base?.[field] ?? null;
  const now = payload.current[field] ?? null;
  if (payload.base !== null && valuesEqual(before, now)) return { kind: 'retry', version: payload.current_version };
  const changer = payload.intervening.findLast((revision) => revision.changed_fields.includes(field));
  return {
    kind: 'ask',
    version: payload.current_version,
    from: before,
    to: now,
    by: changer?.author ?? null,
    at: changer?.at ?? null,
  };
}

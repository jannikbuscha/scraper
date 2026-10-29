// Field verification (docs/UI.md §4.1, docs/DATA_MODEL.md §6.4): which fields
// can be verified, their current state, and what to do on a 409 conflict
// (docs/UI.md §1.3): retry once only if nobody touched the field since the
// base (neither its value nor its verification), else ask.
import type { ConflictPayload, FieldSpec, Item, JsonValue, VerificationStatus } from '../../api/types';
import { valuesEqual } from '../../lib/diff';
import { getFieldValue, isEmptyValue } from '../../lib/format';

/**
 * Tracked, non-system, stored fields with a value; never the record-level
 * status itself, and not the fields of evidence rows: verifying a field needs
 * evidence about its record, and evidence cannot be the subject of evidence
 * (docs/DATA_MODEL.md §3, §6.4).
 */
export function isVerifiable(field: FieldSpec, item: Item): boolean {
  return (
    item.type !== 'evidence' &&
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
  /** Nobody touched the field since the base: retry once with the current version. */
  | { kind: 'retry'; version: number }
  /**
   * The field changed since the base: ask "Value changed from A to B by X — verify B?",
   * or, if only its verification changed, "Verification changed to S by X (note) — … anyway?".
   */
  | VerifyQuestionDecision;

export interface VerifyQuestionDecision {
  kind: 'ask';
  version: number;
  from: JsonValue;
  to: JsonValue;
  /** Author and time of the latest revision since the base that touched the field. */
  by: string | null;
  at: string | null;
  /** The field's verification at the base and now, if it changed (`meta_changed_since_base`). */
  verification: readonly [VerificationStatus, VerificationStatus] | null;
  /** The note of that revision (e.g. the reason of a dispute). */
  note: string | null;
}

const asStatus = (value: JsonValue | undefined): VerificationStatus =>
  value === 'verified' || value === 'disputed' ? value : 'unverified';

export function verifyConflictDecision(payload: ConflictPayload, field: string): VerifyConflictDecision {
  if (payload.current_state.deleted_at !== null) return { kind: 'stale' };
  const before = payload.base?.[field] ?? null;
  const now = payload.current[field] ?? null;
  // The revisions since the base that touched the field: a value change, or a
  // verification (changed_fields also lists fields whose field_meta changed,
  // docs/DATA_MODEL.md §6.3), e.g. a colleague's dispute with its reason.
  const touching = payload.intervening.filter((revision) => revision.changed_fields.includes(field));
  const verified = payload.meta_changed_since_base[field]?.verified;
  if (payload.base !== null && valuesEqual(before, now) && touching.length === 0 && verified === undefined) {
    return { kind: 'retry', version: payload.current_version };
  }
  const changer = touching.at(-1);
  return {
    kind: 'ask',
    version: payload.current_version,
    from: before,
    to: now,
    by: changer?.author ?? null,
    at: changer?.at ?? null,
    verification: verified ? [asStatus(verified[0]), asStatus(verified[1])] : null,
    note: changer?.note ?? null,
  };
}

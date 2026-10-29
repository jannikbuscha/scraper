// Field verification (docs/UI.md §4.1, docs/DATA_MODEL.md §6.4): which fields
// can be verified and their current state.
import type { FieldSpec, Item, VerificationStatus } from '../../api/types';
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

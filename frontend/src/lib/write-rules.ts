// Rules that make a write need extra input (docs/DATA_MODEL.md §7), checked
// before sending so the form can ask for it; the server stays authoritative.
import type { JsonObject } from '../api/types';

/** Changing `in_paper_scope` requires a non-empty `scope_note` in the same change. */
export const requiresScopeNote = (changes: JsonObject): boolean => 'in_paper_scope' in changes;

/** Setting the record-level `verification_status` to verified or disputed requires a note. */
export const requiresVerificationNote = (changes: JsonObject): boolean =>
  changes.verification_status === 'verified' || changes.verification_status === 'disputed';

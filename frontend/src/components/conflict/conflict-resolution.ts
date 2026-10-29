// Resolving a 409 `conflict` of an edit (docs/UI.md §4.1, docs/DATA_MODEL.md
// §6.5): every submitted field is classified against the current state, the
// user chooses per conflicting field, and the result is the new frozen base
// (the current server state) plus the changes to send against it.
import type { ConflictPayload, JsonObject, JsonValue } from '../../api/types';
import { valuesEqual } from '../../lib/diff';

export type ConflictChoice = { kind: 'theirs' } | { kind: 'yours' } | { kind: 'merged'; value: JsonValue };

export type ConflictChoices = Readonly<Record<string, ConflictChoice | undefined>>;

export interface ConflictClassification {
  /** Changed by both sides to different values: a choice is mandatory. */
  conflicting: string[];
  /** Changed only by you: applied as submitted. */
  onlyYours: string[];
  /** Your value already equals the current one: nothing to apply. */
  alreadyCurrent: string[];
  /** Changed only by them: shown for information. */
  onlyTheirs: string[];
}

export interface EditBase {
  fields: JsonObject;
  version: number;
}

export interface ConflictResolution {
  /** The new frozen base: the current server state. */
  base: EditBase;
  /** The changes to send with `expected_version = base.version`. */
  changes: JsonObject;
}

export type ResolveResult = { ok: true; resolution: ConflictResolution } | { ok: false; missing: string[] };

const valueOf = (object: JsonObject | null, field: string): JsonValue => object?.[field] ?? null;

export function classifyConflict(payload: ConflictPayload): ConflictClassification {
  const yours = Object.keys(payload.your_changes);
  const changedSinceBase = new Set(payload.changed_since_base);
  const flagged = new Set(payload.conflicting_fields);
  const classification: ConflictClassification = { conflicting: [], onlyYours: [], alreadyCurrent: [], onlyTheirs: [] };
  for (const field of yours) {
    const mine = valueOf(payload.your_changes, field);
    const sameAsCurrent = valuesEqual(mine, valueOf(payload.current, field));
    // The server's list, plus the contract's definition as a safety net.
    if (flagged.has(field) || (changedSinceBase.has(field) && !sameAsCurrent)) classification.conflicting.push(field);
    else if (sameAsCurrent) classification.alreadyCurrent.push(field);
    else classification.onlyYours.push(field);
  }
  classification.onlyTheirs = payload.changed_since_base.filter((field) => !(field in payload.your_changes));
  return classification;
}

/** Conflicting fields that still need a choice. */
export function missingChoices(payload: ConflictPayload, choices: ConflictChoices): string[] {
  return classifyConflict(payload).conflicting.filter((field) => choices[field] === undefined);
}

/**
 * The new base is the current state; the changes are your values for the
 * fields only you changed plus the chosen values of the conflicting fields.
 * Values equal to the current state are dropped (they would be no-ops).
 */
export function resolveConflict(payload: ConflictPayload, choices: ConflictChoices): ResolveResult {
  const missing = missingChoices(payload, choices);
  if (missing.length > 0) return { ok: false, missing };

  const { conflicting, onlyYours } = classifyConflict(payload);
  const changes: JsonObject = {};
  for (const field of onlyYours) changes[field] = valueOf(payload.your_changes, field);
  for (const field of conflicting) {
    const choice = choices[field];
    if (choice === undefined || choice.kind === 'theirs') continue;
    const value = choice.kind === 'yours' ? valueOf(payload.your_changes, field) : choice.value;
    if (!valuesEqual(value, valueOf(payload.current, field))) changes[field] = value;
  }
  return {
    ok: true,
    resolution: { base: { fields: structuredClone(payload.current), version: payload.current_version }, changes },
  };
}

/** Fields whose verification changed since your base and would be reset by applying your value. */
export function verificationResetFields(payload: ConflictPayload, fields: readonly string[]): string[] {
  return fields.filter((field) => {
    const verified = payload.meta_changed_since_base[field]?.verified;
    return verified !== undefined && verified[1] !== 'unverified';
  });
}

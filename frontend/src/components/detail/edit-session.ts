// Edit mode of the detail page (docs/UI.md §4.1): the record's fields when
// editing started, the form values, and the PATCH changes = the values that
// differ from the starting fields.
import type { EntityTypeMeta, FieldSpec, Item, JsonObject, JsonValue } from '../../api/types';
import { valuesEqual } from '../../lib/diff';
import { fieldValueError, isMissingRequired } from '../../lib/field-validation';
import { isEmptyValue } from '../../lib/format';
import { requiresScopeNote, requiresVerificationNote } from '../../lib/write-rules';
import { isReadOnlyType } from '../fields/FieldInput';

export interface EditSession {
  /** The record's fields when editing started. */
  initial: JsonObject;
  values: JsonObject;
}

export const startEditSession = (item: Item): EditSession => ({ initial: item.fields, values: item.fields });

/** Fields the inline form edits; doc_links, json, derived, virtual and system fields stay read-only. */
export function editableFields(typeMeta: EntityTypeMeta): FieldSpec[] {
  return typeMeta.fields.filter((field) => field.editable && !field.create_only && !isReadOnlyType(field));
}

const valueIn = (object: JsonObject, field: string): JsonValue => object[field] ?? null;

/** Only the form values that differ from the fields when editing started. */
export function changedValues(session: EditSession, fields: readonly FieldSpec[]): JsonObject {
  const changes: JsonObject = {};
  for (const field of fields) {
    const value = valueIn(session.values, field.name);
    if (!valuesEqual(value, valueIn(session.initial, field.name))) changes[field.name] = value;
  }
  return changes;
}

export interface EditErrors {
  /** Per field: missing required values, format errors, "one of" constraints. */
  fields: Record<string, string>;
  /** Changing `in_paper_scope` needs a new, non-empty scope note. */
  scopeNote: string | null;
  /** Setting `verification_status` to verified or disputed needs a change note. */
  note: string | null;
}

const isBlank = (value: JsonValue | undefined): boolean =>
  isEmptyValue(typeof value === 'string' ? value.trim() : (value ?? null));

/**
 * Client-side checks before saving; the server stays authoritative. Format
 * checks apply to changed values only, so a stored value the client rules
 * would not accept never blocks an unrelated change.
 */
export function editErrors(
  session: EditSession,
  typeMeta: EntityTypeMeta,
  changes: JsonObject,
  note: string,
): EditErrors {
  const fields: Record<string, string> = {};
  const labelOf = (name: string) => typeMeta.fields.find((field) => field.name === name)?.label ?? name;
  for (const field of editableFields(typeMeta)) {
    const value = valueIn(session.values, field.name);
    const formatError = field.name in changes ? fieldValueError(field, value) : null;
    if (isMissingRequired(field, value)) fields[field.name] = 'Required.';
    else if (formatError) fields[field.name] = formatError;
  }
  for (const { one_of_required: names } of typeMeta.constraints) {
    if (names.every((name) => isBlank(session.values[name]))) {
      for (const name of names) fields[name] ??= `Enter at least one of ${names.map(labelOf).join(' or ')}.`;
    }
  }
  return {
    fields,
    scopeNote:
      requiresScopeNote(changes) && isBlank(changes.scope_note)
        ? 'Changing the paper scope needs a new scope note (the reason for the decision).'
        : null,
    note: requiresVerificationNote(changes) && note.trim() === '' ? 'Setting verified or disputed needs a note.' : null,
  };
}

export const hasEditErrors = (errors: EditErrors): boolean =>
  Object.keys(errors.fields).length > 0 || errors.scopeNote !== null || errors.note !== null;

/** The service itself and every service below it (parent_service_id links), for the parent picker. */
export function serviceSubtree(rootId: string, services: readonly Item[]): string[] {
  const subtree = [rootId];
  // Array iteration also visits the elements appended on the way (breadth first).
  for (const parent of subtree) {
    for (const service of services) {
      const below = service.fields.parent_service_id === parent;
      if (below && !subtree.includes(service.id)) subtree.push(service.id);
    }
  }
  return subtree;
}

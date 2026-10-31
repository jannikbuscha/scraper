// The `values` an edit-and-accept form sends (docs/UI.md §8.2, docs/API.md
// §7.4): only what differs from the proposal, plus the person's additions.
// Unchanged values are left to the proposal, so they keep the collector as
// their provenance (docs/DATA_MODEL.md §16.4). Null means "accept as
// proposed" (no `values`).
import type { FieldSpec, JsonObject, JsonValue } from '../../api/types';
import { valuesEqual } from '../../lib/diff';
import { isEmptyValue } from '../../lib/format';

/** Empty strings and lists count as no value, as on the server. */
const normalised = (value: JsonValue | undefined): JsonValue =>
  value === undefined || isEmptyValue(value) ? null : typeof value === 'string' ? value.trim() || null : value;

const same = (a: JsonValue | undefined, b: JsonValue | undefined): boolean => valuesEqual(normalised(a), normalised(b));

/** `update_field`: `{field: value}` if the person changed the prefilled value, else null. */
export function fieldUpdateValues(field: string, prefilled: JsonValue, edited: JsonValue): JsonObject | null {
  return same(prefilled, edited) ? null : { [field]: normalised(edited) };
}

/** `possibly_discontinued`: `{status}` if another status was chosen, else null. */
export function statusValues(proposed: JsonValue, chosen: JsonValue): JsonObject | null {
  return same(proposed, chosen) ? null : { status: normalised(chosen) };
}

/** `create_event`: the event fields that differ from the proposed event, else null. */
export function eventValues(proposed: JsonObject, form: JsonObject): JsonObject | null {
  const changed = Object.entries(form).filter(([name, value]) => !same(proposed[name], value));
  return changed.length === 0 ? null : Object.fromEntries(changed.map(([name, value]) => [name, normalised(value)]));
}

/** Project fields the person always decides (the proposal never contains them, docs/DATA_MODEL.md §7). */
export const PROJECT_SCOPE_FIELDS = ['in_paper_scope', 'scope_note'] as const;

/**
 * `create_entity`: the fields the person changed against the observed ones,
 * the fields they added (filled in beyond their default), and for a project
 * always the scope decision. An empty slug is left out (the server generates
 * it from the site's slug).
 */
export function createEntityValues(
  type: string,
  fields: readonly FieldSpec[],
  observed: JsonObject,
  form: JsonObject,
): JsonObject {
  const values: JsonObject = {};
  for (const field of fields) {
    const value = form[field.name];
    if (value === undefined) continue;
    const scopeField = type === 'project' && PROJECT_SCOPE_FIELDS.some((name) => name === field.name);
    if (scopeField) {
      values[field.name] = normalised(value) ?? (field.type === 'bool' ? false : null);
      continue;
    }
    if (field.name === 'slug' && normalised(value) === null) continue;
    // An observed field counts when changed; another field when filled in with more than its default.
    const counts =
      field.name in observed
        ? !same(observed[field.name], value)
        : normalised(value) !== null && !same(field.default, value);
    if (counts) values[field.name] = normalised(value);
  }
  return values;
}

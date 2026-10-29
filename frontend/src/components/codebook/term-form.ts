// Vocabulary-term forms of the Codebook page (docs/UI.md §5): which registry
// fields they edit, what a save sends, and the rules for fixed codes and
// replacements (docs/DATA_MODEL.md §7).
import type { FieldSpec, JsonObject, JsonValue, ValidationErrorDetails, Vocabulary, VocabTerm } from '../../api/types';
import { valuesEqual } from '../../lib/diff';
import { isJsonObject } from '../../lib/format';
import { isReadOnlyType } from '../fields/FieldInput';

/** The vocabulary whose terms carry `attributes.counts_as_modification` (decision D-2). */
export const MODIFICATION_VOCABULARY = 'event_type';
export const COUNTS_AS_MODIFICATION = 'counts_as_modification';

/** The term's identity (vocabulary and code): create-only, read-only once created. */
export const identityFields = (fields: readonly FieldSpec[]): FieldSpec[] => fields.filter((field) => field.create_only);

/** Fields a term edit changes with a generic PATCH, in registry order. */
export const editableTermFields = (fields: readonly FieldSpec[]): FieldSpec[] =>
  fields.filter((field) => field.editable && !field.create_only && !isReadOnlyType(field));

/** Fields of the "Add term" form besides the identity (`in_create`, without read-only types). */
export const createTermFields = (fields: readonly FieldSpec[]): FieldSpec[] =>
  fields.filter((field) => field.in_create && !field.create_only && !isReadOnlyType(field));

/** The entries of `values` that differ from `base`: what a save sends (nothing else). */
export function changedValues(base: JsonObject, values: JsonObject): JsonObject {
  return Object.fromEntries(Object.entries(values).filter(([name, value]) => !valuesEqual(base[name] ?? null, value)));
}

/** The values of `names` in `fields` (missing ones as null). */
export const pickValues = (fields: JsonObject, names: readonly string[]): JsonObject =>
  Object.fromEntries(names.map((name) => [name, fields[name] ?? null]));

export const attributesOf = (value: JsonValue | undefined): JsonObject => (isJsonObject(value) ? value : {});

/** A copy of `attributes` with one key set. */
export const withAttribute = (attributes: JsonValue | undefined, key: string, value: JsonValue): JsonObject => ({
  ...attributesOf(attributes),
  [key]: value,
});

/** Program logic uses the codes: they cannot be added or deactivated (409 fixed_code). */
export const isFixedVocabulary = (vocabulary: Vocabulary): boolean => vocabulary.fixed_codes;

export const isFixedTerm = (vocabulary: Vocabulary, attributes: JsonValue | undefined): boolean =>
  vocabulary.fixed_codes || attributesOf(attributes).fixed === true;

/** Codes a term can be replaced by: active codes of its vocabulary except its own. */
export const replacementCodes = (vocabulary: Vocabulary, ownCode: string | null): VocabTerm[] =>
  vocabulary.terms.filter((term) => term.active && term.code !== ownCode);

/** A copy of `record` without `key` (e.g. a server error once its field changes). */
export const omitKey = <T>(record: Readonly<Record<string, T>>, key: string): Record<string, T> =>
  Object.fromEntries(Object.entries(record).filter(([name]) => name !== key));

/** Server validation messages by field (last path segment, e.g. `changes.label_en`); the rest are general. */
export function splitValidationErrors(
  details: ValidationErrorDetails,
  names: readonly string[],
): { byField: Record<string, string>; other: string[] } {
  const byField: Record<string, string> = {};
  const other: string[] = [];
  for (const [path, messages] of Object.entries(details)) {
    const name = path.split('.').pop() ?? path;
    if (names.includes(name)) byField[name] = messages.join(' ');
    else other.push(`${path}: ${messages.join(' ')}`);
  }
  return { byField, other };
}

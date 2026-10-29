// Client-side format checks per field type (docs/DATA_MODEL.md §1.1, §1.2,
// §2.1). They give early feedback; the server stays authoritative, also for
// lengths, vocabulary codes and references.
import type { FieldSpec, JsonValue } from '../api/types';
import { asStringArray, isEmptyValue } from './format';
import { partialDateError } from './partial-date';
import { urlInputError } from './urls';

const SLUG_PATTERN = /^[a-z0-9]+(-[a-z0-9]+)*$/;
const SLUG_MAX = 100;

export const SLUG_HINT = 'Lowercase letters and digits, separated by single hyphens (e.g. example-project).';

export function slugError(value: string): string | null {
  const slug = value.trim();
  if (slug === '') return null;
  if (slug.length > SLUG_MAX) return `At most ${SLUG_MAX} characters.`;
  return SLUG_PATTERN.test(slug) ? null : SLUG_HINT;
}

/** Format error of a non-empty value, or null. */
export function fieldValueError(field: FieldSpec, value: JsonValue): string | null {
  if (isEmptyValue(value)) return null;
  switch (field.type) {
    case 'slug':
      return typeof value === 'string' ? slugError(value) : 'Enter text.';
    case 'url':
      return typeof value === 'string' ? urlInputError(value) : 'Enter a URL.';
    case 'url_list': {
      const errors = asStringArray(value)
        .map((url, index) => {
          const error = urlInputError(url);
          return error ? `Line ${index + 1}: ${error}` : null;
        })
        .filter((error) => error !== null);
      return errors.length ? errors.join(' ') : null;
    }
    case 'partial_date':
      return typeof value === 'string' ? partialDateError(value) : 'Enter a date.';
    case 'int':
      return typeof value === 'number' && Number.isInteger(value) ? null : 'Enter a whole number.';
    case 'number':
      return typeof value === 'number' && Number.isFinite(value) ? null : 'Enter a number.';
    default:
      return null;
  }
}

/** Missing value of a required field (after trimming text). */
export function isMissingRequired(field: FieldSpec, value: JsonValue): boolean {
  if (!field.required || field.type === 'bool') return false;
  return isEmptyValue(typeof value === 'string' ? value.trim() : value);
}

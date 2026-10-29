// Human-readable descriptions of active filters (empty states explain the
// active filters, docs/UI.md §3).
import type { FieldSpec } from '../api/types';
import {
  EMPTY_TOKEN,
  parseBoolFilter,
  parseDateRangeFilter,
  parseMultiselectFilter,
  parseNumberRangeFilter,
  parseRefFilter,
  parseTextFilter,
  type MultiselectOp,
} from './query-string';

/** Labels for codes and IDs (vocabulary terms, lookup labels). */
export type ValueLabeler = (field: FieldSpec, value: string) => string;

const LIST_OP_WORDS: Record<MultiselectOp, string> = {
  in: 'is any of',
  nin: 'is none of',
  any: 'has any of',
  all: 'has all of',
  none: 'has none of',
};

function labels(field: FieldSpec, values: readonly string[], label: ValueLabeler): string {
  return values.map((value) => (value === EMPTY_TOKEN ? '(empty)' : label(field, value))).join(', ');
}

/** Open bounds are spelled out exactly: `overlaps from X` means the interval ends on or after X. */
function dateRangeText(name: string, op: 'overlaps' | 'within', from: string, to: string): string {
  if (from && to) return `${name} ${op === 'within' ? 'lies within' : 'overlaps'} ${from} – ${to}`;
  if (op === 'within') return from ? `${name} lies on or after ${from}` : `${name} lies on or before ${to}`;
  return from ? `${name} ends on or after ${from}` : `${name} starts on or before ${to}`;
}

/** e.g. `Kind is any of E-service, (empty)`; falls back to the raw value. */
export function describeFilter(field: FieldSpec, raw: string, label: ValueLabeler): string {
  const name = field.label;
  switch (field.filter) {
    case 'text': {
      const value = parseTextFilter(raw);
      if (!value) break;
      if (value.op === 'empty') return `${name} is ${value.empty ? 'empty' : 'not empty'}`;
      return `${name} ${value.op === 'eq' ? 'equals' : 'contains'} “${value.text}”`;
    }
    case 'multiselect': {
      const value = parseMultiselectFilter(raw, field.type === 'vocab_list');
      if (!value) break;
      return `${name} ${LIST_OP_WORDS[value.op]} ${labels(field, value.values, label)}`;
    }
    case 'date_range': {
      const value = parseDateRangeFilter(raw);
      if (!value) break;
      if (value.op === 'empty') return `${name} is ${value.empty ? 'empty' : 'not empty'}`;
      return dateRangeText(name, value.op, value.from, value.to);
    }
    case 'bool': {
      const value = parseBoolFilter(raw);
      if (value === null) break;
      return `${name}: ${value ? 'yes' : 'no'}`;
    }
    case 'number_range': {
      const value = parseNumberRangeFilter(raw);
      if (!value) break;
      if (value.min !== null && value.max !== null) {
        return value.min === value.max ? `${name} = ${value.min}` : `${name} between ${value.min} and ${value.max}`;
      }
      return value.min !== null ? `${name} ≥ ${value.min}` : `${name} ≤ ${value.max ?? ''}`;
    }
    case 'ref': {
      const value = parseRefFilter(raw);
      if (!value) break;
      if (value.op === 'empty') return `${name} is ${value.empty ? 'empty' : 'not empty'}`;
      const qualifier = value.op === 'confirmed' ? ' (confirmed links)' : '';
      return `${name}${qualifier} is any of ${labels(field, value.ids, label)}`;
    }
    default:
      break;
  }
  return `${name}: ${raw}`;
}

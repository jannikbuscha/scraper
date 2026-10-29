// Partial dates (docs/DATA_MODEL.md §1.1): canonical strings only, years
// 1900–2100: YYYY · YYYY-Qn · YYYY-MM · YYYY-MM-DD.

export type DatePrecision = 'day' | 'month' | 'quarter' | 'year';

export interface PartialDate {
  value: string;
  precision: DatePrecision;
  /** First day of the interval, YYYY-MM-DD. */
  start: string;
  /** Last day of the interval (inclusive), YYYY-MM-DD. */
  end: string;
}

export const PARTIAL_DATE_HINT = 'YYYY · YYYY-Qn · YYYY-MM · YYYY-MM-DD';

const MIN_YEAR = 1900;
const MAX_YEAR = 2100;

const pad2 = (n: number): string => String(n).padStart(2, '0');

function daysInMonth(year: number, month: number): number {
  return new Date(Date.UTC(year, month, 0)).getUTCDate();
}

const isoDay = (year: number, month: number, day: number): string => `${year}-${pad2(month)}-${pad2(day)}`;

/** Parses a canonical partial date; anything else (e.g. `2022-q1`, `2022-02-30`) is null. */
export function parsePartialDate(value: string): PartialDate | null {
  const match = /^(\d{4})(?:-(?:Q([1-4])|(\d{2})(?:-(\d{2}))?))?$/.exec(value);
  if (!match) return null;
  const [, yearText, quarterText, monthText, dayText] = match;
  const year = Number(yearText);
  if (year < MIN_YEAR || year > MAX_YEAR) return null;

  if (quarterText !== undefined) {
    const firstMonth = (Number(quarterText) - 1) * 3 + 1;
    const lastMonth = firstMonth + 2;
    return {
      value,
      precision: 'quarter',
      start: isoDay(year, firstMonth, 1),
      end: isoDay(year, lastMonth, daysInMonth(year, lastMonth)),
    };
  }
  if (monthText === undefined) {
    return { value, precision: 'year', start: isoDay(year, 1, 1), end: isoDay(year, 12, 31) };
  }
  const month = Number(monthText);
  if (month < 1 || month > 12) return null;
  if (dayText === undefined) {
    return { value, precision: 'month', start: isoDay(year, month, 1), end: isoDay(year, month, daysInMonth(year, month)) };
  }
  const day = Number(dayText);
  if (day < 1 || day > daysInMonth(year, month)) return null;
  const iso = isoDay(year, month, day);
  return { value, precision: 'day', start: iso, end: iso };
}

/** Live-validation message for an input value; null if valid or empty. */
export function partialDateError(input: string): string | null {
  const value = input.trim();
  if (value === '' || parsePartialDate(value)) return null;
  if (/^\d{4}-q[1-4]$/.test(value)) return 'Write the quarter with an uppercase Q, e.g. 2022-Q1.';
  const year = /^(\d{4})/.exec(value)?.[1];
  if (year !== undefined && (Number(year) < MIN_YEAR || Number(year) > MAX_YEAR)) {
    return `The year must lie between ${MIN_YEAR} and ${MAX_YEAR}.`;
  }
  if (/^\d{4}-\d{2}-\d{2}$/.test(value) || /^\d{4}-\d{2}$/.test(value)) return 'This date does not exist.';
  return `Use one of ${PARTIAL_DATE_HINT}.`;
}

/** Precision of a canonical string (null if not canonical). */
export const partialDatePrecision = (value: string): DatePrecision | null => parsePartialDate(value)?.precision ?? null;

/** Display form with precision hint, e.g. `2020-06 · month`. */
export function formatPartialDate(value: string): string {
  const precision = partialDatePrecision(value);
  return precision ? `${value} · ${precision}` : value;
}

/** True for a valid calendar date `YYYY-MM-DD` (any year). */
export function isIsoDate(value: string): boolean {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  if (!match) return false;
  const month = Number(match[2]);
  const day = Number(match[3]);
  return month >= 1 && month <= 12 && day >= 1 && day <= daysInMonth(Number(match[1]), month);
}

/** Calendar arithmetic on `YYYY-MM-DD`, independent of the local time zone. */
export function addDays(value: string, days: number): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  if (!match) throw new Error(`Not a calendar date: ${value}`);
  const date = new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3]) + days));
  return isoDay(date.getUTCFullYear(), date.getUTCMonth() + 1, date.getUTCDate());
}

import { describe, expect, it } from 'vitest';

import { addDays, formatPartialDate, isIsoDate, parsePartialDate, partialDateError } from './partial-date';

describe('parsePartialDate', () => {
  it('accepts the four canonical forms with their intervals', () => {
    expect(parsePartialDate('2020')).toEqual({ value: '2020', precision: 'year', start: '2020-01-01', end: '2020-12-31' });
    expect(parsePartialDate('2022-Q1')).toEqual({
      value: '2022-Q1',
      precision: 'quarter',
      start: '2022-01-01',
      end: '2022-03-31',
    });
    expect(parsePartialDate('2024-02')).toMatchObject({ precision: 'month', start: '2024-02-01', end: '2024-02-29' });
    expect(parsePartialDate('2023-02')).toMatchObject({ end: '2023-02-28' });
    expect(parsePartialDate('2022-02-24')).toMatchObject({ precision: 'day', start: '2022-02-24', end: '2022-02-24' });
    expect(parsePartialDate('2021-Q4')).toMatchObject({ start: '2021-10-01', end: '2021-12-31' });
  });

  it('rejects non-canonical strings', () => {
    for (const value of ['2022-q1', '2022-Q5', '2022-02-30', '2022-13', '22', '1899', '2101', '2022-2', ' 2022', '2022-01-01T00']) {
      expect(parsePartialDate(value), value).toBeNull();
    }
  });
});

describe('partialDateError', () => {
  it('explains why a value is invalid', () => {
    expect(partialDateError('')).toBeNull();
    expect(partialDateError(' 2020-06 ')).toBeNull();
    expect(partialDateError('2022-q1')).toMatch(/uppercase Q/);
    expect(partialDateError('1850')).toMatch(/between 1900 and 2100/);
    expect(partialDateError('2022-02-30')).toMatch(/does not exist/);
    expect(partialDateError('June 2020')).toMatch(/YYYY · YYYY-Qn/);
  });
});

describe('formatting and calendar helpers', () => {
  it('adds the precision hint', () => {
    expect(formatPartialDate('2020-06')).toBe('2020-06 · month');
    expect(formatPartialDate('2022-Q1')).toBe('2022-Q1 · quarter');
    expect(formatPartialDate('not a date')).toBe('not a date');
  });

  it('validates calendar dates and adds days across month and year ends', () => {
    expect(isIsoDate('2024-02-29')).toBe(true);
    expect(isIsoDate('2023-02-29')).toBe(false);
    expect(addDays('2019-08-29', -1)).toBe('2019-08-28');
    expect(addDays('2022-03-01', -1)).toBe('2022-02-28');
    expect(addDays('2021-12-31', 1)).toBe('2022-01-01');
  });
});

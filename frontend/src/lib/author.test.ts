import { describe, expect, it, vi } from 'vitest';

import {
  AUTHOR_STORAGE_KEY,
  encodeAuthorHeader,
  normalizeAuthor,
  readRecentAuthors,
  readStoredAuthor,
  RECENT_AUTHORS_STORAGE_KEY,
  setAuthor,
  subscribeAuthor,
  validateAuthor,
} from './author';

const invalid = (raw: string) => {
  const result = validateAuthor(raw);
  return result.ok ? null : result.error;
};

describe('normalizeAuthor', () => {
  it('applies NFC, trims and collapses whitespace like the server', () => {
    expect(normalizeAuthor('  Anna \t  Example\n')).toBe('Anna Example');
    // U+0065 U+0301 (e + combining acute) becomes U+00E9.
    expect(normalizeAuthor('René')).toBe('René');
    // No-break space, ideographic space and line separator count as whitespace.
    expect(normalizeAuthor('Олена 　Приклад ')).toBe('Олена Приклад');
  });
});

describe('validateAuthor', () => {
  it('accepts ordinary names in Latin and Cyrillic script', () => {
    expect(validateAuthor(' Example  Person ')).toEqual({ ok: true, name: 'Example Person' });
    expect(validateAuthor('Олена Приклад')).toEqual({ ok: true, name: 'Олена Приклад' });
  });

  it('refuses empty names, commas and over-long names', () => {
    expect(invalid('   ')).toMatch(/Enter a name/);
    expect(invalid('Doe, Jane')).toMatch(/comma/);
    expect(invalid('x'.repeat(101))).toMatch(/100/);
    expect(validateAuthor('я'.repeat(100)).ok).toBe(true);
  });

  it('refuses control, format, bidi and zero-width characters', () => {
    for (const raw of ['Anna\u0000', 'Anna\u0007x', 'An​na', 'Anna‮', 'An⁦na', '﻿Anna', 'An­na']) {
      expect(invalid(raw), JSON.stringify(raw)).toMatch(/control, invisible/);
    }
  });

  it('refuses lone surrogates', () => {
    expect(invalid('Anna\ud800')).not.toBeNull();
  });

  it('refuses reserved names, case-insensitively and with case folding', () => {
    for (const raw of ['seed', 'SEED', 'System', 'ſeed', 'syﬆem', 'collector:c1', 'import:file.csv', 'manual:Anna', '_x:y']) {
      expect(invalid(raw), raw).toMatch(/reserved/);
    }
    expect(validateAuthor('Seedling').ok).toBe(true);
    expect(validateAuthor('Anna: reviewer').ok).toBe(false);
    expect(validateAuthor('Anna 2: reviewer').ok).toBe(true);
  });
});

describe('X-Author encoding', () => {
  it('percent-encodes UTF-8', () => {
    expect(encodeAuthorHeader('Олена Приклад')).toBe('%D0%9E%D0%BB%D0%B5%D0%BD%D0%B0%20%D0%9F%D1%80%D0%B8%D0%BA%D0%BB%D0%B0%D0%B4');
    expect(encodeAuthorHeader('A&B=C%')).toBe('A%26B%3DC%25');
  });

  it('catches encodeURIComponent errors for lone surrogates', () => {
    expect(encodeAuthorHeader('\ud800')).toBeNull();
  });
});

describe('storage', () => {
  it('stores the name and keeps a list of recent names', () => {
    expect(setAuthor('First Person').ok).toBe(true);
    expect(setAuthor(' Second  Person ').ok).toBe(true);
    expect(setAuthor('First Person').ok).toBe(true);
    expect(readStoredAuthor()).toBe('First Person');
    expect(window.localStorage.getItem(AUTHOR_STORAGE_KEY)).toBe('First Person');
    expect(readRecentAuthors()).toEqual(['First Person', 'Second Person']);
  });

  it('does not store invalid names and ignores tampered storage', () => {
    expect(setAuthor('seed').ok).toBe(false);
    expect(readStoredAuthor()).toBeNull();
    window.localStorage.setItem(AUTHOR_STORAGE_KEY, 'Anna‮');
    expect(readStoredAuthor()).toBeNull();
    window.localStorage.setItem(RECENT_AUTHORS_STORAGE_KEY, '{"not":"a list"}');
    expect(readRecentAuthors()).toEqual([]);
    window.localStorage.setItem(RECENT_AUTHORS_STORAGE_KEY, '["Valid", "system", 3, "Valid"]');
    expect(readRecentAuthors()).toEqual(['Valid']);
  });

  it('notifies subscribers on change', () => {
    const listener = vi.fn();
    const unsubscribe = subscribeAuthor(listener);
    setAuthor('Example Person');
    expect(listener).toHaveBeenCalledTimes(1);
    unsubscribe();
    setAuthor('Other Person');
    expect(listener).toHaveBeenCalledTimes(1);
  });
});

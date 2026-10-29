import { describe, expect, it } from 'vitest';

import { safeExternalUrl, urlHost, urlInputError } from './urls';

describe('safeExternalUrl', () => {
  it('accepts http and https URLs and reports the punycode host', () => {
    expect(safeExternalUrl('https://example.org/path?q=1')).toEqual({
      href: 'https://example.org/path?q=1',
      host: 'example.org',
    });
    expect(safeExternalUrl('http://example.org:8080/')?.host).toBe('example.org:8080');
    expect(safeExternalUrl('https://приклад.укр/')?.host).toBe('xn--80aikifvh.xn--j1amh');
  });

  it('refuses other schemes, smuggled schemes, userinfo and relative URLs', () => {
    for (const value of [
      'javascript:alert(1)',
      'JavaScript:alert(1)',
      'java\tscript:alert(1)',
      ' javascript:alert(1)',
      'data:text/html,<script>alert(1)</script>',
      'vbscript:msgbox(1)',
      'https://user:secret@example.org/',
      'https://user@example.org/',
      '//example.org/',
      '/relative/path',
      'example.org',
      '',
    ]) {
      expect(safeExternalUrl(value), JSON.stringify(value)).toBeNull();
    }
  });

  it('extracts hosts for display', () => {
    expect(urlHost('https://sub.example.org/a')).toBe('sub.example.org');
    expect(urlHost('not a url')).toBeNull();
  });
});

describe('urlInputError', () => {
  it('mirrors the URL rules of the data model', () => {
    expect(urlInputError('')).toBeNull();
    expect(urlInputError('https://example.org/a')).toBeNull();
    expect(urlInputError('https://example.org/a b')).toMatch(/spaces/);
    expect(urlInputError('ftp://example.org/')).toMatch(/http and https/);
    expect(urlInputError('https://a@example.org/')).toMatch(/user name/);
    expect(urlInputError('example.org')).toMatch(/absolute URL/);
    expect(urlInputError(`https://example.org/${'a'.repeat(2000)}`)).toMatch(/2000/);
  });
});

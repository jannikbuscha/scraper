import { describe, expect, it } from 'vitest';

import { urlHost, urlInputError } from './urls';

describe('urlHost', () => {
  it('extracts the punycode host with its port for display', () => {
    expect(urlHost('https://sub.example.org/a')).toBe('sub.example.org');
    expect(urlHost('http://example.org:8080/')).toBe('example.org:8080');
    expect(urlHost('https://приклад.укр/')).toBe('xn--80aikifvh.xn--j1amh');
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

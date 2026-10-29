// Rules for links built from data (docs/UI.md §1.4). Only ExternalLink uses
// safeExternalUrl to render an href; everything else shows URLs as text.

export interface SafeUrl {
  /** The parsed, re-serialised URL used as href. */
  href: string;
  /** `URL.host`: punycode host plus port, shown next to the link text. */
  host: string;
}

/**
 * An http(s) URL without userinfo, or null. `new URL` strips tabs and
 * newlines, so `java\tscript:` is recognised as `javascript:` and refused.
 */
export function safeExternalUrl(value: string): SafeUrl | null {
  let url: URL;
  try {
    url = new URL(value);
  } catch {
    return null;
  }
  if (url.protocol !== 'http:' && url.protocol !== 'https:') return null;
  if (url.username !== '' || url.password !== '' || url.host === '') return null;
  return { href: url.href, host: url.host };
}

/** Host for display (e.g. the first host of a URL list), or null for invalid URLs. */
export const urlHost = (value: string): string | null => safeExternalUrl(value)?.host ?? null;

/**
 * Client-side check of the URL rules of docs/DATA_MODEL.md §1.2 for inputs;
 * the server stays authoritative. Returns an error message or null.
 */
export function urlInputError(input: string): string | null {
  const value = input.trim();
  if (value === '') return null;
  // eslint-disable-next-line no-control-regex -- C0/C1 control characters are exactly what is refused
  if (/[\s\u0000-\u001f\u007f-\u009f]/.test(value)) return 'A URL cannot contain spaces or control characters.';
  if (value.length > 2000) return 'A URL can have at most 2000 characters.';
  let url: URL;
  try {
    url = new URL(value);
  } catch {
    return 'Enter an absolute URL starting with http:// or https://.';
  }
  if (url.protocol !== 'http:' && url.protocol !== 'https:') return 'Only http and https URLs are allowed.';
  if (url.username !== '' || url.password !== '') return 'A URL cannot contain a user name or password.';
  if (url.hostname === '') return 'The URL needs a host.';
  return null;
}

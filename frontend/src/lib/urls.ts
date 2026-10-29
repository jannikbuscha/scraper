// URL helpers: the host shown next to links, and the client-side check of URL
// inputs.

/** `URL.host` (punycode host plus port) for display, or null if the value is no absolute URL. */
export function urlHost(value: string): string | null {
  try {
    return new URL(value).host || null;
  } catch {
    return null;
  }
}

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
